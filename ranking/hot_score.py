from __future__ import annotations

import math
from datetime import datetime, timezone

import yaml


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


class HotScorer:
    def __init__(self, cfg_path: str):
        with open(cfg_path, "r", encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)

    def windows(self) -> list[dict]:
        return self.cfg["windows"]

    def score_topic(self, n_posts: int, n_blogs: int, n_prev: int, latest_post_at: str) -> tuple[float, dict, float]:
        w = self.cfg["hot_score"]["weights"]
        caps = self.cfg["hot_score"]["caps"]
        vel_cfg = self.cfg["hot_score"]["velocity"]
        rec = self.cfg["hot_score"]["recency"]

        d = min(1.0, math.log(1 + n_blogs) / math.log(1 + caps["M_blogs"]))
        q = min(1.0, math.log(1 + n_posts) / math.log(1 + caps["M_posts"]))

        growth_ratio = (n_posts - n_prev) / max(vel_cfg["epsilon"], n_prev)
        v = max(0.0, min(growth_ratio, vel_cfg["max_ratio"])) / vel_cfg["max_ratio"]

        delta_hours = (datetime.now(timezone.utc) - _parse_iso(latest_post_at)).total_seconds() / 3600
        r = math.exp(-delta_hours / rec["tau_hours"])

        hot = w["D_diversity"] * d + w["Q_volume"] * q + w["V_velocity"] * v + w["R_recency"] * r
        resonance = n_blogs / math.sqrt(max(1, n_posts))

        breakdown = {
            "D_diversity": round(d, 4),
            "Q_volume": round(q, 4),
            "V_velocity": round(v, 4),
            "R_recency": round(r, 4),
            "n_posts": n_posts,
            "n_blogs": n_blogs,
            "n_prev": n_prev,
            "latest_post_at": latest_post_at,
        }
        return round(hot, 6), breakdown, round(resonance, 6)

    def is_cross_blogger_hot(self, window: str, n_posts: int, n_blogs: int) -> bool:
        for r in self.cfg["cross_blogger_hot"]["rules"]:
            if r["window"] == window:
                return n_blogs >= r["min_blogs"] and n_posts >= r["min_posts"]
        return False
