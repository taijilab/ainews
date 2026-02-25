from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


@dataclass
class PostRecord:
    feed_id: int
    blog_id: str
    guid: str
    title: str
    url: str
    canonical_url: str
    author: str
    published_at: str
    summary: str
    content: str
    title_norm: str
    content_hash: str


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS feeds (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT,
  feed_url TEXT UNIQUE NOT NULL,
  site_url TEXT,
  status TEXT DEFAULT 'ACTIVE',
  last_fetch_at TEXT,
  error_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  feed_id INTEGER NOT NULL,
  blog_id TEXT NOT NULL,
  guid TEXT,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  canonical_url TEXT NOT NULL,
  author TEXT,
  published_at TEXT NOT NULL,
  summary TEXT,
  content TEXT,
  title_norm TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  UNIQUE(feed_id, guid),
  UNIQUE(canonical_url),
  UNIQUE(title_norm, published_at)
);

CREATE TABLE IF NOT EXISTS post_labels (
  post_id INTEGER NOT NULL,
  label_id TEXT NOT NULL,
  score REAL NOT NULL,
  primary_label INTEGER NOT NULL DEFAULT 0,
  UNIQUE(post_id, label_id)
);

CREATE TABLE IF NOT EXISTS post_entities (
  post_id INTEGER NOT NULL,
  entity_id TEXT NOT NULL,
  canonical_name TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  confidence REAL NOT NULL,
  UNIQUE(post_id, entity_id)
);

