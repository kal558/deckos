#!/bin/bash
# Build the deck's place-search index and offline routing tiles on a PC (the
# deck's 2 GB of RAM isn't enough for Valhalla on a country-sized extract).
#
#   tools/build-map-data.sh uk           Britain & Ireland  (~8 GB RAM, ~1-2 h)
#   tools/build-map-data.sh europe-west  much larger        (~32 GB RAM, many hours)
#
# Output in ./map-data/: places.sqlite and valhalla_tiles.tar. Copy both into
# /deck/library/staging/ on the SSD (or over the PC import share), then press
# "Import from staging folder" in the Library app.
# Needs Docker. Data: OpenStreetMap via Geofabrik (ODbL).
set -euo pipefail

REGION="${1:-uk}"
case "$REGION" in
  uk) PBFS=("europe/britain-and-ireland-latest.osm.pbf") ;;
  europe-west) PBFS=("europe/britain-and-ireland-latest.osm.pbf" "europe/france-latest.osm.pbf"
                     "europe/belgium-latest.osm.pbf" "europe/netherlands-latest.osm.pbf"
                     "europe/luxembourg-latest.osm.pbf" "europe/germany-latest.osm.pbf" "europe/spain-latest.osm.pbf"
                     "europe/portugal-latest.osm.pbf" "europe/switzerland-latest.osm.pbf" "europe/austria-latest.osm.pbf"
                     "europe/italy-latest.osm.pbf" "europe/denmark-latest.osm.pbf") ;;
  *) echo "usage: $0 uk|europe-west" >&2; exit 2 ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/map-data"
mkdir -p "$OUT/pbf" "$OUT/valhalla"

for p in "${PBFS[@]}"; do
  f="$OUT/pbf/$(basename "$p")"
  [[ -f "$f" ]] || curl -fL --retry 3 -o "$f" "https://download.geofabrik.de/$p"
  curl -fsSL "https://download.geofabrik.de/$p.md5" | awk '{print $1"  '"$f"'"}' | md5sum -c -
done

echo ">> Place index"
docker run --rm -v "$ROOT:/src:ro" -v "$OUT:/out" python:3.12-slim bash -c '
  pip install --quiet osmium && cd /src && PYTHONPATH=src python -m deckos.maps.places build /out/pbf/*.pbf /out/places.sqlite'

echo ">> Routing tiles"
docker run --rm -v "$OUT:/data" ghcr.io/valhalla/valhalla:latest bash -c '
  cd /data/valhalla &&
  valhalla_build_config --mjolnir-tile-dir /data/valhalla/tiles --mjolnir-tile-extract /data/valhalla_tiles.tar \
    --mjolnir-admin /data/valhalla/admins.sqlite --mjolnir-timezone /data/valhalla/tz.sqlite > valhalla.json &&
  valhalla_build_timezones > /data/valhalla/tz.sqlite &&
  valhalla_build_admins -c valhalla.json /data/pbf/*.pbf &&
  valhalla_build_tiles -c valhalla.json /data/pbf/*.pbf &&
  valhalla_build_extract -c valhalla.json -v'

ls -lh "$OUT/places.sqlite" "$OUT/valhalla_tiles.tar"
echo ">> Done. Copy map-data/places.sqlite and map-data/valhalla_tiles.tar to /deck/library/staging/"
