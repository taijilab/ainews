from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_SPACE = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^\w\s-]+", re.UNICODE)


def normalize_text(text: str) -> str:
    t = text.lower().strip()
    t = _NON_WORD.sub(" ", t)
    t = _SPACE.sub(" ", t)
    return t


def canonicalize_url(url: str) -> str:
    s = urlsplit(url.strip())
    query_items = [(k, v) for k, v in parse_qsl(s.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
    query = urlencode(query_items)
    scheme = "https" if s.scheme in {"http", "https"} else s.scheme
    path = s.path.rstrip("/")
    return urlunsplit((scheme, s.netloc.lower(), path, query, ""))


def stable_hash(*parts: str) -> str:
    payload = "\n".join(parts)
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()
