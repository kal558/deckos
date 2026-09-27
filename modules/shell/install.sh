#!/bin/bash
set -euo pipefail
source "$DECK_SRC/lib/common.sh"
# Keyboard-only desktop starts automatically on tty1 for the deck user
systemctl enable getty@tty1.service
