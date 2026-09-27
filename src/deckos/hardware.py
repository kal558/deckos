"""Detect the deck's plug-in hardware from sysfs/devfs.

Hardware ids used by manifests: ssd, persist, sdr, dvb, mesh, gps.
"""
from __future__ import annotations

from pathlib import Path

from . import paths

# USB vendor:product ids
SDR_IDS = {("0bda", "2838"), ("0bda", "2832")}  # RTL2832U (RTL-SDR Blog V3/V4)
GPS_VENDORS = {"1546"}  # u-blox
GPS_IDS = {("067b", "23a3")}  # Prolific PL2303 used by some GPS pucks
# Meshtastic nodes enumerate as their USB-serial bridge or native USB
MESH_IDS = {
    ("10c4", "ea60"),  # CP210x (Heltec V2, T-Beam)
    ("1a86", "55d4"),  # CH9102 (T-Beam 1.1+, Heltec)
    ("1a86", "7523"),  # CH340
    ("303a", "1001"),  # ESP32-S3 native USB (Heltec V3, Wireless Tracker)
    ("239a", "8029"),  # nRF52 Adafruit bootloader (RAK4631)
    ("239a", "0029"),
}


def usb_devices(sys_root: Path | None = None) -> set[tuple[str, str]]:
    base = (sys_root or paths.root() / "sys") / "bus/usb/devices"
    found: set[tuple[str, str]] = set()
    if not base.is_dir():
        return found
    for dev in base.iterdir():
        try:
            vid = (dev / "idVendor").read_text().strip().lower()
            pid = (dev / "idProduct").read_text().strip().lower()
        except OSError:
            continue
        found.add((vid, pid))
    return found


def detect(sys_root: Path | None = None) -> dict[str, bool]:
    usb = usb_devices(sys_root)
    dev = paths.root() / "dev"
    return {
        "ssd": paths.ssd_available(),
        "persist": paths.persist_available(),
        "sdr": bool(usb & SDR_IDS),
        "dvb": any((dev / "dvb").glob("adapter*")),
        "mesh": bool(usb & MESH_IDS) or (dev / "meshtastic").exists(),
        "gps": any(v in GPS_VENDORS for v, _ in usb) or bool(usb & GPS_IDS) or (dev / "gps0").exists(),
    }


LABELS = {
    "ssd": "SSD",
    "persist": "personal storage",
    "sdr": "SDR dongle",
    "dvb": "TV tuner",
    "mesh": "mesh radio",
    "gps": "GPS",
}


def missing(requires: tuple[str, ...] | list[str], present: dict[str, bool]) -> list[str]:
    return [r for r in requires if not present.get(r, False)]
