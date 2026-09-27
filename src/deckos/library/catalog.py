"""The catalogue of fetchable content (catalog.toml)."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

KINDS = ("zim", "pmtiles", "prebuilt")


@dataclass(frozen=True)
class Item:
    id: str
    title: str
    kind: str
    group: str
    size_gb: float
    default: bool = False
    name: str = ""                      # zim book name
    bbox: tuple[float, ...] = field(default_factory=tuple)  # pmtiles: minlon,minlat,maxlon,maxlat
    maxzoom: int = 14
    file: str = ""                      # prebuilt: path under /deck/library
    replaces: str = ""


def parse(text: str) -> list[Item]:
    data = tomllib.loads(text)
    items = []
    seen = set()
    for raw in data.get("item", []):
        kind = raw.get("kind")
        if kind not in KINDS:
            raise ValueError(f"{raw.get('id')}: unknown kind {kind!r}")
        if raw["id"] in seen:
            raise ValueError(f"duplicate id {raw['id']}")
        seen.add(raw["id"])
        if kind == "zim" and not raw.get("name"):
            raise ValueError(f"{raw['id']}: zim items need a name")
        if kind == "pmtiles" and len(raw.get("bbox", [])) != 4:
            raise ValueError(f"{raw['id']}: pmtiles items need a 4-number bbox")
        items.append(Item(
            id=raw["id"], title=raw["title"], kind=kind, group=raw.get("group", "Other"),
            size_gb=float(raw.get("size_gb", 0)), default=bool(raw.get("default", False)),
            name=raw.get("name", ""), bbox=tuple(float(x) for x in raw.get("bbox", ())),
            maxzoom=int(raw.get("maxzoom", 14)), file=raw.get("file", ""), replaces=raw.get("replaces", ""),
        ))
    return items


def load(path: Path | None = None) -> list[Item]:
    if path is None:
        override = Path("/etc/deckos/catalog.toml")
        path = override if override.exists() else Path(__file__).with_name("catalog.toml")
    return parse(path.read_text())


def total_default_gb(items: list[Item]) -> float:
    return sum(i.size_gb for i in items if i.default)
