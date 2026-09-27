"""deck-status: live status for the waybar status bar and home-screen tiles.

    deck-status bar <emcon|gps|mesh|ssd|temp|power>   waybar JSON
    deck-status tile <key>                            one line of text
"""
from __future__ import annotations

import json
import shutil
import sys

from . import emcon, hardware, paths


def _bar(text: str, cls: str = "", tooltip: str = "") -> dict:
    return {"text": text, "class": cls, "tooltip": tooltip}


def bar(key: str) -> dict:
    if key == "emcon":
        st = emcon.read_state()
        text, cls = emcon.summarize(st)
        if st.tor:
            text += " · TOR"
        return _bar(text, cls, "Emissions control — ⊞+E to change, ⊞+Shift+E for silent")
    if key == "gps":
        from . import gps

        fix = gps.current(timeout=0.8)
        if not fix:
            return _bar("GPS –", "nofix", "No position fix")
        return _bar(f"GPS {fix.mode}D" if fix.source == "gps" else "GPS mesh", "fix",
                    f"{fix.lat:.5f}, {fix.lon:.5f}")
    if key == "mesh":
        from .mesh import client

        try:
            st = client.request({"cmd": "status"}, timeout=0.8)
        except (OSError, client.MeshdError):
            return _bar("", "absent")
        if not st.get("connected"):
            return _bar("MESH –", "absent", "Mesh radio not connected")
        n = st.get("unread", 0)
        return _bar(f"MESH {n}" if n else "MESH", "unread" if n else "ok", f"{n} unread")
    if key == "ssd":
        if not paths.ssd_available():
            return _bar("SSD –", "absent", "DECKDATA SSD not connected")
        u = shutil.disk_usage(paths.deck())
        return _bar(f"SSD {u.free / 1e9:.0f}G", "ok", f"{u.free / 1e9:.0f} GB free")
    if key == "temp":
        from .power import cpu_temp_mc

        t = (cpu_temp_mc() or 0) / 1000
        return _bar(f"{t:.0f}°C", "hot" if t >= 75 else "ok")
    if key == "power":
        from . import board, power

        st = power.status(board.load())
        parts = [st["profile"].upper()]
        if st["estimate_hours"] is not None:
            parts.append(f"~{st['estimate_hours']:.1f}h")
        cls = "brownout" if st["brownout"] else st["profile"]
        tip = "Estimated from power bank capacity; not measured."
        if st["brownout"]:
            parts.append("LOW V")
            tip = "Undervoltage detected: power bank or cable too weak."
        return _bar(" ".join(parts), cls, tip)
    return _bar("?")


def tile(key: str) -> str:
    present = hardware.detect()
    if key == "library":
        if not present["ssd"]:
            return "SSD not connected"
        from .library import store

        n = len(store.installed_zims())
        used, free = store.disk_usage()
        return f"{n} books · {free / 1e9:.0f} GB free"
    if key == "mesh":
        from .mesh import client

        try:
            st = client.request({"cmd": "status"}, timeout=0.8)
        except (OSError, client.MeshdError):
            return "mesh radio not connected"
        tx = "TX on" if st.get("tx_enabled") else "receive only"
        return f"{st.get('unread', 0)} unread · {tx}" if st.get("connected") else "mesh radio not connected"
    if key == "tv":
        return "tuner ready" if present["dvb"] else "tuner not connected"
    if key == "radio":
        from .radio import sdrlock

        if not present["sdr"]:
            return "SDR not connected"
        owner = sdrlock.owner()
        return f"in use: {owner}" if owner else "ready"
    if key == "emcon":
        return emcon.summarize(emcon.read_state())[0]
    return ""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2 or argv[0] not in ("bar", "tile"):
        print(__doc__, file=sys.stderr)
        return 2
    try:
        if argv[0] == "bar":
            print(json.dumps(bar(argv[1])))
        else:
            print(tile(argv[1]))
    except Exception as e:  # noqa: BLE001 - never break the status bar
        print(json.dumps(_bar("!", "error", str(e))) if argv[0] == "bar" else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
