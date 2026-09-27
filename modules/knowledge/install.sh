#!/bin/bash
set -euo pipefail
source "$DECK_SRC/lib/common.sh"
systemctl enable kiwix-serve.service
# The PC import share only runs when switched on from the Library app
systemctl disable smbd.service nmbd.service samba-ad-dc.service 2>/dev/null || true
systemctl mask nmbd.service samba-ad-dc.service 2>/dev/null || true
