"""Feed SDR audio into a virtual PipeWire source for decoder apps (JS8Call, fldigi).

    deck-sdr-pipe --freq 7078000 --mode usb [--then js8call]

Creates a null sink "deck_sdr", makes its monitor the default input, streams
rtl_fm into it and (optionally) runs an app until it exits. Holds the SDR lock.
"""
from __future__ import annotations

import argparse
import subprocess
import sys

from . import pipelines, sdrlock

SINK = "deck_sdr"


def _pactl(*args: str) -> str:
    return subprocess.run(["pactl", *args], capture_output=True, text=True).stdout.strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="deck-sdr-pipe")
    ap.add_argument("--freq", type=float, required=True)
    ap.add_argument("--mode", default="usb")
    ap.add_argument("--gain", type=float)
    ap.add_argument("--name", default="Decoder")
    ap.add_argument("--then", nargs=argparse.REMAINDER, help="app to run while audio flows")
    args = ap.parse_args(argv)

    pipe = pipelines.rtl_fm(args.mode, args.freq, args.gain)
    try:
        with sdrlock.hold(args.name):
            module_id = _pactl("load-module", "module-null-sink", f"sink_name={SINK}",
                               "sink_properties=device.description=SDR-Audio")
            previous_source = _pactl("get-default-source")
            _pactl("set-default-source", f"{SINK}.monitor")
            src = subprocess.Popen(pipe.source, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            sink = subprocess.Popen(pipe.to_sink(SINK), stdin=src.stdout)
            src.stdout.close()
            try:
                if args.then:
                    return subprocess.call(args.then)
                return sink.wait()
            finally:
                for p in (src, sink):
                    p.terminate()
                if previous_source:
                    _pactl("set-default-source", previous_source)
                if module_id:
                    _pactl("unload-module", module_id)
    except sdrlock.Busy as e:
        subprocess.run(["notify-send", "-a", "deckOS", str(e)], stderr=subprocess.DEVNULL)
        return 75


if __name__ == "__main__":
    sys.exit(main())
