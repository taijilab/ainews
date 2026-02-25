from __future__ import annotations

from dataclasses import dataclass

import yaml


@dataclass
class LabelResult:
    label_id: str
    score: float


class RuleClassifier:
    def __init__(self, taxonomy_path: str):
        with open(taxonomy_path, "r", encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)
        self.boost = self.cfg["scoring"]["boost"]
        self.thresholds = self.cfg["scoring"]["thresholds"]
        self.labels = self.cfg["labels"]

    def classify(self, text: str) -> list[dict]:
        t = text.lower()
        scored: list[LabelResult] = []
        for label in self.labels:
            s = 0.0
            for kw in label.get("keywords_strong", []):
                if kw.lower() in t:
                    s += self.boost["strong"]
            for kw in label.get("keywords_medium", []):
                if kw.lower() in t:
                    s += self.boost["medium"]
            for kw in label.get("keywords_weak", []):
                if kw.lower() in t:
                    s += self.boost["weak"]
            if s > 0:
                score = min(1.0, s / 3.0)
                scored.append(LabelResult(label_id=label["id"], score=score))

        if not scored:
            return []

        scored.sort(key=lambda x: x.score, reverse=True)
        primary_min = float(self.thresholds["primary_label_min"])
        secondary_min = float(self.thresholds["secondary_label_min"])

        out: list[dict] = []
        for i, item in enumerate(scored):
            if i == 0 and item.score >= primary_min:
                out.append({"id": item.label_id, "score": item.score, "primary": True})
            elif item.score >= secondary_min:
                out.append({"id": item.label_id, "score": item.score, "primary": False})
        return out
