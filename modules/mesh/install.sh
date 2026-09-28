#!/bin/bash
set -euo pipefail
source "$DECK_SRC/lib/common.sh"
/opt/deckos/venv/bin/pip install --no-cache-dir "meshtastic>=2.5"
# Terminal client, used as a fallback if the Mesh app misbehaves
/opt/deckos/venv/bin/pip install --no-cache-dir contact || warn "meshtastic 'contact' TUI not installed"
if [[ -x /opt/deckos/venv/bin/contact ]]; then ln -sf /opt/deckos/venv/bin/contact /usr/bin/mesh-contact; fi
systemctl enable meshd.service
