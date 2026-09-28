#!/bin/bash
# Fast pre-build check (about a minute): every package in every enabled module
# exists in Debian for the target release/arch, and every fixed download URL the
# build uses still resolves. Catches the common build failures before spending
# an hour compiling a kernel.
#   tools/preflight.sh [release=trixie] [arch=arm64]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RELEASE="${1:-trixie}"
ARCH="${2:-arm64}"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fail=0

echo ">> Debian $RELEASE/$ARCH package index"
for c in main contrib non-free non-free-firmware; do
  curl -fsSL "https://deb.debian.org/debian/dists/$RELEASE/$c/binary-$ARCH/Packages.gz" | zcat
done | awk '/^Package: /{print $2} /^Provides: /{sub(/^Provides: /,""); n=split($0,a,/, */); for(i=1;i<=n;i++){split(a[i],b," "); print b[1]}}' \
  | sort -u > "$tmp/pkgs"
echo "   $(wc -l < "$tmp/pkgs") packages"

# shellcheck source=../deckos.conf
source "$ROOT/deckos.conf"
check_pkg() {  # name source required(yes/no)
  if ! grep -qxF "$1" "$tmp/pkgs"; then
    if [[ "$3" == yes ]]; then echo "MISSING  $1  ($2)"; fail=1; else echo "optional missing  $1  ($2)"; fi
  fi
}
for p in python3 python3-venv python3-pip python3-gi gir1.2-gtk-4.0; do check_pkg "$p" customize-image.sh yes; done
for m in "${MODULES[@]}"; do
  d="$ROOT/modules/$m"
  if [[ -f "$d/packages.list" ]]; then
    while read -r p; do check_pkg "$p" "$m/packages.list" yes; done < <(grep -Ev '^\s*(#|$)' "$d/packages.list")
  fi
  if [[ -f "$d/packages-optional.list" ]]; then
    while read -r p; do check_pkg "$p" "$m/packages-optional.list" no; done < <(grep -Ev '^\s*(#|$)' "$d/packages-optional.list")
  fi
done

echo ">> Required download URLs"
for u in \
  https://cdn.jsdelivr.net/npm/maplibre-gl@5/dist/maplibre-gl.js \
  https://cdn.jsdelivr.net/npm/maplibre-gl@5/dist/maplibre-gl.css \
  https://cdn.jsdelivr.net/npm/pmtiles@4/dist/pmtiles.js \
  https://cdn.jsdelivr.net/npm/@protomaps/basemaps@5/dist/basemaps.js \
  https://github.com/protomaps/basemaps-assets/archive/refs/heads/main.zip \
  "https://dl.cloudsmith.io/public/tvheadend/tvheadend/deb/debian/dists/$RELEASE/Release"; do
  code=$(curl -s -o /dev/null -L -w '%{http_code}' "$u")
  if [[ "$code" != 200 ]]; then echo "BROKEN ($code)  $u"; fail=1; fi
done

if [[ $fail -ne 0 ]]; then echo ">> preflight FAILED"; exit 1; fi
echo ">> preflight OK"
