"""Offline place/address/POI search index (SQLite FTS5) built from OpenStreetMap.

Build (on a PC or, slowly, on the deck):
    deck-mapindex build great-britain-latest.osm.pbf places.sqlite

Features with a `wikipedia=en:Title` tag also power the map's "Wikipedia nearby" layer.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .. import geo

SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS places USING fts5(
    name, kind UNINDEXED, extra, tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS place_geo (
    rowid INTEGER PRIMARY KEY, lat REAL NOT NULL, lon REAL NOT NULL,
    rank INTEGER NOT NULL, wikipedia TEXT
);
CREATE INDEX IF NOT EXISTS place_geo_lat ON place_geo (lat);
CREATE INDEX IF NOT EXISTS place_geo_wiki ON place_geo (wikipedia) WHERE wikipedia IS NOT NULL;
"""

PLACE_RANK = {"city": 100, "town": 85, "village": 65, "suburb": 55, "hamlet": 45,
              "island": 60, "locality": 35, "neighbourhood": 40, "isolated_dwelling": 30}
POI_KEYS = {
    "amenity": {"hospital", "clinic", "doctors", "pharmacy", "drinking_water", "shelter", "police",
                "fire_station", "fuel", "toilets", "water_point", "school", "townhall", "post_office",
                "place_of_worship", "community_centre", "library", "bank", "marketplace"},
    "emergency": {"defibrillator", "phone", "assembly_point"},
    "shop": {"supermarket", "convenience", "hardware", "outdoor", "chemist"},
    "tourism": {"camp_site", "alpine_hut", "wilderness_hut", "hotel", "hostel"},
    "natural": {"spring", "peak", "cave_entrance"},
    "man_made": {"water_well", "water_tap"},
}
RANK_POSTCODE = 70
RANK_ROAD = 25
RANK_POI = 30


@dataclass(frozen=True)
class Feature:
    name: str
    kind: str
    lat: float
    lon: float
    rank: int
    extra: str = ""
    wikipedia: str | None = None


