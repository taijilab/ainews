from __future__ import annotations

import json
import os
from pathlib import Path
import re
from functools import lru_cache
from typing import Dict, List, Optional
from xml.etree import ElementTree as ET
import sqlite3

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
import requests

from db.store import Store
from db.store import PostRecord
from crawler.fetcher import fetch_feed
from processor.cleaner import canonicalize_url, normalize_text, stable_hash
from nlp.classifier import RuleClassifier
from nlp.entity_extractor import EntityExtractor
from topic_engine.topic_builder import TopicBuilder


def _is_serverless() -> bool:
    return bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))


def _build_store() -> Store:
    env_db = os.getenv("AINEWS_DB_PATH")
    db_path = env_db if env_db else ("/tmp/ainews.db" if _is_serverless() else "data/ainews.db")

    primary = Store(db_path)
    try:
        primary.init_db()
        return primary
    except (sqlite3.OperationalError, PermissionError, OSError):
        # In serverless runtime, writeable filesystem is typically /tmp only.
        if db_path != "/tmp/ainews.db":
            fallback = Store("/tmp/ainews.db")
            fallback.init_db()
            return fallback
        raise


store = _build_store()

app = FastAPI(title="AI News Daily API", version="0.1.0")
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


_ZH_RE = re.compile(r"[\u4e00-\u9fff]")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _seed_sources_from_snapshot(path: str = "data/gist_sources_weekly.json") -> int:
    base_dir = Path(__file__).resolve().parents[1]
    candidates = [
        Path(path),
        base_dir / path,
        base_dir / "data" / "gist_sources_weekly.json",
    ]
    p = None
    for c in candidates:
        if c.exists():
            p = c
            break
    if p is None:
        return 0

    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return 0

    rows = obj.get("rows") or []
    imported = 0
    for r in rows:
        feed_url = (r.get("rss_url") or "").strip()
        if not feed_url:
            continue
        title = (r.get("name") or "").strip()
        site_url = (r.get("blog_address") or "").strip()
        topic = (r.get("topic") or "").strip()
        status = (r.get("network_status") or "").strip()
        feed_id = store.upsert_feed(feed_url=feed_url, title=title, site_url=site_url)
        store.update_feed_meta(
            feed_id,
            source_topic=topic if topic else None,
            source_status=status if status else None,
        )
        imported += 1
    return imported


def _ensure_sources_seeded() -> None:
    try:
        if store.feed_count() > 0:
            return
        seeded = _seed_sources_from_snapshot("data/gist_sources_weekly.json")
        if seeded == 0:
            # Last fallback: try online gist import when local snapshot is unavailable.
            import_sources_from_gist({"probe": False})
    except Exception:
        pass


_post_bootstrap_attempted = False
_classifier = None
_entity_extractor = None
_topic_builder = None


def _ensure_nlp_components() -> None:
    global _classifier, _entity_extractor, _topic_builder
    if _classifier and _entity_extractor and _topic_builder:
        return
    base_dir = Path(__file__).resolve().parents[1]
    cfg_dir = base_dir / "config"
    _classifier = RuleClassifier(str(cfg_dir / "taxonomy.yaml"))
    _entity_extractor = EntityExtractor(str(cfg_dir / "entities.yaml"))
    _topic_builder = TopicBuilder(str(cfg_dir / "topic_builder.yaml"))