CREATE TABLE IF NOT EXISTS topics (
  topic_id TEXT PRIMARY KEY,
  topic_type TEXT NOT NULL,
  title TEXT NOT NULL,
  primary_entity_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topic_posts (
  topic_id TEXT NOT NULL,
  post_id INTEGER NOT NULL,
  score REAL NOT NULL,
  evidence TEXT NOT NULL,
  UNIQUE(topic_id, post_id)
);

CREATE TABLE IF NOT EXISTS hot_rankings (
  window TEXT NOT NULL,
  computed_at TEXT NOT NULL,
  topic_id TEXT NOT NULL,
  hot_score REAL NOT NULL,
  breakdown_json TEXT NOT NULL,
  cross_blogger_hot INTEGER NOT NULL DEFAULT 0,
  resonance REAL NOT NULL,
  UNIQUE(window, computed_at, topic_id)
);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            # Backward-compatible schema extension for source management metadata.
            for sql in (
                "ALTER TABLE feeds ADD COLUMN source_topic TEXT",
                "ALTER TABLE feeds ADD COLUMN source_status TEXT",
            ):
                try:
                    conn.execute(sql)
                except sqlite3.OperationalError:
                    pass

    def feed_count(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM feeds").fetchone()
            return int(row["cnt"]) if row else 0

    def get_feed(self, feed_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM feeds WHERE id=?", (feed_id,)).fetchone()

    def post_count(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM posts").fetchone()
            return int(row["cnt"]) if row else 0

    def list_feeds(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT id, feed_url, title, site_url, error_count
                FROM feeds
                ORDER BY
                  CASE WHEN COALESCE(source_status, '') = 'OK' THEN 0 ELSE 1 END,
                  error_count ASC,
                  id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    def upsert_feed(self, feed_url: str, title: str = "", site_url: str = "") -> int:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO feeds (feed_url, title, site_url)
                VALUES (?, ?, ?)
                ON CONFLICT(feed_url) DO UPDATE SET
                  title=excluded.title,
                  site_url=COALESCE(excluded.site_url, feeds.site_url)
                """,
                (feed_url, title, site_url),
            )
            row = conn.execute("SELECT id FROM feeds WHERE feed_url=?", (feed_url,)).fetchone()
            return int(row["id"])

    def update_feed_meta(self, feed_id: int, source_topic: str | None = None, source_status: str | None = None) -> None:
        with self.connect() as conn:
            if source_topic is not None:
                conn.execute("UPDATE feeds SET source_topic=? WHERE id=?", (source_topic, feed_id))
            if source_status is not None:
                conn.execute("UPDATE feeds SET source_status=? WHERE id=?", (source_status, feed_id))

    def mark_feed_fetch(self, feed_id: int, ok: bool) -> None:
        with self.connect() as conn:
            if ok:
                conn.execute(
                    "UPDATE feeds SET last_fetch_at=?, error_count=0 WHERE id=?",
                    (utc_now_iso(), feed_id),
                )
            else:
                conn.execute(
                    "UPDATE feeds SET error_count=error_count+1, last_fetch_at=? WHERE id=?",
                    (utc_now_iso(), feed_id),
                )

    def insert_posts(self, posts: Iterable[PostRecord]) -> list[int]:
        inserted = []
        with self.connect() as conn:
            for p in posts:
                try:
                    cur = conn.execute(
                        """
                        INSERT INTO posts (
                          feed_id, blog_id, guid, title, url, canonical_url,
                          author, published_at, summary, content, title_norm,
                          content_hash, fetched_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            p.feed_id,
                            p.blog_id,
                            p.guid,
                            p.title,
                            p.url,
                            p.canonical_url,
                            p.author,
                            p.published_at,
                            p.summary,
                            p.content,
                            p.title_norm,
                            p.content_hash,
                            utc_now_iso(),
                        ),
                    )
                    inserted.append(cur.lastrowid)
                except sqlite3.IntegrityError:
                    # Existing post: refresh key metadata so parser fixes can correct old rows.
                    conn.execute(
                        """
                        UPDATE posts
                        SET
                          published_at = ?,
                          author = COALESCE(NULLIF(?, ''), author),
                          summary = COALESCE(NULLIF(?, ''), summary),
                          content = CASE WHEN length(COALESCE(content, '')) >= length(COALESCE(?, ''))
                                         THEN content ELSE ? END
                        WHERE canonical_url = ?
                           OR (feed_id = ? AND guid = ?)
                           OR (title_norm = ? AND published_at = ?)
                        """,
                        (
                            p.published_at,
                            p.author,
                            p.summary,
                            p.content,
                            p.content,
                            p.canonical_url,
                            p.feed_id,
                            p.guid,
                            p.title_norm,
                            p.published_at,
                        ),
                    )
                    continue
        return inserted

    def add_labels(self, post_id: int, labels: list[dict]) -> None:
        with self.connect() as conn:
            for item in labels:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO post_labels (post_id, label_id, score, primary_label)
                    VALUES (?, ?, ?, ?)
                    """,
                    (post_id, item["id"], item["score"], 1 if item.get("primary") else 0),
                )

    def add_entities(self, post_id: int, entities: list[dict]) -> None:
        with self.connect() as conn:
            for e in entities:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO post_entities (
                      post_id, entity_id, canonical_name, entity_type, confidence
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (post_id, e["id"], e["canonical"], e["type"], e["confidence"]),
                )

    def upsert_topic(self, topic_id: str, topic_type: str, title: str, primary_entity_id: str | None) -> None:
        now = utc_now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO topics (topic_id, topic_type, title, primary_entity_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(topic_id) DO UPDATE SET
                  title=excluded.title,
                  updated_at=excluded.updated_at
                """,
                (topic_id, topic_type, title, primary_entity_id, now, now),
            )

    def bind_post_topic(self, topic_id: str, post_id: int, score: float, evidence: dict) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO topic_posts (topic_id, post_id, score, evidence)
                VALUES (?, ?, ?, ?)
                """,
                (topic_id, post_id, score, json.dumps(evidence, ensure_ascii=False)),
            )

    def list_topics_with_stats(self, window_hours: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                WITH current_posts AS (
                  SELECT tp.topic_id, p.id AS post_id, p.blog_id, p.published_at
                  FROM topic_posts tp
                  JOIN posts p ON p.id = tp.post_id
                  WHERE datetime(p.published_at) >= datetime('now', ?)
                ),
                prev_posts AS (
                  SELECT tp.topic_id, COUNT(*) AS cnt
                  FROM topic_posts tp
                  JOIN posts p ON p.id = tp.post_id
                  WHERE datetime(p.published_at) < datetime('now', ?)
                    AND datetime(p.published_at) >= datetime('now', ?)
                  GROUP BY tp.topic_id
                )
                SELECT
                  t.topic_id,
                  t.title,
                  COUNT(cp.post_id) AS n_posts,
                  COUNT(DISTINCT cp.blog_id) AS n_blogs,
                  COALESCE(pp.cnt, 0) AS n_prev,
                  MAX(cp.published_at) AS latest_post_at
                FROM topics t
                JOIN current_posts cp ON cp.topic_id = t.topic_id
                LEFT JOIN prev_posts pp ON pp.topic_id = t.topic_id
                GROUP BY t.topic_id, t.title, pp.cnt
                """,
                (f"-{window_hours} hours", f"-{window_hours} hours", f"-{window_hours * 2} hours"),
            ).fetchall()

    def clear_window_rankings(self, window: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM hot_rankings WHERE window=?", (window,))

    def insert_ranking(self, window: str, topic_id: str, hot_score: float, breakdown: dict, cross_hot: bool, resonance: float) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO hot_rankings (
                  window, computed_at, topic_id, hot_score, breakdown_json, cross_blogger_hot, resonance
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    window,
                    utc_now_iso(),
                    topic_id,
                    hot_score,
                    json.dumps(breakdown, ensure_ascii=False),
                    1 if cross_hot else 0,
                    resonance,
                ),
            )

    def api_topics(self, window: str, sort: str = "hot") -> list[sqlite3.Row]:
        order_by = "hot_score DESC" if sort == "hot" else "resonance DESC"
        with self.connect() as conn:
            return conn.execute(
                f"""
                SELECT hr.window, hr.topic_id, t.title, hr.hot_score,
                       hr.cross_blogger_hot, hr.resonance, hr.breakdown_json
                FROM hot_rankings hr
                JOIN topics t ON t.topic_id = hr.topic_id
                WHERE hr.window = ?
                ORDER BY {order_by}
                LIMIT 200
                """,
                (window,),
            ).fetchall()

    def api_topic_detail(self, topic_id: str) -> dict | None:
        with self.connect() as conn:
            topic = conn.execute("SELECT * FROM topics WHERE topic_id=?", (topic_id,)).fetchone()
            if not topic:
                return None
            posts = conn.execute(
                """
                SELECT p.id, p.title, p.url, p.author, p.published_at, p.summary, p.blog_id
                FROM topic_posts tp
                JOIN posts p ON p.id = tp.post_id
                WHERE tp.topic_id=?
                ORDER BY datetime(p.published_at) DESC
                LIMIT 200
                """,
                (topic_id,),
            ).fetchall()
            return {
                "topic": dict(topic),
                "posts": [dict(x) for x in posts],
            }

    def api_posts(self, label: str | None, after: str | None) -> list[sqlite3.Row]:
        sql = """
        SELECT DISTINCT p.id, p.title, p.url, p.author, p.published_at, p.summary
        FROM posts p
        LEFT JOIN post_labels pl ON pl.post_id = p.id
        WHERE 1=1
        """
        params: list = []
        if label:
            sql += " AND pl.label_id = ?"
            params.append(label)
        if after:
            sql += " AND datetime(p.published_at) >= datetime(?)"
            params.append(after)
        sql += " ORDER BY datetime(p.published_at) DESC LIMIT 200"
        with self.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def api_entities(self, q: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT canonical_name, entity_type, entity_id, COUNT(*) AS mentions
                FROM post_entities
                WHERE lower(canonical_name) LIKE lower(?)
                GROUP BY canonical_name, entity_type, entity_id
                ORDER BY mentions DESC
                LIMIT 50
                """,
                (f"%{q}%",),
            ).fetchall()

    def api_browse_posts(self, kind: str, value: str, limit: int = 300) -> list[sqlite3.Row]:
        with self.connect() as conn:
            if kind == "topic":
                return conn.execute(
                    """
                    SELECT DISTINCT
                      p.id, p.title, p.url, p.author, p.blog_id, p.published_at, p.summary,
                      COALESCE(MAX(CASE WHEN pl.primary_label = 1 THEN pl.label_id END), '') AS primary_label
                    FROM posts p
                    JOIN topic_posts tp ON tp.post_id = p.id
                    JOIN topics t ON t.topic_id = tp.topic_id
                    LEFT JOIN post_labels pl ON pl.post_id = p.id
                    WHERE t.title = ?
                    GROUP BY p.id, p.title, p.url, p.author, p.blog_id, p.published_at, p.summary
                    ORDER BY datetime(p.published_at) DESC
                    LIMIT ?
                    """,
                    (value, limit),
                ).fetchall()
            if kind == "tag":
                return conn.execute(
                    """
                    SELECT DISTINCT
                      p.id, p.title, p.url, p.author, p.blog_id, p.published_at, p.summary,
                      COALESCE(MAX(CASE WHEN pl2.primary_label = 1 THEN pl2.label_id END), '') AS primary_label
                    FROM posts p
                    JOIN post_labels pl ON pl.post_id = p.id
                    LEFT JOIN post_labels pl2 ON pl2.post_id = p.id
                    WHERE pl.label_id = ?
                    GROUP BY p.id, p.title, p.url, p.author, p.blog_id, p.published_at, p.summary
                    ORDER BY datetime(p.published_at) DESC
                    LIMIT ?
                    """,
                    (value, limit),
                ).fetchall()
            return []

    def get_post_detail(self, post_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT
                  p.id, p.title, p.url, p.author, p.blog_id, p.published_at,
                  COALESCE(p.summary, '') AS summary,
                  COALESCE(p.content, '') AS content,
                  COALESCE(MAX(CASE WHEN pl.primary_label = 1 THEN pl.label_id END), '') AS primary_label,
                  COALESCE(GROUP_CONCAT(DISTINCT pl.label_id), '') AS label_tags,
                  COALESCE(GROUP_CONCAT(DISTINCT t.title), '') AS topic_tags
                FROM posts p
                LEFT JOIN post_labels pl ON pl.post_id = p.id
                LEFT JOIN topic_posts tp ON tp.post_id = p.id
                LEFT JOIN topics t ON t.topic_id = tp.topic_id
                WHERE p.id = ?
                GROUP BY p.id, p.title, p.url, p.author, p.blog_id, p.published_at, p.summary, p.content
                """,
                (post_id,),
            ).fetchone()

    def api_available_dates(self, limit: int = 90) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT date(published_at) AS day, COUNT(*) AS post_count
                FROM posts
                GROUP BY date(published_at)
                ORDER BY day DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    def api_daily_digest(self, day: str) -> dict:
        with self.connect() as conn:
            stats_row = conn.execute(
                """
                SELECT
                  COUNT(*) AS post_count,
                  COUNT(DISTINCT blog_id) AS blog_count
                FROM posts
                WHERE date(published_at) = date(?)
                """,
                (day,),
            ).fetchone()

            topics = conn.execute(
                """
                SELECT
                  t.topic_id,
                  t.title,
                  COUNT(*) AS post_count,
                  COUNT(DISTINCT p.blog_id) AS blog_count,
                  MAX(p.published_at) AS latest_post_at
                FROM topic_posts tp
                JOIN topics t ON t.topic_id = tp.topic_id
                JOIN posts p ON p.id = tp.post_id
                WHERE date(p.published_at) = date(?)
                GROUP BY t.topic_id, t.title
                ORDER BY post_count DESC, blog_count DESC, latest_post_at DESC
                LIMIT 50
                """,
                (day,),
            ).fetchall()

            posts = conn.execute(
                """
                SELECT
                  p.id,
                  p.title,
                  p.url,
                  p.author,
                  p.blog_id,
                  p.published_at,
                  p.summary,
                  COALESCE(MAX(CASE WHEN pl.primary_label = 1 THEN pl.label_id END), '') AS primary_label,
                  COALESCE(GROUP_CONCAT(DISTINCT pl.label_id), '') AS label_tags,
                  COALESCE(GROUP_CONCAT(DISTINCT t.title), '') AS topic_tags
                FROM posts p
                LEFT JOIN post_labels pl ON pl.post_id = p.id
                LEFT JOIN topic_posts tp ON tp.post_id = p.id
                LEFT JOIN topics t ON t.topic_id = tp.topic_id
                WHERE date(p.published_at) = date(?)
                GROUP BY p.id, p.title, p.url, p.author, p.blog_id, p.published_at, p.summary
                ORDER BY datetime(p.published_at) DESC
                LIMIT 300
                """,
                (day,),
            ).fetchall()

            labels = conn.execute(
                """
                SELECT pl.label_id, COUNT(*) AS cnt
                FROM post_labels pl
                JOIN posts p ON p.id = pl.post_id
                WHERE date(p.published_at) = date(?)
                GROUP BY pl.label_id
                ORDER BY cnt DESC
                LIMIT 20
                """,
                (day,),
            ).fetchall()

        return {
            "day": day,
            "stats": dict(stats_row) if stats_row else {"post_count": 0, "blog_count": 0},
            "topics": [dict(x) for x in topics],
            "posts": [dict(x) for x in posts],
            "labels": [dict(x) for x in labels],
        }

    def api_sources(self, days: int = 7) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT
                  f.id,
                  COALESCE(NULLIF(f.title, ''), f.feed_url) AS name,
                  f.feed_url,
                  COALESCE(NULLIF(f.site_url, ''), f.feed_url) AS blog_address,
                  COALESCE((
                    SELECT COUNT(*)
                    FROM posts p
                    WHERE p.feed_id = f.id
                      AND datetime(p.published_at) >= datetime('now', ?)
                  ), 0) AS weekly_updates,
                  COALESCE(f.source_topic, (
                    SELECT pl.label_id
                    FROM posts p
                    JOIN post_labels pl ON pl.post_id = p.id
                    WHERE p.feed_id = f.id
                      AND datetime(p.published_at) >= datetime('now', '-30 days')
                    GROUP BY pl.label_id
                    ORDER BY COUNT(*) DESC
                    LIMIT 1
                  ), 'General Tech') AS topic,
                  COALESCE(f.source_status, CASE
                    WHEN f.last_fetch_at IS NULL THEN 'UNKNOWN'
                    WHEN f.error_count = 0 THEN 'OK'
                    ELSE 'ERROR'
                  END) AS network_status,
                  f.error_count,
                  f.last_fetch_at
                FROM feeds f
                ORDER BY weekly_updates DESC, name ASC
                """,
                (f"-{days} days",),
            ).fetchall()

    def delete_feed(self, feed_id: int, purge_posts: bool = True) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM feeds WHERE id=?", (feed_id,)).fetchone()
            if not row:
                return False
            if purge_posts:
                conn.execute("DELETE FROM post_labels WHERE post_id IN (SELECT id FROM posts WHERE feed_id=?)", (feed_id,))
                conn.execute("DELETE FROM post_entities WHERE post_id IN (SELECT id FROM posts WHERE feed_id=?)", (feed_id,))
                conn.execute("DELETE FROM topic_posts WHERE post_id IN (SELECT id FROM posts WHERE feed_id=?)", (feed_id,))
                conn.execute("DELETE FROM posts WHERE feed_id=?", (feed_id,))
            conn.execute("DELETE FROM feeds WHERE id=?", (feed_id,))
            return True
