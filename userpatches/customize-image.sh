#!/bin/bash
# Armbian hook: runs inside the image chroot after the base system is installed.
# Arguments from Armbian: $1=RELEASE $2=LINUXFAMILY $3=BOARD $4=BUILD_DESKTOP
# Our files are at /tmp/overlay/deckos (staged by build.sh).
set -euo pipefail
set -E
# Name the exact failing command in the build log (Armbian only reports "Error 1")
trap 'echo "[deckos] FAILED: \"${BASH_COMMAND}\" at ${BASH_SOURCE[0]}:${LINENO} (module: ${DECK_CURRENT_MODULE:-none})" >&2' ERR

export DEBIAN_FRONTEND=noninteractive
export DECK_SRC=/tmp/overlay/deckos
# shellcheck source=lib/common.sh
source "$DECK_SRC/lib/common.sh"

log "deckOS customisation starting (release=$1 family=$2 board=$3)"

install -d -m 0755 /etc/deckos /usr/share/deckos/apps /usr/lib/deckos
install -m 0644 "$DECK_SRC/board.conf" /etc/deckos/board.conf
install -m 0644 "$DECK_SRC/version" /etc/deckos/version
install -m 0644 "$DECK_SRC/modules.list" /etc/deckos/modules.list

cp -L /etc/resolv.conf /tmp/resolv.conf.build 2>/dev/null || true
apt-get update

# Python runtime shared by all deckOS tools. System site packages are visible so
# GTK (python3-gi) comes from Debian; pip-only deps (meshtastic) go in the venv.
apt_install python3 python3-venv python3-pip python3-gi gir1.2-gtk-4.0
python3 -m venv --system-site-packages /opt/deckos/venv
/opt/deckos/venv/bin/pip install --no-cache-dir --upgrade pip
# pip builds in the source tree; /tmp/overlay may be read-only, so build from a copy
rm -rf /tmp/deckos-src
mkdir -p /tmp/deckos-src
cp -r "$DECK_SRC/src" "$DECK_SRC/pyproject.toml" /tmp/deckos-src/
/opt/deckos/venv/bin/pip install --no-cache-dir /tmp/deckos-src
rm -rf /tmp/deckos-src

mapfile -t MODULES < "$DECK_SRC/modules.list"
for m in "${MODULES[@]}"; do
  run_module "$DECK_SRC/modules/$m"
done

# Link every entry point the package declares into /usr/bin
for exe in /opt/deckos/venv/bin/deck-* /opt/deckos/venv/bin/meshd; do
  if [[ -e "$exe" ]]; then ln -sf "$exe" "/usr/bin/$(basename "$exe")"; fi
done

apt-get -y autoremove --purge
apt-get clean
rm -rf /var/lib/apt/lists/* /root/.cache
log "deckOS customisation complete"
