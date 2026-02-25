from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import feedparser
import requests
from dateutil import parser as dt_parser


@dataclass
class RawEntry:
    feed_title: str
    feed_url: str
    site_url: str
    blog_id: str
    guid: str
    title: str
    url: str
    author: str
    published_at: str
    summary: str
    content: str


USER_AGENT = "ainews-bot/0.1 (+rss-intel-system)"


def _safe_iso(value: str | None, parsed_struct=None) -> str:
    # 1) feedparser parsed struct is the most reliable if available.
    if parsed_struct:
        try:
            dt = datetime(*parsed_struct[:6], tzinfo=timezone.utc)
            return dt.isoformat()
        except Exception:
            pass

    if value:
        # 2) Try ISO-8601 parser first.
        try:
            dt = dt_parser.isoparse(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            pass
        # 3) Fallback to RFC-like date parser.
        try:
            dt = parsedate_to_datetime(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            pass

    # 4) Last fallback.
    return datetime.now(timezone.utc).isoformat()


def fetch_feed(feed_url: str, timeout: int = 12) -> tuple[dict, list[RawEntry]]:
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(feed_url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)

    feed_title = parsed.feed.get("title", "")
    site_url = parsed.feed.get("link", "")
    blog_id = urlparse(site_url or feed_url).netloc or feed_url

    entries: list[RawEntry] = []
    for e in parsed.entries:
        content = ""
        if e.get("content") and isinstance(e["content"], list):
            content = e["content"][0].get("value", "")
        entry = RawEntry(
            feed_title=feed_title,
            feed_url=feed_url,
            site_url=site_url,
            blog_id=blog_id,
            guid=e.get("id") or e.get("guid") or e.get("link") or "",
            title=e.get("title", "").strip(),
            url=e.get("link", "").strip(),
            author=e.get("author", "").strip(),
            published_at=_safe_iso(
                e.get("published") or e.get("updated"),
                e.get("published_parsed") or e.get("updated_parsed"),
            ),
            summary=(e.get("summary") or "").strip(),
            content=(content or "").strip(),
        )
        if entry.title and entry.url:
            entries.append(entry)

    meta = {
        "feed_title": feed_title,
        "site_url": site_url,
    }
    return meta, entries
