"""Build the demodulator/playback command lines for each mode (pure, tested)."""
from __future__ import annotations

from dataclasses import dataclass

from . import bands


@dataclass(frozen=True)
class Pipeline:
    source: list[str]      # writes raw S16LE mono audio to stdout
    rate: int              # sample rate of that audio

    def player(self) -> list[str]:
        return ["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-c", "1", "-r", str(self.rate), "-"]

    def to_sink(self, sink: str) -> list[str]:
        return ["pacat", f"--device={sink}", "--raw", "--format=s16le", "--channels=1", f"--rate={self.rate}"]


def rtl_fm(mode: str, freq: float, gain: float | None = None, squelch: int | None = None,
           ppm: int = 0) -> Pipeline:
    """rtl_fm pipeline for an analogue mode. The V4 handles HF via its built-in upconverter."""
    if mode == "auto-ssb":
        mode = bands.ssb_sideband(freq)
    args: list[str] = ["rtl_fm", "-f", str(int(freq))]
    if mode == "wbfm":
        args += ["-M", "wbfm", "-s", "200000", "-r", "48000"]
        rate = 48000
    elif mode == "am":
        args += ["-M", "am", "-s", "16000"]
        rate = 16000
    elif mode == "nfm":
        args += ["-M", "fm", "-s", "16000"]
        rate = 16000
    elif mode in ("usb", "lsb", "ft8"):
        args += ["-M", "lsb" if mode == "lsb" else "usb", "-s", "12000"]
        rate = 12000
    else:
        raise ValueError(f"no rtl_fm pipeline for mode {mode!r}")
    if gain is not None:
        args += ["-g", f"{gain:g}"]
    if squelch:
        args += ["-l", str(squelch)]
    if ppm:
        args += ["-p", str(ppm)]
    args.append("-")
    return Pipeline(args, rate)


def welle_server(channel: str, port: int = 7979) -> list[str]:
    """welle-cli in web-server mode: /mux.json lists services, /mp3/<SID> streams one."""
    return ["welle-cli", "-c", channel, "-w", str(port)]
