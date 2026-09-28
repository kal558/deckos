"""Power profiles, thermal watchdog and runtime estimate.

    deck-power status [--json]
    deck-power profile field|normal|performance
    deck-power set-capacity <Wh>      # power bank capacity (from its label)
    deck-power charged                # "I just swapped/charged the power bank"
    deck-power standby                # screen off, CPU minimum; mesh keeps receiving
    deck-power thermald               # run the watchdog (systemd service)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import board as board_mod
from . import paths

PROFILES = ("field", "normal", "performance")
# Services stopped in Field profile (restarted when leaving it).
FIELD_STOP = ("tvheadend.service", "kiwix-serve.service")
DPMS_TIMEOUT = {"field": 60, "normal": 300, "performance": 900}


def _state_path() -> Path:
    # Survives reboots only when personal storage is unlocked; fine either way.
    return paths.user_state() / "power.json"


def load_state() -> dict:
    try:
        return json.loads(_state_path().read_text())
    except (OSError, ValueError):
        return {"profile": "normal", "capacity_wh": None, "charged_at": None, "used_wh": 0.0,
                "last_tick": None}


def save_state(st: dict) -> None:
    p = _state_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st))
    tmp.replace(p)


# ---- pure helpers (tested) -------------------------------------------------------

@dataclass(frozen=True)
class Estimate:
    remaining_wh: float
    hours_left: float
    percent: int


def estimate(capacity_wh: float | None, used_wh: float, draw_w: float, usable_fraction: float = 0.85) -> Estimate | None:
    """Estimate from capacity, energy used since charge, and current profile's draw.

    Power banks deliver ~85% of their label capacity after conversion losses.
    """
    if not capacity_wh or capacity_wh <= 0 or draw_w <= 0:
        return None
    usable = capacity_wh * usable_fraction
    remaining = max(0.0, usable - used_wh)
    return Estimate(remaining, remaining / draw_w, int(round(100 * remaining / usable)))


def accumulate(st: dict, draw_w: float, now: float) -> dict:
    """Add energy used since the last tick (capped so a long power-off isn't counted)."""
    last = st.get("last_tick")
    st = dict(st)
    if last is not None:
        dt = min(max(0.0, now - last), 600.0)
        st["used_wh"] = float(st.get("used_wh", 0.0)) + draw_w * dt / 3600.0
    st["last_tick"] = now
    return st


def thermal_action(temp_mc: int, warn_mc: int, field_mc: int, profile: str) -> str | None:
    if temp_mc >= field_mc and profile != "field":
        return "field"
    if temp_mc >= warn_mc:
        return "warn"
    return None


def draw_for(board: board_mod.Board, profile: str) -> float:
    defaults = {"field": 4.5, "normal": 6.0, "performance": 7.5}
    return board.get_float(f"DRAW_W_{profile.upper()}", defaults[profile])


# ---- hardware -----------------------------------------------------------------------

def cpu_temp_mc() -> int | None:
    temps = []
    for z in (paths.root() / "sys/class/thermal").glob("thermal_zone*"):
        try:
            temps.append(int((z / "temp").read_text().strip()))
        except (OSError, ValueError):
            continue
    return max(temps) if temps else None


def _write(path: Path, value: str) -> None:
    try:
        path.write_text(value)
    except OSError:
        pass


def apply_profile(profile: str, board: board_mod.Board) -> None:
    cap = board.get_int(f"CPUFREQ_{profile.upper()}")
    for pol in (paths.root() / "sys/devices/system/cpu/cpufreq").glob("policy*"):
        try:
            hw_max = (pol / "cpuinfo_max_freq").read_text().strip()
        except OSError:
            continue
        _write(pol / "scaling_governor", "powersave" if profile == "field" else "schedutil")
        _write(pol / "scaling_max_freq", str(cap) if cap else hw_max)
    for svc in FIELD_STOP:
        action = "stop" if profile == "field" else "try-restart"
        subprocess.run(["systemctl", action, svc], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # DPMS timeout is read by the user's swayidle via this file.
    (paths.run()).mkdir(parents=True, exist_ok=True)
    (paths.run() / "dpms-timeout").write_text(str(DPMS_TIMEOUT[profile]))


def set_idle(idle: bool, profile: str, board: board_mod.Board) -> None:
    """Standby: drop CPU to minimum without changing the saved profile."""
    for pol in (paths.root() / "sys/devices/system/cpu/cpufreq").glob("policy*"):
        if idle:
            _write(pol / "scaling_governor", "powersave")
        else:
            _write(pol / "scaling_governor", "powersave" if profile == "field" else "schedutil")


def brownout_detected(board: board_mod.Board) -> bool:
    if board.get("BROWNOUT_METHOD") == "vcgencmd":
        try:
            out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=3).stdout
            m = re.search(r"0x([0-9a-fA-F]+)", out)
            return bool(m and int(m.group(1), 16) & 0x1)  # bit 0: under-voltage now
        except (OSError, subprocess.TimeoutExpired):
            return False
    try:
        out = subprocess.run(["journalctl", "-k", "-b", "--since", "-2min", "-q", "--no-pager"],
                             capture_output=True, text=True, timeout=5).stdout.lower()
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "under-voltage" in out or "undervoltage" in out or "over-current" in out


def notify_all(msg: str, urgency: str = "normal") -> None:
    # notify-send from a system service needs the user's session bus
    import pwd

    try:
        uid = pwd.getpwnam("deck").pw_uid
    except KeyError:
        return
    env = dict(os.environ, DBUS_SESSION_BUS_ADDRESS=f"unix:path=/run/user/{uid}/bus")
    subprocess.run(["runuser", "-u", "deck", "--", "notify-send", "-u", urgency, "-a", "deckOS", msg],
                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def status(board: board_mod.Board) -> dict:
    st = load_state()
    prof = st.get("profile", "normal")
    est = estimate(st.get("capacity_wh"), st.get("used_wh", 0.0), draw_for(board, prof))
    return {
        "profile": prof,
        "temp_c": (cpu_temp_mc() or 0) / 1000,
        "estimate_hours": round(est.hours_left, 1) if est else None,
        "estimate_percent": est.percent if est else None,
        "capacity_wh": st.get("capacity_wh"),
        "brownout": (paths.run() / "brownout").exists(),
    }


def thermald(board: board_mod.Board) -> None:
    warn = board.get_int("THERMAL_WARN", 75000) or 75000
    field = board.get_int("THERMAL_FIELD", 80000) or 80000
    last_warn = 0.0
    st = load_state()
    apply_profile(st.get("profile", "normal"), board)
    while True:
        st = load_state()
        st = accumulate(st, draw_for(board, st.get("profile", "normal")), time.time())
        temp = cpu_temp_mc()
        if temp is not None:
            act = thermal_action(temp, warn, field, st.get("profile", "normal"))
            if act == "field":
                st["profile"] = "field"
                apply_profile("field", board)
                notify_all(f"Deck is hot ({temp / 1000:.0f}°C) — switched to Field profile", "critical")
            elif act == "warn" and time.time() - last_warn > 600:
                last_warn = time.time()
                notify_all(f"Deck is getting hot ({temp / 1000:.0f}°C). Open the case or add ventilation.")
        flag = paths.run() / "brownout"
        if brownout_detected(board):
            if not flag.exists():
                flag.touch()
                notify_all("Power supply too weak (undervoltage). Check the power bank/cable.", "critical")
        else:
            flag.unlink(missing_ok=True)
        save_state(st)
        time.sleep(30)


def _ensure_root(argv: list[str]) -> None:
    if os.geteuid() != 0 and os.environ.get("DECKOS_ROOT") is None:
        os.execvp("sudo", ["sudo", "-n", "/usr/bin/deck-power", *argv])


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="deck-power")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status")
    s.add_argument("--json", action="store_true")
    p = sub.add_parser("profile")
    p.add_argument("name", choices=PROFILES)
    c = sub.add_parser("set-capacity")
    c.add_argument("wh", type=float)
    sub.add_parser("charged")
    sub.add_parser("standby")
    i = sub.add_parser("idle")
    i.add_argument("state", choices=("on", "off"))
    sub.add_parser("thermald")
    args = ap.parse_args(argv)
    board = board_mod.load()

    if args.cmd == "status":
        st = status(board)
        if args.json:
            print(json.dumps(st))
        else:
            for k, v in st.items():
                print(f"{k:18s} {v}")
        return 0
    if args.cmd == "standby":
        # SIGUSR1 makes swayidle go idle now: screen off + CPU minimum (see sway
        # config); any key wakes it. meshd keeps receiving throughout.
        subprocess.run(["pkill", "-USR1", "-x", "swayidle"])
        return 0
    _ensure_root(argv)
    st = load_state()
    if args.cmd == "idle":
        set_idle(args.state == "on", st.get("profile", "normal"), board)
        return 0
    if args.cmd == "profile":
        st["profile"] = args.name
        apply_profile(args.name, board)
    elif args.cmd == "set-capacity":
        st["capacity_wh"] = args.wh
    elif args.cmd == "charged":
        st["used_wh"] = 0.0
        st["charged_at"] = time.time()
    elif args.cmd == "thermald":
        thermald(board)
    save_state(st)
    return 0


if __name__ == "__main__":
    sys.exit(main())
