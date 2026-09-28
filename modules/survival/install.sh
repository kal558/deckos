#!/bin/bash
set -euo pipefail
source "$DECK_SRC/lib/common.sh"
systemctl enable deck-thermald.service
