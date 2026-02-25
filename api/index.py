from __future__ import annotations

try:
    from .app import app
except Exception:
    from app import app  # type: ignore
