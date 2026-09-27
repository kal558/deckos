"""Resolve Kiwix book names to download URLs via the OPDS v2 catalogue."""
from __future__ import annotations

import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass

CATALOG = "https://library.kiwix.org/catalog/v2/entries"
NS = {"a": "http://www.w3.org/2005/Atom"}
ACQ = "http://opds-spec.org/acquisition/open-access"


@dataclass(frozen=True)
class Book:
    name: str
    title: str
    updated: str
    meta4_url: str
    size_bytes: int

    @property
    def zim_url(self) -> str:
        return self.meta4_url.removesuffix(".meta4")

    @property
    def filename(self) -> str:
        return self.zim_url.rsplit("/", 1)[-1]


def query_url(name: str) -> str:
    return f"{CATALOG}?{urllib.parse.urlencode({'name': name, 'count': 5})}"


def parse_feed(xml_text: str, name: str) -> Book | None:
    """Newest entry whose name matches exactly."""
    root = ET.fromstring(xml_text)
    best: Book | None = None
    for entry in root.findall("a:entry", NS):
        ename = (entry.findtext("a:name", default="", namespaces=NS) or "").strip()
        if ename and ename != name:
            continue
        link = next((lk for lk in entry.findall("a:link", NS) if lk.get("rel") == ACQ), None)
        if link is None or not link.get("href"):
            continue
        href = link.get("href", "")
        if not href.startswith("http"):
            continue
        book = Book(
            name=name,
            title=(entry.findtext("a:title", default=name, namespaces=NS) or name).strip(),
            updated=(entry.findtext("a:updated", default="", namespaces=NS) or "").strip(),
            meta4_url=href if href.endswith(".meta4") else href + ".meta4",
            size_bytes=int(link.get("length") or 0),
        )
        if best is None or book.updated > best.updated:
            best = book
    return best


def resolve(name: str, timeout: float = 30) -> Book | None:
    req = urllib.request.Request(query_url(name), headers={"User-Agent": "deckOS-library"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return parse_feed(r.read().decode("utf-8"), name)
