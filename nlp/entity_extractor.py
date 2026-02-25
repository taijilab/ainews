from __future__ import annotations

import yaml


class EntityExtractor:
    def __init__(self, entity_path: str):
        with open(entity_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        self.entities = cfg["entities"]

    def extract(self, text: str) -> list[dict]:
        t = text.lower()
        out: list[dict] = []
        for ent in self.entities:
            matched = False
            for alias in ent.get("aliases", []):
                if alias.lower() in t:
                    matched = True
                    break
            if not matched:
                for kw in ent.get("trigger_keywords", []):
                    if kw.lower() in t:
                        matched = True
                        break
            if matched:
                out.append(
                    {
                        "id": ent["id"],
                        "canonical": ent["canonical"],
                        "type": ent["type"],
                        "confidence": 0.9,
                    }
                )
        return out