def open_db(path: Path | str, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    else:
        db = sqlite3.connect(str(path))
        db.executescript(SCHEMA)
    db.row_factory = sqlite3.Row
    return db


def build_index(path: Path | str, features: Iterable[Feature]) -> int:
    db = open_db(path)
    n = 0
    with db:
        for f in features:
            cur = db.execute("INSERT INTO places (name, kind, extra) VALUES (?, ?, ?)", (f.name, f.kind, f.extra))
            db.execute("INSERT INTO place_geo (rowid, lat, lon, rank, wikipedia) VALUES (?, ?, ?, ?, ?)",
                       (cur.lastrowid, f.lat, f.lon, f.rank, f.wikipedia))
            n += 1
    db.execute("INSERT INTO places(places) VALUES ('optimize')")
    db.commit()
    db.close()
    return n


def fts_query(text: str) -> str:
    """User text -> FTS5 query: every word must match as a prefix."""
    words = [w.replace('"', "") for w in text.split()]
    return " ".join(f'"{w}"*' for w in words if w)


def search(db: sqlite3.Connection, text: str, limit: int = 20,
           near: tuple[float, float] | None = None) -> list[dict]:
    q = fts_query(text)
    if not q:
        return []
    rows = db.execute(
        "SELECT p.rowid, p.name, p.kind, p.extra, g.lat, g.lon, g.rank, g.wikipedia, bm25(places) AS score"
        " FROM places p JOIN place_geo g ON g.rowid = p.rowid WHERE places MATCH ?"
        " ORDER BY score - g.rank / 20.0 LIMIT ?",
        (q, limit * 5 if near else limit),
    ).fetchall()
    results = [dict(r) for r in rows]
    if near:
        for r in results:
            r["distance_m"] = geo.haversine_m(near[0], near[1], r["lat"], r["lon"])
        # Nearby things first among comparable matches
        results.sort(key=lambda r: r["score"] - r["rank"] / 20.0 + min(r["distance_m"], 500_000) / 100_000)
        results = results[:limit]
    return results


def nearby_wikipedia(db: sqlite3.Connection, lat: float, lon: float, radius_m: float = 10_000,
                     limit: int = 50) -> list[dict]:
    min_lat, min_lon, max_lat, max_lon = geo.bbox_around(lat, lon, radius_m)
    rows = db.execute(
        "SELECT p.name, g.lat, g.lon, g.wikipedia FROM place_geo g JOIN places p ON p.rowid = g.rowid"
        " WHERE g.wikipedia IS NOT NULL AND g.lat BETWEEN ? AND ? AND g.lon BETWEEN ? AND ?",
        (min_lat, max_lat, min_lon, max_lon),
    ).fetchall()
    out = []
    for r in rows:
        d = geo.haversine_m(lat, lon, r["lat"], r["lon"])
        if d <= radius_m:
            out.append({**dict(r), "distance_m": d})
    out.sort(key=lambda r: r["distance_m"])
    return out[:limit]


# ---- OSM extraction ---------------------------------------------------------------

def classify(tags: dict[str, str]) -> tuple[str, int] | None:
    if "place" in tags and tags["place"] in PLACE_RANK:
        return tags["place"], PLACE_RANK[tags["place"]]
    for key, values in POI_KEYS.items():
        v = tags.get(key)
        if v in values:
            return f"{key}={v}", RANK_POI
    if "highway" in tags and tags["highway"] in {"primary", "secondary", "tertiary", "residential",
                                                  "unclassified", "trunk", "living_street", "track"}:
        return "road", RANK_ROAD
    return None


def wiki_title(tags: dict[str, str]) -> str | None:
    w = tags.get("wikipedia", "")
    return w[3:] if w.startswith("en:") else None


def osm_features(pbf: str) -> Iterable[Feature]:  # pragma: no cover - needs pyosmium + data
    import osmium

    postcodes: dict[str, list[float]] = {}
    roads_seen: set[tuple[str, int, int]] = set()
    out: list[Feature] = []

    def emit(tags: dict[str, str], lat: float, lon: float) -> None:
        pc = tags.get("addr:postcode")
        if pc:
            acc = postcodes.setdefault(pc.upper().strip(), [0.0, 0.0, 0])
            acc[0] += lat
            acc[1] += lon
            acc[2] += 1
        name = tags.get("name")
        if not name:
            return
        cls = classify(tags)
        if cls is None:
            if not wiki_title(tags):
                return
            cls = ("landmark", RANK_POI)
        kind, rank = cls
        if kind == "road":
            key = (name, round(lat * 50), round(lon * 50))  # ~2 km dedupe cells
            if key in roads_seen:
                return
            roads_seen.add(key)
        extra = " ".join(filter(None, [tags.get("addr:city"), tags.get("is_in"), tags.get("addr:street")]))
        out.append(Feature(name, kind, lat, lon, rank, extra, wiki_title(tags)))

    class Handler(osmium.SimpleHandler):
        def node(self, n):
            if n.tags:
                emit(dict(n.tags), n.location.lat, n.location.lon)

        def way(self, w):
            if not w.tags:
                return
            try:
                pts = [(nd.location.lat, nd.location.lon) for nd in w.nodes if nd.location.valid()]
            except osmium.InvalidLocationError:
                return
            if pts:
                emit(dict(w.tags), sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

    Handler().apply_file(pbf, locations=True, idx="sparse_file_array,/tmp/deckos-nodes.idx")
    yield from out
    for pc, (slat, slon, n) in postcodes.items():
        yield Feature(pc, "postcode", slat / n, slon / n, RANK_POSTCODE)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="deck-mapindex")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build places.sqlite from an OSM .pbf extract")
    b.add_argument("pbf", nargs="+")
    b.add_argument("out")
    s = sub.add_parser("search")
    s.add_argument("db")
    s.add_argument("query")
    args = ap.parse_args(argv)
    if args.cmd == "build":
        out = Path(args.out)
        tmp = out.with_suffix(".building")
        tmp.unlink(missing_ok=True)
        total = 0
        for pbf in args.pbf:
            total += build_index(tmp, osm_features(pbf))
        tmp.replace(out)
        print(f"{total} places indexed into {out}")
    else:
        for r in search(open_db(args.db, readonly=True), args.query):
            print(f"{r['name']:40s} {r['kind']:22s} {r['lat']:.4f},{r['lon']:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
