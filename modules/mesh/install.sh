#!/bin/bash
set -euo pipefail
source "$DECK_SRC/lib/common.sh"
/opt/deckos/venv/bin/pip install --no-cache-dir "meshtastic>=2.5"
# Terminal client, used as a fallback if the Mesh app misbehaves
/opt/deckos/venv/bin/pip install --no-cache-dir contact || warn "meshtastic 'contact' TUI not installed"
[[ -x /opt/deckos/venv/bin/contact ]] && ln -sf /opt/deckos/venv/bin/contact /usr/bin/mesh-contact
systemctl enable meshd.service
