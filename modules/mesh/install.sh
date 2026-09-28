#!/bin/bash
set -euo pipefail
source "$DECK_SRC/lib/common.sh"
/opt/deckos/venv/bin/pip install --no-cache-dir "meshtastic>=2.5"
# The official command-line client is the fallback if the Mesh app misbehaves
ln -sf /opt/deckos/venv/bin/meshtastic /usr/bin/meshtastic
systemctl enable meshd.service
