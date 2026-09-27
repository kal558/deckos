"""Global search backend: one query across every source, grouped by source.

Each provider is independent and time-limited; a slow or missing source never
blocks the others.
"""
from __future__ import annotations

import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from dataclasses import dataclass, field
from pathlib import Path

from . import manifest, paths

KIWIX = "http://127.0.0.1:8080"
MAPS = "http://127.0.0.1:8090"
PROVIDER_TIMEOUT = 4.0


@dataclass(frozen=True)
class Result:
    title: str
    source: str
    subtitle: str = ""
    command: tuple[str, ...] = field(default_factory=tuple)


def search_apps(q: str, apps: list[manifest.App] | None = None) -> list[Result]:
    ql = q.lower()
    apps = apps if apps is not None else manifest.load_all()
    return [Result(a.name, "Apps", a.description, ("deck-launch", a.id))
            for a in apps if ql in a.name.lower() or ql in a.description.lower()]


def parse_kiwix_rss(xml_text: str) -> list[Result]:
    root = ET.fromstring(xml_text)
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        book = (item.findtext("book/title") or "Library").strip()
        desc = " ".join((item.findtext("description") or "").split())[:140]
        if title and link:
            url = link if link.startswith("http") else KIWIX + link
            out.append(Result(title, book, desc, ("deck-reader", "--url", url)))
    return out


def search_kiwix(q: str) -> list[Result]:
    url = f"{KIWIX}/search?{urllib.parse.urlencode({'pattern': q, 'format': 'xml', 'pageLength': 12})}"
    with urllib.request.urlopen(url, timeout=PROVIDER_TIMEOUT) as r:
        return parse_kiwix_rss(r.read().decode("utf-8", "replace"))


def search_places(q: str) -> list[Result]:
    from .maps import places

    db_path = paths.library() / "places" / "places.sqlite"
    if not db_path.exists():
        return []
    db = places.open_db(db_path, readonly=True)
    try:
        rows = places.search(db, q, limit=8)
    finally:
        db.close()
    return [Result(r["name"], "Places", f"{r['kind']} {r['extra']}".strip(),
                   ("deck-reader", "--url", f"{MAPS}/#{r['lat']:.5f},{r['lon']:.5f},15"))
            for r in rows]


MEDIA_EXT = {".mp4", ".mkv", ".avi", ".webm", ".mp3", ".flac", ".ogg", ".m4a", ".opus", ".jpg", ".png",
             ".ts", ".pdf", ".epub", ".odt", ".ods", ".docx", ".xlsx", ".txt"}
_file_cache: list[Path] | None = None


def _index_files(limit: int = 50_000) -> list[Path]:
    global _file_cache
    if _file_cache is None:
        found: list[Path] = []
        for base in (paths.media(), paths.personal() / "documents", paths.games() / "roms"):
            for dirpath, _dirs, files in os.walk(base):
                for f in files:
                    if Path(f).suffix.lower() in MEDIA_EXT or base.name == "roms":
                        found.append(Path(dirpath) / f)
                if len(found) > limit:
                    break
        _file_cache = found
    return _file_cache


def search_files(q: str) -> list[Result]:
    ql = q.lower()
    hits = [p for p in _index_files() if ql in p.name.lower()][:10]
    return [Result(p.name, "Files", str(p.parent), ("xdg-open", str(p))) for p in hits]


def search_notes(q: str) -> list[Result]:
    ql = q.lower()
    out = []
    notes = paths.persist() / "notes"
    for f in sorted(notes.glob("**/*")) if notes.is_dir() else []:
        if not f.is_file() or f.suffix not in (".txt", ".md"):
            continue
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        if ql in f.name.lower() or ql in text.lower():
            line = next((ln for ln in text.splitlines() if ql in ln.lower()), text[:80])
            out.append(Result(f.stem, "Notes", line.strip()[:120], ("mousepad", str(f))))
    return out[:10]


def search_mesh(q: str) -> list[Result]:
    from .mesh import client

    try:
        rows = client.request({"cmd": "search", "query": q}, timeout=PROVIDER_TIMEOUT)["results"]
    except (OSError, client.MeshdError):
        return []
    return [Result(r["text"][:80], "Mesh", r.get("long_name") or r["from_id"], ("deck-launch", "mesh"))
            for r in rows]


PROVIDERS = {
    "Apps": search_apps,
    "Library": search_kiwix,
    "Places": search_places,
    "Files": search_files,
    "Notes": search_notes,
    "Mesh": search_mesh,
}


def search(q: str, providers: dict | None = None) -> list[Result]:
    q = q.strip()
    if len(q) < 2:
        return []
    providers = providers or PROVIDERS
    results: list[Result] = []
    pool = ThreadPoolExecutor(max_workers=len(providers))
    try:
        futures = [pool.submit(fn, q) for fn in providers.values()]
        deadline = time.monotonic() + PROVIDER_TIMEOUT + 1
        for fut in futures:
            try:
                results.extend(fut.result(timeout=max(0.0, deadline - time.monotonic())))
            except (FutTimeout, Exception):  # noqa: BLE001 - one bad source never breaks search
                continue
    finally:
        # Don't wait for stragglers: their results are simply dropped.
        pool.shutdown(wait=False, cancel_futures=True)
    return results


def grouped(results: list[Result]) -> dict[str, list[Result]]:
    out: dict[str, list[Result]] = {}
    for r in results:
        out.setdefault(r.source, []).append(r)
    return out
