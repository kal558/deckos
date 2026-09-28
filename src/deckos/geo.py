"""Small geodesy helpers."""
from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def bbox_around(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    """(min_lat, min_lon, max_lat, max_lon) enclosing a circle."""
    dlat = math.degrees(radius_m / EARTH_RADIUS_M)
    dlon = math.degrees(radius_m / (EARTH_RADIUS_M * max(0.01, math.cos(math.radians(lat)))))
    return lat - dlat, lon - dlon, lat + dlat, lon + dlon


def maidenhead_to_latlon(grid: str) -> tuple[float, float]:
    """Centre of a Maidenhead locator (4 or 6 characters), as used by FT8/JS8."""
    g = grid.strip()
    if len(g) not in (4, 6):
        raise ValueError(f"bad locator: {grid!r}")
    g = g[:2].upper() + g[2:4] + g[4:].lower()
    if not ("A" <= g[0] <= "R" and "A" <= g[1] <= "R" and g[2:4].isdigit()):
        raise ValueError(f"bad locator: {grid!r}")
    lon = (ord(g[0]) - 65) * 20 - 180 + int(g[2]) * 2
    lat = (ord(g[1]) - 65) * 10 - 90 + int(g[3])
    if len(g) == 6:
        if not ("a" <= g[4] <= "x" and "a" <= g[5] <= "x"):
            raise ValueError(f"bad locator: {grid!r}")
        lon += (ord(g[4]) - 97) * (2 / 24) + (1 / 24)
        lat += (ord(g[5]) - 97) * (1 / 24) + (1 / 48)
    else:
        lon += 1
        lat += 0.5
    return lat, lon


def decode_polyline(encoded: str, precision: int = 6) -> list[tuple[float, float]]:
    """Decode a Google-format encoded polyline into (lat, lon) pairs."""
    coords: list[tuple[float, float]] = []
    index = lat = lon = 0
    factor = 10 ** precision
    while index < len(encoded):
        for which in (0, 1):
            shift = result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if which == 0:
                lat += delta
            else:
                lon += delta
        coords.append((lat / factor, lon / factor))
    return coords
