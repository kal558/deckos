"""deck-mapd: local-only HTTP server for the offline map app (127.0.0.1:8090).

    /                       static map app (/usr/share/deckos/maps)
    /tiles/<id>.pmtiles     vector tiles with HTTP Range support
    /api/maps               installed map regions
    /api/search?q=&lat=&lon=
    /api/nearby?lat=&lon=&radius=     geotagged Wikipedia articles
    /api/route?from=lat,lon&to=lat,lon&mode=pedestrian|bicycle|auto
    /api/position           GPS fix (gpsd, else mesh node)
    /api/mesh               mesh nodes with positions + waypoints
    /api/waypoint           POST {name, lat, lon, description, share}; DELETE ?id=
    /api/spots              recent FT8 spots (radio module)
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import geo, gps, paths
from ..library import catalog, store
from . import places

HOST, PORT = "127.0.0.1", 8090
VALHALLA = "http://127.0.0.1:8002/route"
KIWIX = "http://127.0.0.1:8080"
MODES = {"pedestrian", "bicycle", "auto"}
RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")


def static_dir() -> Path:
    return paths.share() / "maps"


def places_db_path() -> Path:
    return paths.library() / "places" / "places.sqlite"


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Parse a single-range header into inclusive (start, end); None if absent/invalid."""
    if not header:
        return None
    m = RANGE_RE.match(header.strip())
    if not m or (not m[1] and not m[2]):
        return None
    if m[1]:
        start = int(m[1])
        end = int(m[2]) if m[2] else size - 1
    else:
        start = max(0, size - int(m[2]))
        end = size - 1
    end = min(end, size - 1)
    if start > end or start >= size:
        return None
    return start, end


def wikipedia_book() -> str | None:
    zims = store.installed_zims()
    for name in ("wikipedia_en_all_maxi", "wikipedia_en_all_nopic", "wikipedia_en_all_mini"):
        if name in zims:
            return zims[name].path.stem
    return None


def installed_maps() -> list[dict]:
    items = {i.id: i for i in catalog.load() if i.kind == "pmtiles"}
    out = []
    for f in sorted(store.maps_dir().glob("*.pmtiles")) if store.maps_dir().is_dir() else []:
        it = items.get(f.stem)
        out.append({"id": f.stem, "url": f"/tiles/{f.name}", "title": it.title if it else f.stem,
                    "bbox": list(it.bbox) if it else None, "maxzoom": it.maxzoom if it else None})
    # Most detailed first, so the client can prefer it inside its bbox
    out.sort(key=lambda m: -(m["maxzoom"] or 0))
    return out


