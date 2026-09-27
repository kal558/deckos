"""Only one program may use the RTL-SDR at a time.

    deck-sdr-lock status
    deck-sdr-lock run "SDR++" -- sdrpp
"""
from __future__ import annotations

import fcntl
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from .. import paths


class Busy(RuntimeError):
    def __init__(self, owner: str):
        super().__init__(f"The SDR is in use by {owner}")
        self.owner = owner


def _lock_file() -> Path:
    return paths.run() / "sdr.lock"


def _owner_file() -> Path:
    return paths.run() / "sdr.owner"


def owner() -> str | None:
    """Current holder's name, or None if the SDR is free."""
    lf = _lock_file()
    if not lf.exists():
        return None
    with lf.open("a") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            try:
                return _owner_file().read_text().strip() or "another app"
            except OSError:
                return "another app"
        fcntl.flock(fh, fcntl.LOCK_UN)
    return None


@contextmanager
def hold(name: str):
    lf = _lock_file()
    lf.parent.mkdir(parents=True, exist_ok=True)
    fh = lf.open("a")
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy(owner() or "another app") from None
        _owner_file().write_text(name)
        yield
    finally:
        try:
            if _owner_file().read_text().strip() == name:
                _owner_file().unlink()
        except OSError:
            pass
        fh.close()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["status"]:
        print(owner() or "free")
        return 0
    if len(argv) >= 3 and argv[0] == "run" and "--" in argv:
        name = argv[1]
        cmd = argv[argv.index("--") + 1:]
        try:
            with hold(name):
                return subprocess.call(cmd)
        except Busy as e:
            subprocess.run(["notify-send", "-a", "deckOS", str(e)], stderr=subprocess.DEVNULL)
            print(e, file=sys.stderr)
            return 75  # EX_TEMPFAIL
    print("usage: deck-sdr-lock status | run NAME -- COMMAND...", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
