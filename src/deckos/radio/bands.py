"""Band preset files (radio/bands/*.toml) plus the user's saved stations."""
from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .. import paths

MODES = {"wbfm", "am", "nfm", "usb", "lsb", "auto-ssb", "dab", "ft8", "app", "satellite"}
# RTL-SDR Blog V4 tuning range
MIN_HZ = 500e3
MAX_HZ = 1766e6


@dataclass(frozen=True)
class Preset:
    name: str
    freq: float
    channel: str = ""


@dataclass(frozen=True)
class Band:
    name: str
    start: float
    end: float
    step: float


@dataclass(frozen=True)
class Satellite:
    name: str
    norad: int
    freq: float
    pipeline: str


@dataclass
class Tab:
    id: str
    tab: str
    section: str
    mode: str
    note: str = ""
    presets: list[Preset] = field(default_factory=list)
    bands: list[Band] = field(default_factory=list)
    channels: dict[str, float] = field(default_factory=dict)
    satellites: list[Satellite] = field(default_factory=list)
    app: list[str] = field(default_factory=list)
    app_mode: str = "usb"
    dial_offset: float = 0.0


class BandError(ValueError):
    pass


def _check_freq(tab_id: str, f: float) -> float:
    if not MIN_HZ <= f <= MAX_HZ:
        raise BandError(f"{tab_id}: {f:.0f} Hz is outside the SDR's range")
    return float(f)


def parse(text: str, tab_id: str) -> Tab:
    try:
        d = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise BandError(f"{tab_id}: {e}") from e
    mode = d.get("mode", "")
    if mode not in MODES:
        raise BandError(f"{tab_id}: unknown mode {mode!r}")
    t = Tab(id=tab_id, tab=d.get("tab", tab_id), section=d.get("section", "Other"), mode=mode,
            note=d.get("note", ""), app=list(d.get("app", [])), app_mode=d.get("app_mode", "usb"),
            dial_offset=float(d.get("dial_offset", 0.0)))
    for p in d.get("preset", []):
        t.presets.append(Preset(p["name"], _check_freq(tab_id, p["freq"]), p.get("channel", "")))
    bands = list(d.get("band", []))
    if "scan" in d:
        bands.insert(0, {"name": "Scan", **d["scan"]})
    for b in bands:
        start, end = _check_freq(tab_id, b["start"]), _check_freq(tab_id, b["end"])
        if end <= start or b["step"] <= 0:
            raise BandError(f"{tab_id}: bad band {b['name']}")
        t.bands.append(Band(b["name"], start, end, float(b["step"])))
    t.channels = {k: _check_freq(tab_id, v) for k, v in d.get("channels", {}).items()}
    for s in d.get("satellite", []):
        t.satellites.append(Satellite(s["name"], int(s["norad"]), _check_freq(tab_id, s["freq"]), s["pipeline"]))
    if mode == "app" and not t.app:
        raise BandError(f"{tab_id}: app mode needs an app command")
    return t


def bands_dir() -> Path:
    return Path(__file__).with_name("bands")


def load_all(directory: Path | None = None) -> list[Tab]:
    directory = directory or bands_dir()
    tabs = []
    for f in sorted(directory.glob("*.toml")):
        tabs.append(parse(f.read_text(), f.stem))
    for tab in tabs:
        tab.presets.extend(saved_presets(tab.id))
    return tabs


def ssb_sideband(freq: float) -> str:
    """Amateur convention: LSB below 10 MHz, USB above (60 m channels are USB)."""
    if 5.25e6 <= freq <= 5.45e6:
        return "usb"
    return "lsb" if freq < 10e6 else "usb"


# ---- user-saved stations -----------------------------------------------------------

def _saved_file() -> Path:
    return paths.user_state() / "radio-presets.json"


def _read_saved() -> dict[str, list[dict]]:
    try:
        return json.loads(_saved_file().read_text())
    except (OSError, ValueError):
        return {}


def saved_presets(tab_id: str) -> list[Preset]:
    return [Preset(p["name"], float(p["freq"]), p.get("channel", "")) for p in _read_saved().get(tab_id, [])]


def save_preset(tab_id: str, preset: Preset) -> None:
    data = _read_saved()
    lst = [p for p in data.get(tab_id, []) if abs(float(p["freq"]) - preset.freq) > 1 or p.get("channel") != preset.channel]
    lst.append({"name": preset.name, "freq": preset.freq, "channel": preset.channel})
    data[tab_id] = sorted(lst, key=lambda p: p["freq"])
    _saved_file().write_text(json.dumps(data, indent=1))