def valhalla_route(frm: tuple[float, float], to: tuple[float, float], mode: str) -> dict:
    body = json.dumps({
        "locations": [{"lat": frm[0], "lon": frm[1]}, {"lat": to[0], "lon": to[1]}],
        "costing": mode, "units": "kilometers", "directions_options": {"language": "en-GB"},
    }).encode()
    req = urllib.request.Request(VALHALLA, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    trip = data["trip"]
    coords: list[list[float]] = []
    steps = []
    for leg in trip["legs"]:
        coords += [[lon, lat] for lat, lon in geo.decode_polyline(leg["shape"], 6)]
        steps += [{"text": m.get("instruction", ""), "km": m.get("length", 0)} for m in leg.get("maneuvers", [])]
    return {
        "geometry": {"type": "LineString", "coordinates": coords},
        "km": trip["summary"]["length"], "minutes": round(trip["summary"]["time"] / 60), "steps": steps,
    }


def _latlon(s: str) -> tuple[float, float]:
    a, b = s.split(",")
    return float(a), float(b)


class Handler(BaseHTTPRequestHandler):
    server_version = "deck-mapd"

    def log_message(self, fmt: str, *args) -> None:  # keep the journal quiet
        pass

    # ---- responses
    def _json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, f: Path) -> None:
        if not f.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        size = f.stat().st_size
        rng = parse_range(self.headers.get("Range"), size)
        ctype = "application/octet-stream" if f.suffix in (".pmtiles", ".pbf") else \
            (mimetypes.guess_type(f.name)[0] or "application/octet-stream")
        start, end = rng if rng else (0, size - 1)
        self.send_response(HTTPStatus.PARTIAL_CONTENT if rng else HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with f.open("rb") as fh:
            fh.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = fh.read(min(1 << 16, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _safe_join(self, base: Path, rel: str) -> Path | None:
        target = (base / rel.lstrip("/")).resolve()
        return target if str(target).startswith(str(base.resolve())) else None

    # ---- routing
    def do_GET(self) -> None:
        url = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        try:
            if url.path.startswith("/api/"):
                return self._api_get(url.path[5:], q)
            if url.path.startswith("/tiles/"):
                f = self._safe_join(store.maps_dir(), url.path[len("/tiles/"):])
                return self._file(f) if f else self.send_error(HTTPStatus.FORBIDDEN)
            rel = "index.html" if url.path in ("", "/") else url.path
            f = self._safe_join(static_dir(), rel)
            return self._file(f) if f else self.send_error(HTTPStatus.FORBIDDEN)
        except (BrokenPipeError, ConnectionResetError):
            return None
        except Exception as e:  # noqa: BLE001 - report to the client
            return self._json({"error": str(e)}, 500)

    def _api_get(self, name: str, q: dict) -> None:
        if name == "maps":
            try:
                theme = (paths.user_state() / "theme").read_text().strip() or "night"
            except OSError:
                theme = "night"
            return self._json({"maps": installed_maps(), "wikipedia_book": wikipedia_book(), "kiwix": KIWIX,
                               "theme": theme})
        if name == "search":
            if not places_db_path().exists():
                return self._json({"results": [], "error": "place index not installed"})
            near = (float(q["lat"]), float(q["lon"])) if "lat" in q and "lon" in q else None
            db = places.open_db(places_db_path(), readonly=True)
            try:
                return self._json({"results": places.search(db, q.get("q", ""), 20, near)})
            finally:
                db.close()
        if name == "nearby":
            if not places_db_path().exists():
                return self._json({"results": []})
            db = places.open_db(places_db_path(), readonly=True)
            try:
                res = places.nearby_wikipedia(db, float(q["lat"]), float(q["lon"]), float(q.get("radius", 10000)))
            finally:
                db.close()
            book = wikipedia_book()
            for r in res:
                r["url"] = f"{KIWIX}/content/{book}/{urllib.parse.quote(r['wikipedia'].replace(' ', '_'))}" if book else None
            return self._json({"results": res})
        if name == "route":
            mode = q.get("mode", "pedestrian")
            if mode not in MODES:
                return self._json({"error": "bad mode"}, 400)
            try:
                return self._json(valhalla_route(_latlon(q["from"]), _latlon(q["to"]), mode))
            except OSError:
                return self._json({"error": "routing unavailable (is the routing data installed?)"}, 503)
        if name == "position":
            fix = gps.current(timeout=1.5)
            return self._json({"fix": fix.__dict__ if fix else None})
        if name == "mesh":
            from ..mesh import client

            try:
                nodes = client.request({"cmd": "nodes"}, 3)["nodes"]
                wps = client.request({"cmd": "waypoints"}, 3)["waypoints"]
            except (OSError, client.MeshdError):
                nodes, wps = [], []
            return self._json({"nodes": [n for n in nodes if n.get("lat") is not None], "waypoints": wps})
        if name == "spots":
            f = paths.run() / "ft8-spots.json"
            try:
                spots = json.loads(f.read_text())
            except (OSError, ValueError):
                spots = []
            cutoff = time.time() - 3600
            return self._json({"spots": [s for s in spots if s.get("time", 0) >= cutoff]})
        return self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        if self.path != "/api/waypoint":
            return self._json({"error": "not found"}, 404)
        from ..mesh import client

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(min(length, 65536)) or b"{}")
        try:
            wid = client.request({"cmd": "add_waypoint", "name": str(body["name"])[:30],
                                  "lat": float(body["lat"]), "lon": float(body["lon"]),
                                  "description": str(body.get("description", ""))[:100]})["id"]
            if body.get("share"):
                client.request({"cmd": "share_waypoint", "name": str(body["name"])[:30],
                                "lat": float(body["lat"]), "lon": float(body["lon"])}, 15)
            return self._json({"id": wid})
        except (OSError, client.MeshdError) as e:
            return self._json({"error": str(e)}, 409)

    def do_DELETE(self) -> None:
        from ..mesh import client

        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        if url.path != "/api/waypoint" or "id" not in q:
            return self._json({"error": "not found"}, 404)
        try:
            client.request({"cmd": "delete_waypoint", "id": int(q["id"][0])})
            return self._json({})
        except (OSError, client.MeshdError) as e:
            return self._json({"error": str(e)}, 409)


def main() -> int:
    host = os.environ.get("DECK_MAPD_HOST", HOST)
    srv = ThreadingHTTPServer((host, PORT), Handler)
    srv.daemon_threads = True
    print(f"deck-mapd on http://{host}:{PORT}")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
