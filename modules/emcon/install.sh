#!/bin/bash
set -euo pipefail
source "$DECK_SRC/lib/common.sh"
# Tor only runs while Tor mode is on
systemctl disable tor.service 2>/dev/null || true
