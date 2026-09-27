"""Back up /persist to the encrypted personal container on the SSD, and restore it.

Runs at every clean shutdown (deck-backup.service) and from Settings.
    deck-backup now | restore | info
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from . import paths

EXCLUDE = ("lost+found", "swap", "*.sqlite-wal", "*.sqlite-shm", "*.tmp")


def backup_dir() -> Path:
    return paths.personal() / "backup" / "persist"


def _sqlite_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as s, sqlite3.connect(dst) as d:
        s.backup(d)


def backup() -> str:
    if not paths.persist_available():
        return "personal storage is locked; nothing to back up"
    if not paths.personal_available():
        return "SSD personal container not unlocked; backup skipped"
    dest = backup_dir()
    dest.mkdir(parents=True, exist_ok=True)
    cmd = ["rsync", "-a", "--delete", *[f"--exclude={e}" for e in EXCLUDE], f"{paths.persist()}/", f"{dest}/"]
    subprocess.run(cmd, check=True)
    for db in paths.persist().rglob("*.sqlite"):
        _sqlite_copy(db, dest / db.relative_to(paths.persist()))
    (dest.parent / "info.json").write_text(json.dumps({"time": time.time()}))
    return f"backed up to {dest}"


def restore() -> str:
    src = backup_dir()
    if not src.is_dir():
        return "no backup found on the SSD"
    if not paths.persist_available():
        return "personal storage is locked"
    subprocess.run(["rsync", "-a", f"{src}/", f"{paths.persist()}/"], check=True)
    return "restored from SSD backup"


def info() -> dict | None:
    try:
        return json.loads((backup_dir().parent / "info.json").read_text())
    except (OSError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "now"
    if cmd == "now":
        print(backup())
    elif cmd == "restore":
        print(restore())
    elif cmd == "info":
        i = info()
        print(time.strftime("%Y-%m-%d %H:%M", time.localtime(i["time"])) if i else "no backup")
    else:
        print("usage: deck-backup now|restore|info", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
