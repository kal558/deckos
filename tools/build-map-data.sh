#!/bin/bash
# Build the deck's place-search index and offline routing data on a PC (it can
# be done on the deck too, but takes many hours there).
#
#   tools/build-map-data.sh uk           Britain & Ireland  (~4 GB RAM, ~30-60 min)
#   tools/build-map-data.sh europe-west  much larger        (~16 GB RAM, several hours)
#
# Output in ./map-data/: places.sqlite and routino.tar. Copy both into
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
mkdir -p "$OUT/pbf"

for p in "${PBFS[@]}"; do
  f="$OUT/pbf/$(basename "$p")"
  [[ -f "$f" ]] || curl -fL --retry 3 -o "$f" "https://download.geofabrik.de/$p"
  curl -fsSL "https://download.geofabrik.de/$p.md5" | awk '{print $1"  '"$f"'"}' | md5sum -c -
done

echo ">> Place index"
docker run --rm -v "$ROOT:/src:ro" -v "$OUT:/out" python:3.13-slim bash -c '
  pip install --quiet osmium && cd /src && PYTHONPATH=src python -m deckos.maps.places build /out/pbf/*.pbf /out/places.sqlite'

echo ">> Routing data (Routino, same version as the deck: Debian trixie)"
docker run --rm -v "$OUT:/data" debian:trixie bash -c '
  apt-get update -qq && apt-get install -y -qq routino routino-common >/dev/null &&
  rm -rf /data/routino && mkdir -p /data/routino &&
  planetsplitter --dir=/data/routino --tagging=/usr/share/routino/tagging.xml /data/pbf/*.pbf &&
  tar -C /data/routino -cf /data/routino.tar nodes.mem segments.mem ways.mem relations.mem'

ls -lh "$OUT/places.sqlite" "$OUT/routino.tar"
echo ">> Done. Copy map-data/places.sqlite and map-data/routino.tar to /deck/library/staging/"
