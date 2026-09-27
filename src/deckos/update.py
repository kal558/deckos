"""Manual system updates (never automatic).

The running root is a RAM overlay over a read-only lower filesystem mounted at
/media/root-ro. Updates remount the lower filesystem writable, run apt inside it
via chroot, then lock it again. A reboot activates the changes.

    deck-update check     # list pending updates (needs network)
    deck-update apply     # apply them
"""
from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

LOWER = Path("/media/root-ro")
BINDS = ("proc", "sys", "dev", "dev/pts", "run")


def overlay_active() -> bool:
    return LOWER.is_dir() and os.path.ismount(LOWER)


@contextmanager
def writable_lower():
    if not overlay_active():
        # Maintenance boot (deckos.rw=1): root is already the real filesystem.
        yield Path("/")
        return
    subprocess.run(["mount", "-o", "remount,rw", str(LOWER)], check=True)
    mounted = []
    try:
        for b in BINDS:
            target = LOWER / b
            subprocess.run(["mount", "--bind", f"/{b}", str(target)], check=True)
            mounted.append(target)
        yield LOWER
    finally:
        for t in reversed(mounted):
            subprocess.run(["umount", "-l", str(t)])
        subprocess.run(["sync"])
        subprocess.run(["mount", "-o", "remount,ro", str(LOWER)])


def _apt(root: Path, *args: str) -> subprocess.CompletedProcess:
    base = ["chroot", str(root)] if root != Path("/") else []
    env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
    return subprocess.run([*base, "apt-get", *args], env=env, text=True, capture_output=True)


def check() -> list[str]:
    with writable_lower() as root:
        r = _apt(root, "update")
        if r.returncode != 0:
            raise RuntimeError("apt update failed (are you online?)\n" + r.stderr[-500:])
        sim = _apt(root, "-s", "full-upgrade")
    return [line.split()[1] for line in sim.stdout.splitlines() if line.startswith("Inst ")]


def apply() -> str:
    with writable_lower() as root:
        _apt(root, "update")
        r = _apt(root, "-y", "-o", "Dpkg::Options::=--force-confold", "full-upgrade")
        if r.returncode != 0:
            raise RuntimeError(r.stderr[-800:])
        _apt(root, "-y", "autoremove", "--purge")
        _apt(root, "clean")
    return "Updates applied. Reboot to use them."


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if os.geteuid() != 0:
        os.execvp("sudo", ["sudo", "-n", "/usr/bin/deck-update", *argv])
    cmd = argv[0] if argv else "check"
    try:
        if cmd == "check":
            pkgs = check()
            print(f"{len(pkgs)} updates available")
            for p in pkgs:
                print(f"  {p}")
        elif cmd == "apply":
            print(apply())
        else:
            print("usage: deck-update check|apply", file=sys.stderr)
            return 2
    except (RuntimeError, subprocess.CalledProcessError) as e:
        print(f"update failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
