"""deck-launch <app-id>: start an app from its manifest.

- If the app is already running, focus it instead of starting a second copy.
- If required hardware is missing, say so instead of launching.
- On low-memory boards (<4 GB), heavy apps run one at a time: launching a heavy
  app while another is open asks to close the other first (it gets a normal close
  request, so it can offer to save).

Each launched app gets its own process group; the registry maps app id -> pgid.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import board, hardware, manifest


def registry_path() -> Path:
    base = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    return base / "deckos-apps.json"


# ---- process-group helpers --------------------------------------------------

def _proc_stat(pid: int, proc: Path = Path("/proc")) -> list[str] | None:
    try:
        raw = (proc / str(pid) / "stat").read_text()
    except OSError:
        return None
    # comm (field 2) may contain spaces; split after the closing paren
    rest = raw[raw.rfind(")") + 2 :].split()
    return rest  # rest[0] = state (field 3), rest[2] = pgrp (field 5)


def pgid_alive(pgid: int, proc: Path = Path("/proc")) -> bool:
    for entry in proc.iterdir() if proc.is_dir() else []:
        if not entry.name.isdigit():
            continue
        st = _proc_stat(int(entry.name), proc)
        if st and len(st) > 2 and st[2] == str(pgid) and st[0] != "Z":
            return True
    return False


def load_registry(alive=pgid_alive) -> dict[str, int]:
    try:
        data = json.loads(registry_path().read_text())
    except (OSError, ValueError):
        return {}
    return {k: int(v) for k, v in data.items() if isinstance(v, int) and alive(int(v))}


def save_registry(reg: dict[str, int]) -> None:
    p = registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg))
    tmp.replace(p)


# ---- policy (pure) -------------------------------------------------------------

def must_close(app: manifest.App, running: dict[str, int], heavy_ids: set[str], low_memory: bool) -> list[str]:
    """Which running apps must close before `app` may start."""
    if not app.heavy or not low_memory:
        return []
    return sorted(a for a in running if a in heavy_ids and a != app.id)


# ---- sway ------------------------------------------------------------------------

def _sway_windows() -> list[dict]:
    try:
        out = subprocess.run(["swaymsg", "-t", "get_tree", "-r"], capture_output=True, text=True, timeout=5).stdout
        tree = json.loads(out)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    found: list[dict] = []

    def walk(n: dict) -> None:
        if n.get("pid") and n.get("type") in ("con", "floating_con") and not n.get("nodes"):
            found.append(n)
        for c in n.get("nodes", []) + n.get("floating_nodes", []):
            walk(c)

    walk(tree)
    return found


def _windows_of(pgid: int) -> list[int]:
    ids = []
    for w in _sway_windows():
        st = _proc_stat(int(w["pid"]))
        if st and len(st) > 2 and st[2] == str(pgid):
            ids.append(int(w["id"]))
    return ids


def focus(pgid: int) -> bool:
    wins = _windows_of(pgid)
    if wins:
        subprocess.run(["swaymsg", f"[con_id={wins[0]}] focus"], stdout=subprocess.DEVNULL)
        return True
    return False


def request_close(pgid: int, timeout: float = 30.0) -> bool:
    """Politely close all windows of a process group; True once it has exited."""
    for wid in _windows_of(pgid):
        subprocess.run(["swaymsg", f"[con_id={wid}] kill"], stdout=subprocess.DEVNULL)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pgid_alive(pgid):
            return True
        time.sleep(0.5)
    return False


def notify(msg: str) -> None:
    subprocess.run(["notify-send", "-a", "deckOS", msg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def confirm(question: str) -> bool:
    """Small GTK yes/no dialog; falls back to 'no' if GTK is unavailable."""
    try:
        from .ui.dialogs import ask_yes_no
    except Exception:  # noqa: BLE001 - no display/GTK
        return False
    return ask_yes_no(question)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: deck-launch <app-id>", file=sys.stderr)
        return 2
    apps = {a.id: a for a in manifest.load_all()}
    app = apps.get(argv[0])
    if app is None:
        notify(f"Unknown app: {argv[0]}")
        return 1

    present = hardware.detect()
    miss = hardware.missing(app.requires, present)
    if miss:
        notify(f"{app.name}: {', '.join(hardware.LABELS.get(m, m) for m in miss)} not connected")
        return 1

    reg = load_registry()
    if app.id in reg and focus(reg[app.id]):
        return 0

    heavy_ids = {a.id for a in apps.values() if a.heavy}
    for other in must_close(app, reg, heavy_ids, board.is_low_memory()):
        name = apps[other].name if other in apps else other
        if not confirm(f"{app.name} needs the memory {name} is using.\n\nClose {name}?"):
            return 0
        if not request_close(reg[other]):
            notify(f"{name} is still open (unsaved work?). Close it, then try again.")
            return 1
        reg.pop(other, None)

    proc = subprocess.Popen(list(app.command) + argv[1:], start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    reg[app.id] = proc.pid
    save_registry(reg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
