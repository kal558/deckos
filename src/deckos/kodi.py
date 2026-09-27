"""deck-kodi: start Kodi locked down, optionally straight into Live TV.

    deck-kodi          media library (video, music, photos, recordings)
    deck-kodi --tv     Live TV channel list

Kodi's own settings can't switch off every online feature from a config file,
so after it starts we apply them over its local JSON-RPC port (127.0.0.1:9090):
no add-on updates or repository checks, no web server, no network sharing,
and the tvheadend client enabled.
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time

RPC = ("127.0.0.1", 9090)

LOCKDOWN = {
    "general.addonupdates": 2,          # never
    "general.addonnotifications": False,
    "addons.unknownsources": False,
    "services.webserver": False,
    "services.zeroconf": False,
    "services.upnp": False,
    "services.airplay": False,
    "services.esenabled": True,         # keep local JSON-RPC (loopback only)
    "services.esallinterfaces": False,
    "lookandfeel.enablerssfeeds": False,
    "weather.addon": "",
    "videoplayer.usedisplayasclock": False,
}
DISABLE_ADDONS = ("repository.xbmc.org", "service.xbmc.versioncheck")
ENABLE_ADDONS = ("pvr.hts",)


def rpc(method: str, params: dict | None = None, timeout: float = 3.0) -> dict:
    msg = {"jsonrpc": "2.0", "id": 1, "method": method, **({"params": params} if params else {})}
    with socket.create_connection(RPC, timeout=timeout) as s:
        s.sendall(json.dumps(msg).encode())
        buf = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
            try:
                return json.loads(buf)
            except ValueError:
                continue
    return {}


def wait_for_kodi(seconds: float = 60) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if rpc("JSONRPC.Ping").get("result") == "pong":
                return True
        except OSError:
            pass
        time.sleep(1)
    return False


def lock_down() -> None:
    for key, value in LOCKDOWN.items():
        try:
            rpc("Settings.SetSettingValue", {"setting": key, "value": value})
        except OSError:
            pass
    for addon in DISABLE_ADDONS:
        try:
            rpc("Addons.SetAddonEnabled", {"addonid": addon, "enabled": False})
        except OSError:
            pass
    for addon in ENABLE_ADDONS:
        try:
            rpc("Addons.SetAddonEnabled", {"addonid": addon, "enabled": True})
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="deck-kodi")
    ap.add_argument("--tv", action="store_true")
    args = ap.parse_args(argv)
    proc = subprocess.Popen(["kodi"])
    if wait_for_kodi():
        lock_down()
        if args.tv:
            time.sleep(2)  # let the PVR client connect to tvheadend
            try:
                rpc("GUI.ActivateWindow", {"window": "tvchannels"})
            except OSError:
                pass
    return proc.wait()


if __name__ == "__main__":
    sys.exit(main())
