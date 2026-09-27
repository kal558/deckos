"""Keep the clock sane without internet time servers.

The Zero 3W has no RTC. At shutdown we save the time; at boot we restore the
newest saved time (never going backwards). chrony then disciplines the clock
from GPS via gpsd as soon as there is a fix.

    deck-clock save | restore
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from . import paths


def candidates() -> list[Path]:
    return [paths.persist() / "state/clock", paths.deck() / ".deckos/clock", paths.etc() / "version"]


def newest_saved(files: list[Path]) -> float:
    best = 0.0
    for f in files:
        try:
            if f.name == "version":
                best = max(best, f.stat().st_mtime)  # image build time
            else:
                best = max(best, float(f.read_text().strip()))
        except (OSError, ValueError):
            continue
    return best


def restore_target(now: float, saved: float) -> float | None:
    """Time to set, or None if the current clock is already later."""
    return saved if saved > now else None


def save() -> None:
    now = f"{time.time():.0f}"
    persist_file, ssd_file = candidates()[:2]
    for f, available in ((persist_file, paths.persist_available()), (ssd_file, paths.ssd_available())):
        if not available:
            continue
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(now)
        except OSError:
            pass


def restore() -> None:
    target = restore_target(time.time(), newest_saved(candidates()))
    if target:
        subprocess.run(["date", "-s", f"@{int(target)}"], stdout=subprocess.DEVNULL)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["save"]:
        save()
    elif argv[:1] == ["restore"]:
        restore()
    else:
        print("usage: deck-clock save|restore", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
