"""deck-selftest: check the deck's hardware and safety settings on the real device.

    deck-selftest            run everything
    deck-selftest --quick    skip the slow video-decode test
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path

from . import emcon, gps, hardware, paths

PASS, FAIL, SKIP, WARN = "PASS", "FAIL", "SKIP", "WARN"
LOCAL_ADDR = re.compile(r"^(127\.\d+\.\d+\.\d+|\[?::1\]?|\[?::ffff:127\.[\d.]+\]?)(%\w+)?:\d+$")


def sh(*cmd: str, timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)


def non_local_listeners(ss_output: str) -> list[str]:
    """Listening sockets (from `ss -Hltnu`) not bound to loopback."""
    bad = []
    for line in ss_output.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        local = parts[4]
        # DHCP clients bind the wildcard address while a network is up; the firewall
        # only admits their replies. They aren't services.
        if parts[0] == "udp" and local.rsplit(":", 1)[-1] in ("68", "546"):
            continue
        if not LOCAL_ADDR.match(local):
            bad.append(f"{parts[0]} {local}")
    return bad


# ---- checks: each returns (status, detail) ------------------------------------------

def check_readonly_root():
    ok = os.path.ismount("/media/root-ro")
    return (PASS, "root is a RAM overlay; power loss is safe") if ok else (WARN, "root is writable (maintenance or first boot)")


def check_persist():
    return (PASS, "unlocked") if paths.persist_available() else (WARN, "locked or missing: personal data unavailable")


def check_ssd():
    if not paths.ssd_available():
        return FAIL, "DECKDATA SSD not mounted"
    return PASS, "mounted" + (", personal folder unlocked" if paths.personal_available() else ", personal folder locked")


def check_emcon():
    st = emcon.read_state()
    text, _ = emcon.summarize(st)
    return (PASS if not st.transmitting() else WARN), text


def check_firewall():
    r = sh("nft", "list", "chain", "inet", "deckos", "input")
    if r.returncode != 0:
        return FAIL, "deckos firewall table missing"
    return (PASS, "inbound default-deny") if "policy drop" in r.stdout else (FAIL, "input policy is not drop")


def check_listeners():
    r = sh("ss", "-Hltnu")
    bad = non_local_listeners(r.stdout)
    share_on = sh("systemctl", "is-active", "smbd.service").stdout.strip() == "active"
    if bad and not share_on:
        return FAIL, "listening on the network: " + ", ".join(bad)
    return PASS, "nothing listens on the network" if not bad else "only the PC import share (you turned it on)"


def check_zram():
    try:
        swaps = Path("/proc/swaps").read_text()
    except OSError:
        return FAIL, "cannot read /proc/swaps"
    return (PASS, "compressed memory active") if "zram" in swaps else (FAIL, "zram not active")


def check_gpu():
    drivers = set()
    for d in Path("/sys/class/drm").glob("card*/device/driver"):
        drivers.add(Path(os.path.realpath(d)).name)
    good = drivers & {"panfrost", "panthor", "v3d", "vc4-drm", "vc4_drm"}
    return (PASS, ", ".join(sorted(drivers))) if good else (FAIL, f"no open GPU driver ({', '.join(drivers) or 'none'})")


def _decode_test(codec: str, encoder: str) -> tuple[str, str]:
    with tempfile.TemporaryDirectory() as td:
        clip = Path(td) / f"t.{codec}.mkv"
        enc = sh("ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
                 "-t", "2", "-c:v", encoder, "-preset", "ultrafast", str(clip), timeout=300)
        if enc.returncode != 0:
            return SKIP, f"could not create {codec} test clip"
        r = sh("mpv", "--no-config", "--vo=null", "--ao=null", "--hwdec=auto-safe", "--frames=30",
               "--msg-level=vd=v", str(clip), timeout=120)
        out = r.stdout + r.stderr
        if "Using hardware decoding" in out:
            m = re.search(r"Using hardware decoding \((\S+)\)", out)
            return PASS, f"hardware ({m[1] if m else 'yes'})"
        return WARN, "software decoding only"


def check_h264():
    return _decode_test("h264", "libx264")


def check_hevc():
    return _decode_test("hevc", "libx265")


def check_audio():
    r = sh("aplay", "-l")
    return (PASS, "sound card present") if "card" in r.stdout else (FAIL, "no sound card")


def check_sdr():
    if not hardware.detect()["sdr"]:
        return SKIP, "SDR not connected"
    r = sh("rtl_test", "-t", timeout=20)
    out = r.stdout + r.stderr
    return (PASS, "RTL-SDR responds") if "Found 1 device" in out or "Found 2 device" in out else (FAIL, out.strip()[-120:])


def check_dvb():
    fe = list(Path("/dev/dvb").glob("adapter*/frontend0"))
    return (PASS, f"{len(fe)} tuner(s)") if fe else (SKIP, "TV tuner not connected")


def check_mesh():
    if not hardware.detect()["mesh"]:
        return SKIP, "mesh radio not connected"
    from .mesh import client

    try:
        st = client.request({"cmd": "status"}, 3)
    except (OSError, client.MeshdError) as e:
        return FAIL, f"meshd: {e}"
    if not st.get("connected"):
        return FAIL, "meshd can't talk to the node"
    return PASS, f"{st.get('node_name')} · {'TX on' if st.get('tx_enabled') else 'receive only'}"


def check_gps():
    if not hardware.detect()["gps"]:
        return SKIP, "GPS not connected"
    fix = gps.from_gpsd(timeout=5)
    return (PASS, f"{fix.mode}D fix") if fix else (WARN, "no fix yet (needs sky view; first fix can take minutes)")


def _http(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status == 200
    except OSError:
        return False


def check_kiwix():
    if not paths.ssd_available():
        return SKIP, "SSD not connected"
    return (PASS, "serving library") if _http("http://127.0.0.1:8080/catalog/v2/root.xml") else (FAIL, "kiwix-serve not responding")


def check_maps():
    return (PASS, "map server up") if _http("http://127.0.0.1:8090/api/maps") else (FAIL, "deck-mapd not responding")


CHECKS: list[tuple[str, Callable, bool]] = [
    ("Read-only root", check_readonly_root, False),
    ("Personal storage", check_persist, False),
    ("SSD", check_ssd, False),
    ("Emissions (EMCON)", check_emcon, False),
    ("Firewall", check_firewall, False),
    ("Network listeners", check_listeners, False),
    ("Compressed memory", check_zram, False),
    ("GPU driver", check_gpu, False),
    ("Video H.264", check_h264, True),
    ("Video HEVC", check_hevc, True),
    ("Audio", check_audio, False),
    ("SDR radio", check_sdr, False),
    ("TV tuner", check_dvb, False),
    ("Mesh radio", check_mesh, False),
    ("GPS", check_gps, False),
    ("Library server", check_kiwix, False),
    ("Map server", check_maps, False),
]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="deck-selftest")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    results = []
    for name, fn, slow in CHECKS:
        if slow and args.quick:
            results.append((name, SKIP, "skipped (--quick)"))
            continue
        try:
            status, detail = fn()
        except Exception as e:  # noqa: BLE001
            status, detail = FAIL, f"error: {e}"
        results.append((name, status, detail))
        if not args.json:
            print(f"[{status}] {name:20s} {detail}", flush=True)
    if args.json:
        print(json.dumps([{"check": n, "status": s, "detail": d} for n, s, d in results]))
    fails = sum(1 for _, s, _ in results if s == FAIL)
    if not args.json:
        print(f"\n{fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
