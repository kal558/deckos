"""What's installed under /deck/library, and keeping the kiwix catalogue in sync."""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .. import paths
from .catalog import Item

ZIM_RE = re.compile(r"^(?P<name>.+)_(?P<date>\d{4}-\d{2})\.zim$")


@dataclass(frozen=True)
class Installed:
    path: Path
    name: str       # zim book name, or catalogue id for maps
    date: str       # YYYY-MM, or "" if unknown
    size_bytes: int
    mtime: float

    def age_months(self, now: float | None = None) -> int | None:
        if not self.date:
            return None
        y, m = map(int, self.date.split("-"))
        t = time.gmtime(now or time.time())
        return (t.tm_year - y) * 12 + (t.tm_mon - m)


def parse_zim_filename(fname: str) -> tuple[str, str] | None:
    m = ZIM_RE.match(fname)
    return (m["name"], m["date"]) if m else None


def zim_dir() -> Path:
    return paths.library() / "zim"


def maps_dir() -> Path:
    return paths.library() / "maps"


def installed_zims(directory: Path | None = None) -> dict[str, Installed]:
    """Newest file per book name."""
    directory = directory or zim_dir()
    out: dict[str, Installed] = {}
    for f in directory.glob("*.zim") if directory.is_dir() else []:
        parsed = parse_zim_filename(f.name)
        name, date = parsed if parsed else (f.stem, "")
        st = f.stat()
        inst = Installed(f, name, date, st.st_size, st.st_mtime)
        if name not in out or date > out[name].date:
            out[name] = inst
    return out


def superseded_zims(directory: Path | None = None) -> list[Path]:
    """Older dated copies of books that have a newer file."""
    directory = directory or zim_dir()
    newest = installed_zims(directory)
    old = []
    for f in directory.glob("*.zim") if directory.is_dir() else []:
        parsed = parse_zim_filename(f.name)
        if parsed and parsed[0] in newest and newest[parsed[0]].path != f:
            old.append(f)
    return old


def installed_item(item: Item) -> Installed | None:
    if item.kind == "zim":
        return installed_zims().get(item.name)
    if item.kind == "pmtiles":
        f = maps_dir() / f"{item.id}.pmtiles"
    else:
        f = paths.library() / item.file
    if not f.exists():
        return None
    st = f.stat()
    return Installed(f, item.id, time.strftime("%Y-%m", time.gmtime(st.st_mtime)), st.st_size, st.st_mtime)


def disk_usage() -> tuple[int, int]:
    """(used, free) bytes on the SSD, or (0, 0) if it isn't mounted."""
    if not paths.ssd_available():
        return 0, 0
    u = shutil.disk_usage(paths.deck())
    return u.used, u.free


def library_xml() -> Path:
    return paths.library() / "library.xml"


def rebuild_kiwix_library() -> int:
    """Regenerate library.xml from the ZIMs present; kiwix-serve picks it up (--monitorLibrary)."""
    xml = library_xml()
    tmp = xml.with_suffix(".xml.new")
    tmp.unlink(missing_ok=True)
    zims = sorted(i.path for i in installed_zims().values())
    for z in zims:
        subprocess.run(["kiwix-manage", str(tmp), "add", str(z)], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not tmp.exists():
        tmp.write_text('<?xml version="1.0" encoding="UTF-8" ?>\n<library version="20110515"></library>\n')
    tmp.replace(xml)
    return len(zims)
