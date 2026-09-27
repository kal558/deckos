#!/bin/bash
# maps: vendor the map web libraries, fonts and sprites so the map works offline,
# install the pmtiles CLI (for region downloads) and configure Valhalla routing.
set -euo pipefail
source "$DECK_SRC/lib/common.sh"

MAPLIBRE_VER="5"
PMTILES_JS_VER="4"
BASEMAPS_VER="5"

V=/usr/share/deckos/maps/vendor
mkdir -p "$V"
fetch "https://cdn.jsdelivr.net/npm/maplibre-gl@${MAPLIBRE_VER}/dist/maplibre-gl.js" "$V/maplibre-gl.js"
fetch "https://cdn.jsdelivr.net/npm/maplibre-gl@${MAPLIBRE_VER}/dist/maplibre-gl.css" "$V/maplibre-gl.css"
fetch "https://cdn.jsdelivr.net/npm/pmtiles@${PMTILES_JS_VER}/dist/pmtiles.js" "$V/pmtiles.js"
fetch "https://cdn.jsdelivr.net/npm/@protomaps/basemaps@${BASEMAPS_VER}/dist/basemaps.js" "$V/basemaps.js"

# Glyphs and sprites for the Protomaps styles
tmp=$(mktemp -d)
fetch "https://github.com/protomaps/basemaps-assets/archive/refs/heads/main.zip" "$tmp/assets.zip"
unzip -q "$tmp/assets.zip" -d "$tmp"
cp -r "$tmp"/basemaps-assets-main/fonts "$V/fonts"
cp -r "$tmp"/basemaps-assets-main/sprites "$V/sprites"
rm -rf "$tmp"

# pmtiles CLI (go-pmtiles), latest release for arm64
url=$(curl -fsSL https://api.github.com/repos/protomaps/go-pmtiles/releases/latest \
      | jq -r '.assets[].browser_download_url' | grep -E 'Linux_arm64\.tar\.gz$' | head -n1 || true)
if [[ -n "$url" ]]; then
  tmp=$(mktemp -d)
  if fetch_optional "$url" "$tmp/pmtiles.tgz"; then
    tar -xzf "$tmp/pmtiles.tgz" -C "$tmp"
    install -m 0755 "$tmp/pmtiles" /usr/local/bin/pmtiles
  fi
  rm -rf "$tmp"
else
  warn "could not find a go-pmtiles arm64 release; map region downloads unavailable"
fi

# Valhalla config pointing at the routing tiles on the SSD, listening on localhost only
mkdir -p /etc/valhalla
if command -v valhalla_build_config >/dev/null; then
  valhalla_build_config \
    --mjolnir-tile-dir /deck/library/valhalla/tiles \
    --mjolnir-tile-extract /deck/library/valhalla/valhalla_tiles.tar \
    --httpd-service-listen tcp://127.0.0.1:8002 \
    --httpd-service-loopback ipc:///run/valhalla/loopback \
    --httpd-service-interrupt ipc:///run/valhalla/interrupt \
    > /etc/valhalla/valhalla.json
else
  warn "valhalla_build_config not found; routing needs /etc/valhalla/valhalla.json"
fi

systemctl enable deck-mapd.service valhalla.service
