"""Position from gpsd (USB GPS), falling back to the mesh node's GPS."""
from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass

from . import paths


@dataclass(frozen=True)
class Fix:
    lat: float
    lon: float
    mode: int  # 2 = 2D, 3 = 3D
    time: str | None
    source: str
    speed: float | None = None
    alt: float | None = None


def parse_tpv(msg: dict) -> Fix | None:
    if msg.get("class") != "TPV" or int(msg.get("mode", 0)) < 2:
        return None
    if "lat" not in msg or "lon" not in msg:
        return None
    return Fix(float(msg["lat"]), float(msg["lon"]), int(msg["mode"]), msg.get("time"), "gps",
               msg.get("speed"), msg.get("altMSL", msg.get("alt")))


def from_gpsd(timeout: float = 2.0, host: str = "127.0.0.1", port: int = 2947) -> Fix | None:
    deadline = time.monotonic() + timeout
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.sendall(b'?WATCH={"enable":true,"json":true};\n')
            buf = b""
            while time.monotonic() < deadline:
                s.settimeout(max(0.1, deadline - time.monotonic()))
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        fix = parse_tpv(json.loads(line))
                    except ValueError:
                        continue
                    if fix:
                        return fix
    except OSError:
        return None
    return None


def from_mesh(max_age_s: float = 900) -> Fix | None:
    p = paths.run() / "mesh-position.json"
    try:
        if time.time() - p.stat().st_mtime > max_age_s:
            return None
        d = json.loads(p.read_text())
        return Fix(float(d["lat"]), float(d["lon"]), 2, None, "mesh")
    except (OSError, ValueError, KeyError):
        return None


def current(timeout: float = 2.0) -> Fix | None:
    return from_gpsd(timeout) or from_mesh()
