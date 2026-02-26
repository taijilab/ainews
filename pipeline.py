from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from crawler.fetcher import RawEntry, fetch_feed
from crawler.fulltext import CrawlerConfig, fetch_fulltext
from crawler.opml import parse_opml
from db.store import PostRecord, Store
from nlp.classifier import RuleClassifier
from nlp.entity_extractor import EntityExtractor
from processor.cleaner import canonicalize_url, normalize_text, stable_hash
from ranking.hot_score import HotScorer
from topic_engine.topic_builder import TopicBuilder


@dataclass
class PipelineConfig:
    db_path: str
    opml_path: str
    config_dir: str = "config"
    crawler_config: str = "config/crawler.yaml"


class DailyPipeline:
    def __init__(self, cfg: PipelineConfig):
        self.cfg = cfg
        cdir = Path(cfg.config_dir)
        self.store = Store(cfg.db_path)
        self.classifier = RuleClassifier(str(cdir / "taxonomy.yaml"))
        self.entity_extractor = EntityExtractor(str(cdir / "entities.yaml"))
        self.topic_builder = TopicBuilder(str(cdir / "topic_builder.yaml"))
        self.hot_scorer = HotScorer(str(cdir / "hot_config.yaml"))

    def init(self) -> None:
        self.store.init_db()

    def run_ingest(self) -> dict:
        feed_urls = parse_opml(self.cfg.opml_path)
        total_entries = 0
        total_inserted = 0

        for feed_url in feed_urls:
            feed_id = self.store.upsert_feed(feed_url)
            ok = True
            try:
                meta, entries = fetch_feed(feed_url)
                self.store.upsert_feed(feed_url, meta.get("feed_title", ""), meta.get("site_url", ""))
                total_entries += len(entries)
                posts = [self._to_post_record(feed_id, e) for e in entries]
                inserted = self.store.insert_posts(posts)
                total_inserted += len(inserted)
            except Exception:
                ok = False
            self.store.mark_feed_fetch(feed_id, ok)

        return {
            "feeds": len(feed_urls),
            "entries": total_entries,
            "inserted": total_inserted,
        }

    def run_annotate_and_topics(self) -> dict:
        with self.store.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.id, p.title, p.summary, p.content
                FROM posts p
                WHERE NOT EXISTS (SELECT 1 FROM post_labels pl WHERE pl.post_id = p.id)
                """
            ).fetchall()

        bound = 0
        for row in rows:
            post_id = int(row["id"])
            text = "\n".join([row["title"] or "", row["summary"] or "", row["content"] or ""])
            labels = self.classifier.classify(text)
            entities = self.entity_extractor.extract(text)
            self.store.add_labels(post_id, labels)
            self.store.add_entities(post_id, entities)

            keywords = set(normalize_text(text).split())
            topic_id, evidence = self.topic_builder.assign_topic(entities, labels, keywords)
            if topic_id:
                title = entities[0]["canonical"] if entities else row["title"]
                primary_entity = entities[0]["id"] if entities else None
                self.store.upsert_topic(topic_id, "ENTITY" if entities else "CLUSTER", title, primary_entity)
                self.store.bind_post_topic(topic_id, post_id, 1.0, evidence)
                bound += 1

        return {
            "annotated": len(rows),
            "topic_bound": bound,
        }

    def run_fulltext_enrich(self, batch_size: int = 100) -> dict:
        """Batch-enrich posts that have short content by fetching their full text."""
        crawler_cfg = CrawlerConfig.from_yaml(self.cfg.crawler_config)
        if not crawler_cfg.enabled:
            return {"skipped": True, "reason": "fulltext disabled in config"}

        rows = self.store.list_posts_needing_fulltext(
            min_chars=crawler_cfg.min_fulltext_chars,
            limit=batch_size,
        )
        enriched = 0
        paywalled = 0
        failed = 0
        for row in rows:
            url = str(row["url"])
            result = fetch_fulltext(url, crawler_cfg)
            if result.paywall_detected:
                self.store.update_post_fulltext(int(row["id"]), result.text, "paywalled", True)
                paywalled += 1
            elif result.ok and result.text:
                self.store.update_post_fulltext(int(row["id"]), result.text, "fetched_fulltext", False)
                enriched += 1
            else:
                failed += 1

        return {
            "processed": len(rows),
            "enriched": enriched,
            "paywalled": paywalled,
            "failed": failed,
        }

    def run_rankings(self) -> dict:
        out = {}
        for w in self.hot_scorer.windows():
            name = w["name"]
            hours = int(w["hours"])
            self.store.clear_window_rankings(name)
            rows = self.store.list_topics_with_stats(hours)

            n = 0
            for r in rows:
                n_posts = int(r["n_posts"])
                n_blogs = int(r["n_blogs"])
                n_prev = int(r["n_prev"])
                latest_post = str(r["latest_post_at"])
                hot, breakdown, resonance = self.hot_scorer.score_topic(n_posts, n_blogs, n_prev, latest_post)
                cross_hot = self.hot_scorer.is_cross_blogger_hot(name, n_posts, n_blogs)
                self.store.insert_ranking(name, str(r["topic_id"]), hot, breakdown, cross_hot, resonance)
                n += 1
            out[name] = n
        return out

    @staticmethod
    def _to_post_record(feed_id: int, e: RawEntry) -> PostRecord:
        canon_url = canonicalize_url(e.url)
        title_norm = normalize_text(e.title)
        content_hash = stable_hash(title_norm, normalize_text(e.summary), normalize_text(e.content))

        return PostRecord(
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
