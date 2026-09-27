"""Board profile (/etc/deckos/board.conf) and memory detection."""
from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path

from . import paths


def parse_shell_conf(text: str) -> dict[str, str]:
    """Parse simple KEY=VALUE shell assignments (comments and blanks ignored)."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key.isidentifier():
            continue
        try:
            parts = shlex.split(value, comments=True)
        except ValueError:
            continue
        out[key] = parts[0] if parts else ""
    return out


@dataclass
class Board:
    values: dict[str, str] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.values.get("DECK_BOARD_ID", "unknown")

    @property
    def name(self) -> str:
        return self.values.get("DECK_BOARD_NAME", "Unknown board")

    def get(self, key: str, default: str = "") -> str:
        return self.values.get(key, default)

    def get_int(self, key: str, default: int | None = None) -> int | None:
        v = self.values.get(key, "")
        try:
            return int(v)
        except ValueError:
            return default

    def get_float(self, key: str, default: float) -> float:
        try:
            return float(self.values.get(key, ""))
        except ValueError:
            return default


def load(path: Path | None = None) -> Board:
    path = path or paths.etc() / "board.conf"
    try:
        return Board(parse_shell_conf(path.read_text()))
    except OSError:
        return Board()


def mem_total_kib(meminfo: Path | None = None) -> int:
    meminfo = meminfo or paths.root() / "proc/meminfo"
    try:
        for line in meminfo.read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0


# Boards sold as "4 GB" report ~3.7-3.9 GiB after kernel reservations.
LOW_MEMORY_THRESHOLD_KIB = 3_500_000


def is_low_memory(meminfo: Path | None = None) -> bool:
    total = mem_total_kib(meminfo)
    return total == 0 or total < LOW_MEMORY_THRESHOLD_KIB
