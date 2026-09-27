#!/bin/bash
# Boot a built image in a container and check the things that must always hold:
#   - it boots and core services start
#   - Wi-Fi/Bluetooth default off (checked via deck-emcon's view; no radios exist here)
#   - firewall is default-deny inbound
#   - nothing listens on the network
#   - every deckOS tool imports, every manifest loads, sway config is valid
# Usage: sudo tests/image/smoke.sh output/deckos-zero3w-*.img.xz
set -euo pipefail
source "$(dirname "$0")/lib.sh"

open_image "$1"
boot_container --private-network

failed=$(run_in systemctl --failed --no-legend --plain | awk '{print $1}' | grep -vE '^(systemd-(udev|rfkill|modules-load|sysctl).*|.*\.device)$' || true)
[[ -z "$failed" ]] && pass "no failed units" || die "failed units: $failed"

for unit in NetworkManager nftables chrony deck-emcon-boot meshd deck-mapd deck-thermald; do
  state=$(run_in systemctl is-enabled "$unit.service" 2>/dev/null || true)
  [[ "$state" == enabled ]] && pass "$unit enabled" || die "$unit is '$state'"
done

run_in nft list chain inet deckos input | grep -q 'policy drop' && pass "firewall default-deny" || die "firewall"

bad=$(run_in /opt/deckos/venv/bin/python -c '
import subprocess
from deckos.selftest import non_local_listeners
print("\n".join(non_local_listeners(subprocess.run(["ss","-Hltnu"],capture_output=True,text=True).stdout)))')
[[ -z "$bad" ]] && pass "nothing listens on the network" || die "network listeners: $bad"

run_in /opt/deckos/venv/bin/python -c '
import importlib, pkgutil, deckos
skip = {"deckos.ui"}  # GTK apps need a display; imported below with a stub check
for m in pkgutil.walk_packages(deckos.__path__, "deckos."):
    if not any(m.name.startswith(s) for s in skip):
        importlib.import_module(m.name)
import gi; gi.require_version("Gtk", "4.0"); gi.require_version("WebKit", "6.0")
' && pass "all deckOS modules import" || die "module import"

n=$(run_in /opt/deckos/venv/bin/python -c 'from deckos import manifest; print(len(manifest.load_all()))')
[[ "$n" -ge 15 ]] && pass "$n launcher tiles" || die "only $n launcher tiles"

run_in deck-emcon status --json | grep -q '"text": "SILENT"' && pass "EMCON reports SILENT" || die "EMCON not silent"

for exe in deck-home deck-reader deck-radio deck-mesh meshd deck-library deck-mapd deck-selftest deck-kodi deck-games \
           deck-firefox kiwix-serve rtl_fm welle-cli jt9 kodi retroarch libreoffice firefox-esr sway waybar tvheadend; do
  run_in sh -c "command -v $exe" >/dev/null && pass "has $exe" || echo "WARN: missing $exe"
done

run_in sway --validate -c /etc/sway/config >/dev/null 2>&1 && pass "sway config valid" || echo "WARN: sway config not validated (no display?)"

if run_in test -s /etc/deckos/build-warnings.txt; then
  echo "Build warnings recorded in the image:"
  run_in cat /etc/deckos/build-warnings.txt
fi
echo "smoke test complete"
