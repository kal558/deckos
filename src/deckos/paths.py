"""Filesystem locations used across deckOS.

Everything is relative to DECKOS_ROOT (default "/") so tests can point the whole
system at a temporary directory.
"""
from __future__ import annotations

import os
from pathlib import Path


def root() -> Path:
    return Path(os.environ.get("DECKOS_ROOT", "/"))


def _p(rel: str) -> Path:
    return root() / rel.lstrip("/")


def etc() -> Path:
    return _p("/etc/deckos")


def apps_dir() -> Path:
    return _p("/usr/share/deckos/apps")


def share() -> Path:
    return _p("/usr/share/deckos")


def run() -> Path:
    """Runtime state shared by system services (tmpfs)."""
    return _p("/run/deckos")


def persist() -> Path:
    """Encrypted personal storage on the SD card/eMMC."""
    return _p("/persist")


def deck() -> Path:
    """Mount point of the DECKDATA SSD."""
    return _p("/deck")


def library() -> Path:
    return deck() / "library"


def media() -> Path:
    return deck() / "media"


def games() -> Path:
    return deck() / "games"


def personal() -> Path:
    """Encrypted container on the SSD."""
    return deck() / "personal"


def is_mounted(path: Path) -> bool:
    """True if path is a mount point (or, under a test root, simply exists)."""
    if root() != Path("/"):
        return path.exists()
    try:
        return os.path.ismount(path)
    except OSError:
        return False


def persist_available() -> bool:
    return is_mounted(persist())


def ssd_available() -> bool:
    return is_mounted(deck())


def personal_available() -> bool:
    return is_mounted(personal())


def user_state() -> Path:
    """Per-user writable state: in /persist when unlocked, else a RAM fallback."""
    if persist_available():
        d = persist() / "state"
    else:
        d = run() / "volatile-state"
    d.mkdir(parents=True, exist_ok=True)
    return d
