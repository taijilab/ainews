from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET


def parse_opml(path: str | Path) -> list[str]:
    root = ET.parse(path).getroot()
    urls: list[str] = []
    for node in root.findall('.//outline[@xmlUrl]'):
        u = (node.attrib.get("xmlUrl") or "").strip()
        if u:
            urls.append(u)
    dedup = sorted(set(urls))
    return dedup
