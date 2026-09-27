"""Emissions control: what the deck is allowed to transmit.

Transmitters: wifi, bluetooth, mesh. Everything else on the deck is receive-only.
Wi-Fi and Bluetooth are switched off at every boot (soft-off, never disabled) and
can be switched on from Settings or the EMCON panel. The mesh radio defaults to
receive-only; meshd enforces it on the device.

CLI (needs root for radios; re-execs itself through sudo):
    deck-emcon status [--json]
    deck-emcon set wifi|bluetooth|mesh on|off
    deck-emcon silent
    deck-emcon tor on|off
    deck-emcon boot            # applied by deck-emcon-boot.service
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from . import paths

TRANSMITTERS = ("wifi", "bluetooth", "mesh")
LABELS = {"wifi": "WiFi", "bluetooth": "BT", "mesh": "Mesh"}


@dataclass
class State:
    wifi: bool = False
    bluetooth: bool = False
    mesh: bool = False
    tor: bool = False
    mesh_connected: bool = False

    def transmitting(self) -> list[str]:
        return [t for t in TRANSMITTERS if getattr(self, t)]


def summarize(state: State) -> tuple[str, str]:
    """Return (text, css_class) for the status bar."""
    tx = state.transmitting()
    if not tx:
        return "SILENT", "silent"
    return "TX: " + ", ".join(LABELS[t] for t in tx), "transmitting"


# ---- rfkill ---------------------------------------------------------------

def rfkill_state(kind: str, sys_root: Path | None = None) -> bool | None:
    """True if any device of this rfkill type is unblocked (i.e. may transmit).

    kind is the sysfs type: 'wlan' or 'bluetooth'. None if no such device.
    """
    base = (sys_root or paths.root() / "sys") / "class/rfkill"
    seen = False
    on = False
    if not base.is_dir():
        return None
    for dev in base.iterdir():
        try:
            if (dev / "type").read_text().strip() != kind:
                continue
            seen = True
            soft = (dev / "soft").read_text().strip() == "1"
            hard = (dev / "hard").read_text().strip() == "1"
        except OSError:
            continue
        if not soft and not hard:
            on = True
    return on if seen else None


def _mesh_tx_enabled() -> tuple[bool, bool]:
    """(tx_enabled, connected) as reported by meshd; (False, False) if absent."""
    from .mesh import client

    try:
        st = client.request({"cmd": "status"}, timeout=1.0)
    except (OSError, client.MeshdError):
        return False, False
    return bool(st.get("tx_enabled")), bool(st.get("connected"))


def tor_enabled() -> bool:
    return (paths.run() / "tor-mode").exists()


def read_state() -> State:
    mesh_tx, mesh_conn = _mesh_tx_enabled()
    return State(
        wifi=bool(rfkill_state("wlan")),
        bluetooth=bool(rfkill_state("bluetooth")),
        mesh=mesh_tx,
        tor=tor_enabled(),
        mesh_connected=mesh_conn,
    )


# ---- actions (root) -------------------------------------------------------

def _run(cmd: list[str]) -> bool:
    try:
        return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def set_wifi(on: bool) -> None:
    if on:
        _run(["rfkill", "unblock", "wlan"])
        _run(["nmcli", "radio", "wifi", "on"])
    else:
        _run(["nmcli", "radio", "wifi", "off"])
        _run(["rfkill", "block", "wlan"])


def set_bluetooth(on: bool) -> None:
    if on:
        _run(["rfkill", "unblock", "bluetooth"])
        _run(["systemctl", "start", "bluetooth.service"])
        _run(["bluetoothctl", "power", "on"])
        # Never discoverable; pairing is opened explicitly from Settings.
        _run(["bluetoothctl", "discoverable", "off"])
        _run(["bluetoothctl", "pairable", "off"])
    else:
        _run(["bluetoothctl", "power", "off"])
        _run(["systemctl", "stop", "bluetooth.service"])
        _run(["rfkill", "block", "bluetooth"])


def open_bt_pairing(seconds: int = 60) -> None:
    set_bluetooth(True)
    _run(["bluetoothctl", "pairable-timeout", str(seconds)])
    _run(["bluetoothctl", "pairable", "on"])


def set_mesh(on: bool) -> bool:
    from .mesh import client

    try:
        client.request({"cmd": "set_tx", "enabled": on}, timeout=15.0)
        return True
    except (OSError, client.MeshdError):
        return False


TOR_NFT = "/usr/share/deckos/nft/tor-mode.nft"


def set_tor(on: bool) -> None:
    flag = paths.run() / "tor-mode"
    if on:
        _run(["systemctl", "start", "tor.service"])
        if _run(["nft", "-f", TOR_NFT]):
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.touch()
    else:
        _run(["nft", "delete", "table", "inet", "deckos_tor"])
        _run(["systemctl", "stop", "tor.service"])
        flag.unlink(missing_ok=True)


def silent() -> None:
    set_wifi(False)
    set_bluetooth(False)
    set_mesh(False)


def boot() -> None:
    """Boot-time defaults: every transmitter off. Not a block: settings can re-enable."""
    set_wifi(False)
    set_bluetooth(False)
    paths.run().mkdir(parents=True, exist_ok=True)
    (paths.run() / "tor-mode").unlink(missing_ok=True)


SETTERS = {"wifi": set_wifi, "bluetooth": set_bluetooth, "mesh": set_mesh}


def _ensure_root(argv: list[str]) -> None:
    if os.geteuid() != 0 and os.environ.get("DECKOS_ROOT") is None:
        os.execvp("sudo", ["sudo", "-n", "/usr/bin/deck-emcon", *argv])


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="deck-emcon", description="Emissions control")
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status")
    st.add_argument("--json", action="store_true")
    s = sub.add_parser("set")
    s.add_argument("transmitter", choices=TRANSMITTERS)
    s.add_argument("value", choices=("on", "off"))
    sub.add_parser("silent")
    t = sub.add_parser("tor")
    t.add_argument("value", choices=("on", "off"))
    bp = sub.add_parser("bt-pair")
    bp.add_argument("--seconds", type=int, default=60)
    sub.add_parser("boot")
    args = ap.parse_args(argv)

    if args.cmd == "status":
        state = read_state()
        if args.json:
            text, cls = summarize(state)
            print(json.dumps({**asdict(state), "text": text, "class": cls}))
        else:
            text, _ = summarize(state)
            print(text)
            for t in TRANSMITTERS:
                print(f"  {t:10s} {'ON' if getattr(state, t) else 'off'}")
            print(f"  {'tor':10s} {'ON' if state.tor else 'off'}")
        return 0

    _ensure_root(argv)
    if args.cmd == "set":
        SETTERS[args.transmitter](args.value == "on")
    elif args.cmd == "silent":
        silent()
    elif args.cmd == "tor":
        set_tor(args.value == "on")
    elif args.cmd == "bt-pair":
        open_bt_pairing(args.seconds)
    elif args.cmd == "boot":
        boot()
    # Refresh the status bar's TX indicator now rather than at its next poll
    _run(["pkill", "-RTMIN+8", "-x", "waybar"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
