"""Weather-satellite passes and recording (Meteor-M LRPT via SatDump).

    deck-sat passes [--hours 24]    upcoming passes over your position
    deck-sat update-tle             refresh orbit data (needs network)
    deck-sat record NAME            record the next/current pass of a satellite
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .. import gps, paths
from . import bands, sdrlock

TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=weather&FORMAT=tle"
MIN_ELEVATION = 20.0


@dataclass(frozen=True)
class Pass:
    name: str
    rise: float
    culminate: float
    set: float
    max_elevation: float


def tle_file() -> Path:
    return paths.user_state() / "weather.tle"


def update_tle() -> int:
    with urllib.request.urlopen(TLE_URL, timeout=30) as r:
        text = r.read().decode()
    if "METEOR" not in text:
        raise RuntimeError("unexpected TLE response")
    tle_file().write_text(text)
    return text.count("\n") // 3


def parse_tle(text: str) -> dict[int, tuple[str, str, str]]:
    """NORAD id -> (name, line1, line2)."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    out = {}
    for i in range(0, len(lines) - 2, 3):
        name, l1, l2 = lines[i], lines[i + 1], lines[i + 2]
        if l1.startswith("1 ") and l2.startswith("2 "):
            out[int(l1[2:7])] = (name.strip(), l1, l2)
    return out


def observer() -> tuple[float, float] | None:
    fix = gps.current(timeout=2)
    if fix:
        return fix.lat, fix.lon
    try:
        d = json.loads((paths.user_state() / "location.json").read_text())
        return float(d["lat"]), float(d["lon"])
    except (OSError, ValueError, KeyError):
        return None


def satellites() -> list[bands.Satellite]:
    return [s for t in bands.load_all() for s in t.satellites]


def predict(hours: float = 24) -> list[Pass]:
    from skyfield.api import EarthSatellite, load, wgs84

    pos = observer()
    if pos is None:
        raise RuntimeError("no position: get a GPS fix or set your location in Settings")
    try:
        tles = parse_tle(tle_file().read_text())
    except OSError:
        raise RuntimeError("no orbit data yet: go online and run 'deck-sat update-tle'") from None
    ts = load.timescale()
    here = wgs84.latlon(*pos)
    t0 = ts.now()
    t1 = ts.tt_jd(t0.tt + hours / 24)
    passes = []
    for sat in satellites():
        if sat.norad not in tles:
            continue
        name, l1, l2 = tles[sat.norad]
        es = EarthSatellite(l1, l2, name, ts)
        times, events = es.find_events(here, t0, t1, altitude_degrees=10.0)
        cur: dict = {}
        for t, ev in zip(times, events):
            if ev == 0:
                cur = {"rise": t}
            elif ev == 1 and cur:
                alt = (es - here).at(t).altaz()[0].degrees
                cur.update(culminate=t, max_el=alt)
            elif ev == 2 and "culminate" in cur:
                if cur["max_el"] >= MIN_ELEVATION:
                    passes.append(Pass(sat.name, cur["rise"].utc_datetime().timestamp(),
                                       cur["culminate"].utc_datetime().timestamp(),
                                       t.utc_datetime().timestamp(), round(cur["max_el"], 1)))
                cur = {}
    return sorted(passes, key=lambda p: p.rise)


def record(name: str) -> int:
    sat = next((s for s in satellites() if s.name.lower() == name.lower()), None)
    if sat is None:
        print(f"unknown satellite {name}")
        return 2
    upcoming = [p for p in predict(24) if p.name == sat.name and p.set > time.time()]
    if not upcoming:
        print("no good pass in the next 24 h")
        return 1
    p = upcoming[0]
    wait = p.rise - time.time()
    if wait > 0:
        print(f"waiting {wait / 60:.0f} min for {sat.name} (max elevation {p.max_elevation}°)")
        time.sleep(wait)
    out = paths.media() / "satellite" / time.strftime("%Y-%m-%d_%H%M", time.gmtime(p.rise))
    out.mkdir(parents=True, exist_ok=True)
    duration = int(p.set - time.time()) + 30
    try:
        with sdrlock.hold(f"Satellite {sat.name}"):
            return subprocess.call(["satdump", "live", sat.pipeline, str(out), "--source", "rtlsdr",
                                    "--samplerate", "1.024e6", "--frequency", f"{sat.freq:.0f}",
                                    "--timeout", str(duration)])
    except sdrlock.Busy as e:
        print(e)
        return 75


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="deck-sat")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("passes")
    p.add_argument("--hours", type=float, default=24)
    p.add_argument("--json", action="store_true")
    sub.add_parser("update-tle")
    r = sub.add_parser("record")
    r.add_argument("name")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "update-tle":
            print(f"updated orbit data ({update_tle()} satellites)")
        elif args.cmd == "passes":
            ps = predict(args.hours)
            if args.json:
                print(json.dumps([p.__dict__ for p in ps]))
            else:
                for x in ps:
                    t = time.strftime("%a %H:%M", time.localtime(x.rise))
                    print(f"{t}  {x.name:14s} max {x.max_elevation:4.1f}°  {int((x.set - x.rise) / 60)} min")
        elif args.cmd == "record":
            return record(args.name)
    except (RuntimeError, OSError) as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