def _bootstrap_posts_if_empty() -> None:
    global _post_bootstrap_attempted
    if store.post_count() > 0:
        return
    if _post_bootstrap_attempted:
        return
    _post_bootstrap_attempted = True

    _ensure_sources_seeded()
    feeds = store.list_feeds(limit=10)
    if not feeds:
        return

    inserted_ids: list[int] = []
    for f in feeds:
        feed_id = int(f["id"])
        feed_url = str(f["feed_url"])
        ok = True
        try:
            meta, entries = fetch_feed(feed_url, timeout=8)
            store.upsert_feed(
                feed_url=feed_url,
                title=meta.get("feed_title", str(f["title"] or "")),
                site_url=meta.get("site_url", str(f["site_url"] or "")),
            )
            posts: list[PostRecord] = []
            for e in entries[:25]:
                canon_url = canonicalize_url(e.url)
                title_norm = normalize_text(e.title)
                content_hash = stable_hash(title_norm, normalize_text(e.summary), normalize_text(e.content))
                posts.append(
                    PostRecord(
                        feed_id=feed_id,
                        blog_id=e.blog_id,
                        guid=e.guid,
                        title=e.title,
                        url=e.url,
                        canonical_url=canon_url,
                        author=e.author,
                        published_at=e.published_at,
                        summary=e.summary,
                        content=e.content,
                        title_norm=title_norm,
                        content_hash=content_hash,
                    )
                )
            inserted_ids.extend(store.insert_posts(posts))
        except Exception:
            ok = False
        store.mark_feed_fetch(feed_id, ok)

    if not inserted_ids:
        return

    _ensure_nlp_components()
    placeholders = ",".join("?" for _ in inserted_ids)
    with store.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT id, title, summary, content
            FROM posts
            WHERE id IN ({placeholders})
            """,
            inserted_ids,
        ).fetchall()

    for row in rows:
        post_id = int(row["id"])
        text = "\n".join([row["title"] or "", row["summary"] or "", row["content"] or ""])
        labels = _classifier.classify(text) if _classifier else []
        entities = _entity_extractor.extract(text) if _entity_extractor else []
        store.add_labels(post_id, labels)
        store.add_entities(post_id, entities)
        keywords = set(normalize_text(text).split())
        topic_id, evidence = _topic_builder.assign_topic(entities, labels, keywords) if _topic_builder else (None, {})
        if topic_id:
            title = entities[0]["canonical"] if entities else (row["title"] or "Topic")
            primary_entity = entities[0]["id"] if entities else None
            store.upsert_topic(topic_id, "ENTITY" if entities else "CLUSTER", title, primary_entity)
            store.bind_post_topic(topic_id, post_id, 1.0, evidence)


def _to_cn_text(text: str, limit: int = 220) -> str:
    value = (text or "").strip()
    if not value:
        return ""
    value = _HTML_TAG_RE.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > limit:
        value = value[: limit - 1] + "…"
    if _ZH_RE.search(value):
        return value
    return f"（英文）{value}"


@lru_cache(maxsize=4096)
def _translate_to_zh(text: str, limit: int = 220) -> str:
    value = (text or "").strip()
    if not value:
        return ""
    if _ZH_RE.search(value):
        return _to_cn_text(value, limit=limit)
    try:
        q = value[:800]
        resp = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "auto", "tl": "zh-CN", "dt": "t", "q": q},
            timeout=3,
        )
        resp.raise_for_status()
        data = resp.json()
        translated = "".join(part[0] for part in (data[0] or []) if part and part[0])
        translated = _to_cn_text(translated, limit=limit)
        if translated:
            return translated
    except Exception:
        pass
    # fallback: keep readable Chinese-prefixed text when translation endpoint is unavailable.
    return _to_cn_text(value, limit=limit)


@app.get("/healthz")
def healthz() -> Dict[str, bool]:
    return {"ok": True}


@app.get("/")
def web_home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/sources")
def web_sources() -> FileResponse:
    _ensure_sources_seeded()
    return FileResponse(STATIC_DIR / "sources.html")


@app.get("/browse")
def web_browse() -> FileResponse:
    return FileResponse(STATIC_DIR / "browse.html")


@app.get("/favicon.ico")
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/api/topics")
def get_topics(window: str = Query("24h"), sort: str = Query("hot")) -> List[Dict]:
    rows = store.api_topics(window=window, sort=sort)
    out = []
    for r in rows:
        item = dict(r)
        item["breakdown"] = json.loads(item.pop("breakdown_json"))
        out.append(item)
    return out


@app.get("/api/topics/{topic_id}")
def get_topic(topic_id: str) -> Dict:
    return store.api_topic_detail(topic_id) or {"topic": None, "posts": []}


@app.get("/api/posts")
def get_posts(label: Optional[str] = None, after: Optional[str] = None) -> List[Dict]:
    return [dict(r) for r in store.api_posts(label=label, after=after)]


@app.get("/api/entities")
def get_entities(q: str = Query(..., min_length=1)) -> List[Dict]:
    return [dict(r) for r in store.api_entities(q)]


@app.get("/api/dates")
def get_available_dates(limit: int = Query(90, ge=1, le=365)) -> List[Dict]:
    _bootstrap_posts_if_empty()
    return [dict(r) for r in store.api_available_dates(limit=limit)]


@app.get("/api/daily")
def get_daily(day: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$")) -> Dict:
    _bootstrap_posts_if_empty()
    digest = store.api_daily_digest(day)
    posts = []
    for p in digest.get("posts", []):
        labels = [x for x in (p.get("label_tags") or "").split(",") if x]
        topics = [x for x in (p.get("topic_tags") or "").split(",") if x]
        item = dict(p)
        item["labels"] = labels
        item["topics"] = topics
        item["zh_title"] = _translate_to_zh(item.get("title", ""), limit=120)
        item["zh_summary"] = _translate_to_zh(item.get("summary", ""), limit=220)
        posts.append(item)
    digest["posts"] = posts
    return digest


@app.get("/api/sources")
def get_sources(days: int = Query(7, ge=1, le=30)) -> List[Dict]:
    _ensure_sources_seeded()
    return [dict(r) for r in store.api_sources(days=days)]


@app.get("/api/browse")
def api_browse(
    kind: str = Query(..., pattern=r"^(topic|tag)$"),
    value: str = Query(..., min_length=1),
    limit: int = Query(300, ge=1, le=1000),
) -> Dict:
    rows = [dict(r) for r in store.api_browse_posts(kind=kind, value=value, limit=limit)]
    for item in rows:
        item["zh_title"] = _translate_to_zh(item.get("title", ""), limit=120)
        item["zh_summary"] = _translate_to_zh(item.get("summary", ""), limit=220)
    return {"kind": kind, "value": value, "count": len(rows), "posts": rows}


@app.post("/api/sources")
def add_source(payload: Dict) -> Dict:
    feed_url = (payload.get("feed_url") or "").strip()
    title = (payload.get("title") or "").strip()
    site_url = (payload.get("site_url") or "").strip()
    probe = bool(payload.get("probe", True))

    if not feed_url.startswith("http://") and not feed_url.startswith("https://"):
        return {"ok": False, "error": "feed_url must start with http:// or https://"}

    feed_id = store.upsert_feed(feed_url=feed_url, title=title, site_url=site_url)
    probe_error = ""
    source_topic = (payload.get("topic") or "").strip()
    source_status = (payload.get("network_status") or "").strip()
    if probe:
        try:
            meta, _ = fetch_feed(feed_url)
            store.upsert_feed(feed_url=feed_url, title=meta.get("feed_title", title), site_url=meta.get("site_url", site_url))
            store.mark_feed_fetch(feed_id, True)
        except Exception as exc:
            store.mark_feed_fetch(feed_id, False)
            probe_error = str(exc)[:200]
    if source_topic:
        store.update_feed_meta(feed_id, source_topic=source_topic)
    if source_status:
        store.update_feed_meta(feed_id, source_status=source_status)

    return {"ok": True, "feed_id": feed_id, "probe_error": probe_error}


@app.delete("/api/sources/{feed_id}")
def delete_source(feed_id: int, purge_posts: bool = Query(True)) -> Dict:
    ok = store.delete_feed(feed_id=feed_id, purge_posts=purge_posts)
    return {"ok": ok}


@app.post("/api/sources/{feed_id}/refresh")
def refresh_source(feed_id: int) -> Dict:
    row = store.get_feed(feed_id)
    if not row:
        return {"ok": False, "error": "source not found"}

    feed_url = str(row["feed_url"])
    try:
        meta, _ = fetch_feed(feed_url)
        store.upsert_feed(
            feed_url=feed_url,
            title=meta.get("feed_title", str(row["title"] or "")),
            site_url=meta.get("site_url", str(row["site_url"] or "")),
        )
        store.mark_feed_fetch(feed_id, True)
        store.update_feed_meta(feed_id, source_status="OK")
        return {"ok": True, "network_status": "OK"}
    except Exception as exc:
        store.mark_feed_fetch(feed_id, False)
        store.update_feed_meta(feed_id, source_status="ERROR")
        return {"ok": False, "network_status": "ERROR", "error": str(exc)[:200]}


@app.post("/api/sources/import-gist")
def import_sources_from_gist(payload: Optional[Dict] = None) -> Dict:
    data = payload or {}
    gist_raw_url = data.get(
        "gist_raw_url",
        "https://gist.githubusercontent.com/emschwartz/e6d2bf860ccc367fe37ff953ba6de66b/raw/hn-popular-blogs-2025.opml",
    )
    timeout = int(data.get("timeout", 30))
    probe = bool(data.get("probe", False))

    try:
        resp = requests.get(gist_raw_url, timeout=timeout)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except Exception as exc:
        return {"ok": False, "imported": 0, "gist_raw_url": gist_raw_url, "error": str(exc)[:240]}

    imported = 0
    for node in root.findall('.//outline[@xmlUrl]'):
        feed_url = (node.attrib.get("xmlUrl") or "").strip()
        if not feed_url:
            continue
        title = (node.attrib.get("title") or node.attrib.get("text") or "").strip()
        site_url = (node.attrib.get("htmlUrl") or "").strip()
        feed_id = store.upsert_feed(feed_url=feed_url, title=title, site_url=site_url)
        imported += 1
        if probe:
            try:
                meta, _ = fetch_feed(feed_url)
                store.upsert_feed(
                    feed_url=feed_url,
                    title=meta.get("feed_title", title),
                    site_url=meta.get("site_url", site_url),
                )
                store.mark_feed_fetch(feed_id, True)
            except Exception:
                store.mark_feed_fetch(feed_id, False)

    return {"ok": True, "imported": imported, "gist_raw_url": gist_raw_url}


@app.post("/api/sources/prefill-local-gist")
def prefill_sources_from_local_gist(payload: Optional[Dict] = None) -> Dict:
    data = payload or {}
    path = data.get("path", "data/gist_sources_weekly.json")
    imported = _seed_sources_from_snapshot(path)
    if imported > 0:
        return {"ok": True, "imported": imported, "path": path}
    # Fallback to online gist import if local snapshot does not exist.
    return import_sources_from_gist({"probe": False})
