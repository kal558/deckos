"""FT8 monitor: decode amateur FT8 beacons and publish spots for the map.

    deck-ft8 --freq 14074000

Audio from rtl_fm (USB, 12 kHz) is cut into 15-second slots aligned to UTC,
written as WAV and decoded by WSJT-X's jt9. Spots with a grid locator go to
/run/deckos/ft8-spots.json (last 2 hours).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

from .. import geo, paths
from . import pipelines, sdrlock

RATE = 12000
SLOT = 15
# jt9 decode line, e.g. "000000 -12  0.3 1234 ~  CQ G4ABC IO91"
DECODE_RE = re.compile(r"^\s*(\d{4,6})\s+(-?\d+)\s+(-?[\d.]+)\s+(\d+)\s+~\s+(.+?)\s*$")
GRID_RE = re.compile(r"^[A-R]{2}\d{2}([a-xA-X]{2})?$")
CALL_RE = re.compile(r"^[A-Z0-9/]*\d[A-Z0-9/]*[A-Z]$")
KEEP_S = 7200


@dataclass(frozen=True)
class Spot:
    call: str
    grid: str
    lat: float
    lon: float
    snr: int
    freq: float
    time: float
    message: str


def parse_decode(line: str, dial_hz: float, now: float) -> Spot | None:
    m = DECODE_RE.match(line)
    if not m:
        return None
    snr, audio_hz, msg = int(m[2]), int(m[4]), m[5]
    tokens = msg.replace("<", "").replace(">", "").split()
    if len(tokens) < 3:
        return None
    grid = tokens[-1]
    if not GRID_RE.match(grid) or grid.upper() == "RR73":
        return None
    call = tokens[-2]
    if not CALL_RE.match(call):
        return None
    try:
        lat, lon = geo.maidenhead_to_latlon(grid)
    except ValueError:
        return None
    return Spot(call, grid, lat, lon, snr, dial_hz + audio_hz, now, msg)


def merge_spots(existing: list[dict], new: list[Spot], now: float) -> list[dict]:
    """Keep the newest spot per callsign within the retention window."""
    by_call = {s["call"]: s for s in existing if now - s.get("time", 0) <= KEEP_S}
    for s in new:
        by_call[s.call] = asdict(s)
    return sorted(by_call.values(), key=lambda s: -s["time"])


def spots_file() -> Path:
    return paths.run() / "ft8-spots.json"


def publish(new: list[Spot]) -> None:
    f = spots_file()
    try:
        existing = json.loads(f.read_text())
    except (OSError, ValueError):
        existing = []
    merged = merge_spots(existing, new, time.time())
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged))
    tmp.replace(f)


def decode_slot(pcm: bytes, dial_hz: float, basedir: Path) -> list[Spot]:
    # Own directory per slot: a slow decode must not collide with the next slot.
    workdir = Path(tempfile.mkdtemp(dir=basedir))
    try:
        return _decode(pcm, dial_hz, workdir)
    finally:
        import shutil

        shutil.rmtree(workdir, ignore_errors=True)


def _decode(pcm: bytes, dial_hz: float, workdir: Path) -> list[Spot]:
    wav = workdir / "slot.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    out = subprocess.run(["jt9", "-8", "-d", "3", "-a", str(workdir), "-t", str(workdir), str(wav)],
                         capture_output=True, text=True, cwd=workdir, timeout=40).stdout
    now = time.time()
    return [s for s in (parse_decode(line, dial_hz, now) for line in out.splitlines()) if s]


def run(dial_hz: float, gain: float | None) -> None:
    pipe = pipelines.rtl_fm("ft8", dial_hz, gain)
    bytes_per_slot = RATE * 2 * SLOT
    with sdrlock.hold("FT8 monitor"), tempfile.TemporaryDirectory(prefix="deck-ft8-") as td:
        proc = subprocess.Popen(pipe.source, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        assert proc.stdout is not None
        # Discard audio until the next slot boundary so slots line up with UTC.
        skip = (SLOT - (time.time() % SLOT)) * RATE * 2
        proc.stdout.read(int(skip) & ~1)
        while True:
            pcm = proc.stdout.read(bytes_per_slot)
            if len(pcm) < bytes_per_slot:
                break
            threading.Thread(target=lambda p=pcm: publish(decode_slot(p, dial_hz, Path(td))), daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="deck-ft8")
    ap.add_argument("--freq", type=float, required=True, help="dial frequency in Hz, e.g. 14074000")
    ap.add_argument("--gain", type=float)
    args = ap.parse_args(argv)
    try:
        run(args.freq, args.gain)
    except sdrlock.Busy as e:
        print(e, file=sys.stderr)
        return 75
    return 0


if __name__ == "__main__":
    sys.exit(main())
