from __future__ import annotations

import yaml


class TopicBuilder:
    def __init__(self, cfg_path: str):
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        self.cfg = cfg["topic_building"]

    def assign_topic(self, entities: list[dict], labels: list[dict], post_keywords: set[str]) -> tuple[str | None, dict]:
        min_conf = float(self.cfg["entity_rules"]["min_confidence"])
        for ent in entities:
            if ent.get("confidence", 0.0) >= min_conf:
                topic_id = f"topic.entity.{ent['id']}"
                return topic_id, {"mode": "entity_exact", "entity_id": ent["id"]}

        if not self.cfg.get("fallback", {}).get("create_single_post_topic", False):
            return None, {"mode": "none"}

        fallback_key = "-".join(sorted(post_keywords)[:3])
        if fallback_key:
            return f"topic.keyword.{fallback_key}", {"mode": "keyword_cluster"}
        return None, {"mode": "none"}
