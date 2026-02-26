"""Full-text article fetcher with Readability parsing, UA rotation, proxy support, and retries."""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import requests
import yaml

try:
    from readability import Document as ReadabilityDocument
    _HAS_READABILITY = True
except ImportError:  # pragma: no cover
    _HAS_READABILITY = False

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_BREAK_RE = re.compile(
    r"</?(p|div|article|section|h[1-6]|li|ul|ol|blockquote|pre|br)[^>]*>",
    re.IGNORECASE,
)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_PAYWALL_RE = re.compile(
    r"(subscribe|paywall|sign.?in|log.?in|create.?account|premium.?content|members?.only)",
    re.IGNORECASE,
)

DEFAULT_USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
]


@dataclass
class CrawlerConfig:
    enabled: bool = True
    min_fulltext_chars: int = 500
    max_retries: int = 3
    retry_base_delay: float = 1.0
    timeout: int = 12
    user_agents: List[str] = field(default_factory=list)
    proxies: List[str] = field(default_factory=list)
    playwright_enabled: bool = False
    per_domain_delay: float = 2.0
    max_concurrent: int = 5

    @classmethod
    def from_yaml(cls, path: str) -> "CrawlerConfig":
        p = Path(path)
        if not p.exists():
            return cls()
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            return cls()
        ft = data.get("fulltext") or {}
        pl = data.get("playwright") or {}
        rl = data.get("rate_limiting") or {}
        return cls(
            enabled=bool(ft.get("enabled", True)),
            min_fulltext_chars=int(ft.get("min_fulltext_chars", 500)),
            max_retries=int(ft.get("max_retries", 3)),
            retry_base_delay=float(ft.get("retry_base_delay", 1.0)),
            timeout=int(ft.get("timeout", 12)),
            user_agents=list(ft.get("user_agents") or []),
            proxies=list(ft.get("proxies") or []),
            playwright_enabled=bool(pl.get("enabled", False)),
            per_domain_delay=float(rl.get("per_domain_delay", 2.0)),
            max_concurrent=int(rl.get("max_concurrent", 5)),
        )


@dataclass
class FetchResult:
    text: str
    method: str  # "readability" | "regex" | "readability_short" | "paywalled" | "failed" | "disabled"
    ok: bool
    paywall_detected: bool = False


def _pick_ua(cfg: CrawlerConfig) -> str:
    uas = cfg.user_agents or DEFAULT_USER_AGENTS
    return random.choice(uas)


def _http_get(url: str, cfg: CrawlerConfig, proxy: str | None = None) -> str:
    headers = {
        "User-Agent": _pick_ua(cfg),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    proxies = {"http": proxy, "https": proxy} if proxy else None
    resp = requests.get(
        url,
        headers=headers,
        proxies=proxies,
        timeout=cfg.timeout,
        allow_redirects=True,
    )
    resp.raise_for_status()
    return resp.text


def _readability_extract(html: str) -> str:
    """Extract main content using readability-lxml (Mozilla Readability port)."""
    if not _HAS_READABILITY:
        return ""
    try:
        doc = ReadabilityDocument(html)
        content = doc.summary(html_partial=True)
        # Insert paragraph breaks before stripping tags
        content = _BLOCK_BREAK_RE.sub("\n\n", content)
        content = _HTML_TAG_RE.sub(" ", content)
        content = re.sub(r"[ \t]+", " ", content)
        content = re.sub(r"\n{3,}", "\n\n", content).strip()
        return content
    except Exception:
        return ""


def _regex_extract(html: str) -> str:
    """Fallback: simple regex-based extraction when readability-lxml is not installed."""
    html = _SCRIPT_STYLE_RE.sub(" ", html)
    m = re.search(r"<article[^>]*>(.*?)</article>", html, re.IGNORECASE | re.DOTALL)
    if not m:
        m = re.search(r"<main[^>]*>(.*?)</main>", html, re.IGNORECASE | re.DOTALL)
    body = m.group(1) if m else html
    body = _BLOCK_BREAK_RE.sub("\n\n", body)
    body = _HTML_TAG_RE.sub(" ", body)
    body = re.sub(r"\s+", " ", body).strip()
    return body


def _detect_paywall(html: str, text: str) -> bool:
    """Heuristic: short text + paywall-related keywords near the top of the HTML."""
    if len(text) >= 300:
        return False
    return bool(_PAYWALL_RE.search(html[:8000]))


def fetch_fulltext(url: str, cfg: CrawlerConfig) -> FetchResult:
    """
    Multi-layer full-text extraction:
      1. readability-lxml (semantic extraction)
      2. regex fallback (simple tag stripping)
    With UA rotation, proxy support, and exponential-backoff retry.
    """
    if not url or not cfg.enabled:
        return FetchResult(text="", method="disabled", ok=False)

    proxy_pool: list[str | None] = list(cfg.proxies) if cfg.proxies else [None]

    for attempt in range(max(1, cfg.max_retries)):
        proxy = random.choice(proxy_pool)
        try:
            html = _http_get(url, cfg, proxy=proxy)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status in (403, 401, 429):
                time.sleep((2 ** attempt) * cfg.retry_base_delay)
                # If using proxies, rotate to another proxy next iteration
                continue
            # Other HTTP errors (404, 500, etc.) — no point retrying
            break
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            time.sleep(2 ** attempt)
            continue
        except Exception:
            break

        # Try Readability first, then regex fallback
        text = _readability_extract(html) if _HAS_READABILITY else ""
        method = "readability"
        if not text:
            text = _regex_extract(html)
            method = "regex"

        # Paywall check
        if _detect_paywall(html, text):
            return FetchResult(text=text, method="paywalled", ok=False, paywall_detected=True)

        if len(text) >= cfg.min_fulltext_chars:
            return FetchResult(text=text, method=method, ok=True)

        # Content too short but fetched successfully — return as-is (better than nothing)
        if text:
            return FetchResult(text=text, method=f"{method}_short", ok=True)

        # Empty content — no retry benefit
        break

    return FetchResult(text="", method="failed", ok=False)
