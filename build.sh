#!/usr/bin/env bash
# Build a flashable deckOS image.
#   ./build.sh --board zero3w      Radxa Zero 3W
#   ./build.sh --board rpi         Raspberry Pi 4/5
# Options:
#   --kernel vendor|current|edge   override the board's kernel branch
#   --clean                        re-clone the Armbian framework
# Runs on Linux (Ubuntu 24.04 recommended, including WSL2). Armbian pulls its own
# Docker container if the host is not a supported build host.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOARD=""
KERNEL_OVERRIDE=""
CLEAN=no

while [[ $# -gt 0 ]]; do
  case "$1" in
    --board) BOARD="$2"; shift 2 ;;
    --kernel) KERNEL_OVERRIDE="$2"; shift 2 ;;
    --clean) CLEAN=yes; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

case "$BOARD" in
  zero3w) BOARD_FILE="$ROOT/boards/radxa-zero3w.conf" ;;
  rpi)    BOARD_FILE="$ROOT/boards/rpi4-5.conf" ;;
  *) echo "Usage: $0 --board zero3w|rpi" >&2; exit 2 ;;
esac

# shellcheck source=deckos.conf
source "$ROOT/deckos.conf"
# shellcheck source=boards/radxa-zero3w.conf
source "$BOARD_FILE"
[[ -n "$KERNEL_OVERRIDE" ]] && ARMBIAN_BRANCH="$KERNEL_OVERRIDE"

for required in base emcon shell; do
  [[ " ${MODULES[*]} " == *" $required "* ]] || { echo "Module '$required' is required" >&2; exit 2; }
done
for m in "${MODULES[@]}"; do
  [[ -d "$ROOT/modules/$m" ]] || { echo "Module '$m' not found in modules/" >&2; exit 2; }
done

ARMBIAN_DIR="$ROOT/armbian"
if [[ "$CLEAN" == yes ]]; then rm -rf "$ARMBIAN_DIR"; fi
if [[ ! -d "$ARMBIAN_DIR/.git" ]]; then
  git clone --depth 1 --branch "$ARMBIAN_REF" "$ARMBIAN_REPO" "$ARMBIAN_DIR" 2>/dev/null \
    || git clone "$ARMBIAN_REPO" "$ARMBIAN_DIR"
fi
git -C "$ARMBIAN_DIR" fetch --depth 1 origin "$ARMBIAN_REF" 2>/dev/null || true
git -C "$ARMBIAN_DIR" checkout -q FETCH_HEAD 2>/dev/null || git -C "$ARMBIAN_DIR" checkout -q "$ARMBIAN_REF"
ARMBIAN_COMMIT="$(git -C "$ARMBIAN_DIR" rev-parse HEAD)"

# Stage userpatches: Armbian copies userpatches/overlay into the chroot at /tmp/overlay
UP="$ARMBIAN_DIR/userpatches"
rm -rf "$UP"
mkdir -p "$UP/overlay/deckos"
cp "$ROOT/userpatches/customize-image.sh" "$UP/customize-image.sh"
chmod +x "$UP/customize-image.sh"
cp -r "$ROOT/userpatches/lib" "$UP/overlay/deckos/lib"
cp -r "$ROOT/src" "$ROOT/pyproject.toml" "$UP/overlay/deckos/"
mkdir -p "$UP/overlay/deckos/modules"
for m in "${MODULES[@]}"; do cp -r "$ROOT/modules/$m" "$UP/overlay/deckos/modules/$m"; done
cp "$BOARD_FILE" "$UP/overlay/deckos/board.conf"
printf '%s\n' "${MODULES[@]}" > "$UP/overlay/deckos/modules.list"
DECKOS_VERSION="$(date -u +%Y.%m.%d)-$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo dev)"
echo "$DECKOS_VERSION" > "$UP/overlay/deckos/version"

cat > "$UP/config-deckos.conf" <<EOF
BOARD="$ARMBIAN_BOARD"
BRANCH="$ARMBIAN_BRANCH"
RELEASE="$RELEASE"
BUILD_MINIMAL=yes
BUILD_DESKTOP=no
KERNEL_CONFIGURE=no
KERNEL_GIT=shallow
COMPRESS_OUTPUTIMAGE=sha,xz
FIXED_IMAGE_SIZE=$IMAGE_SIZE_MIB
EXPERT=yes
EOF

echo ">> Building deckOS $DECKOS_VERSION for $DECK_BOARD_NAME (Armbian $ARMBIAN_BOARD/$ARMBIAN_BRANCH/$RELEASE @ ${ARMBIAN_COMMIT:0:12})"
(cd "$ARMBIAN_DIR" && ./compile.sh deckos)

mkdir -p "$ROOT/output"
shopt -s nullglob
imgs=("$ARMBIAN_DIR"/output/images/*.img.xz)
[[ ${#imgs[@]} -gt 0 ]] || { echo "Build produced no image" >&2; exit 1; }
latest="$(ls -t "${imgs[@]}" | head -n1)"
out="$ROOT/output/deckos-$DECK_BOARD_ID-$DECKOS_VERSION.img.xz"
cp "$latest" "$out"
[[ -f "$latest.sha" ]] && cp "$latest.sha" "$out.sha"

cat > "$ROOT/output/BUILDINFO-$DECK_BOARD_ID.txt" <<EOF
deckos_version=$DECKOS_VERSION
board=$DECK_BOARD_ID
armbian_board=$ARMBIAN_BOARD
armbian_branch=$ARMBIAN_BRANCH
armbian_commit=$ARMBIAN_COMMIT
release=$RELEASE
modules=${MODULES[*]}
built_utc=$(date -u +%FT%TZ)
EOF

echo ">> Done: $out"
echo ">> Flash it with balenaEtcher or Raspberry Pi Imager."
