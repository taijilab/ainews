from __future__ import annotations

import json
import os
from pathlib import Path
import re
from functools import lru_cache
from typing import Dict, List, Optional
from xml.etree import ElementTree as ET

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
import requests

from db.store import Store
from crawler.fetcher import fetch_feed


DB_PATH = os.getenv("AINEWS_DB_PATH", "data/ainews.db")
store = Store(DB_PATH)
store.init_db()

app = FastAPI(title="AI News Daily API", version="0.1.0")
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


_ZH_RE = re.compile(r"[\u4e00-\u9fff]")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


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
    try:
        if store.feed_count() == 0:
            prefill_sources_from_local_gist({"path": "data/gist_sources_weekly.json"})
    except Exception:
        pass
    return FileResponse(STATIC_DIR / "sources.html")


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
    return [dict(r) for r in store.api_available_dates(limit=limit)]


@app.get("/api/daily")
def get_daily(day: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$")) -> Dict:
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
    return [dict(r) for r in store.api_sources(days=days)]


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
        # Fallback to online gist import if local snapshot does not exist.
        return import_sources_from_gist({"probe": False})

    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "imported": 0, "error": str(exc)[:240]}

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
        store.update_feed_meta(feed_id, source_topic=topic if topic else None, source_status=status if status else None)
        imported += 1
    return {"ok": True, "imported": imported, "path": str(p)}
