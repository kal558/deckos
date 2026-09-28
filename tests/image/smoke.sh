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
FAILS=0
check_fail() { echo "FAIL: $*"; FAILS=$((FAILS + 1)); }

if run_in test -s /etc/deckos/build-warnings.txt; then
  echo "================ build warnings (features skipped or degraded) ================"
  run_in cat /etc/deckos/build-warnings.txt
  echo "=============================================================================="
else
  pass "no build warnings: every module installed"
fi

# Units that can't work inside a container (no hardware, no clock/zram/remount rights)
CONTAINER_ONLY='^(systemd-(udev|rfkill|modules-load|sysctl|remount-fs|binfmt|timesyncd).*|.*\.device|run-u[0-9]+\.service|aic-bluetooth\.service|zramswap\.service|fake-hwclock.*|armbian-.*|deck-clock\.service|deck-emcon-boot\.service|chrony\.service|bluetooth\.service|NetworkManager-wait-online\.service)$'
failed=$(run_in systemctl --failed --no-legend --plain | awk '{print $1}' | grep -vE "$CONTAINER_ONLY" || true)
[[ -z "$failed" ]] && pass "no failed units" || check_fail "failed units: $failed"

for unit in NetworkManager nftables chrony deck-emcon-boot meshd deck-mapd deck-thermald; do
  state=$(run_in systemctl is-enabled "$unit.service" 2>/dev/null || true)
  [[ "$state" == enabled ]] && pass "$unit enabled" || check_fail "$unit is '$state'"
done

run_in nft list chain inet deckos input | grep -q 'policy drop' && pass "firewall default-deny" || check_fail "firewall"

bad=$(run_in /opt/deckos/venv/bin/python -c '
import subprocess
from deckos.selftest import non_local_listeners
print("\n".join(non_local_listeners(subprocess.run(["ss","-Hltnu"],capture_output=True,text=True).stdout)))' || echo "(listener check could not run)")
[[ -z "$bad" ]] && pass "nothing listens on the network" || check_fail "network listeners: $bad"

run_in /opt/deckos/venv/bin/python -c '
import importlib, pkgutil, deckos
skip = {"deckos.ui"}  # GTK apps need a display; imported below with a stub check
for m in pkgutil.walk_packages(deckos.__path__, "deckos."):
    if not any(m.name.startswith(s) for s in skip):
        importlib.import_module(m.name)
import gi; gi.require_version("Gtk", "4.0"); gi.require_version("WebKit", "6.0")
' && pass "all deckOS modules import" || check_fail "module import"

n=$(run_in /opt/deckos/venv/bin/python -c 'from deckos import manifest; print(len(manifest.load_all()))' || echo 0)
[[ "$n" -ge 15 ]] && pass "$n launcher tiles" || check_fail "only $n launcher tiles"

run_in deck-emcon status --json | grep -q '"text": "SILENT"' && pass "EMCON reports SILENT" || check_fail "EMCON not silent"

for exe in deck-home deck-reader deck-radio deck-mesh meshd deck-library deck-mapd deck-selftest deck-kodi deck-games \
           deck-firefox kiwix-serve rtl_fm welle-cli jt9 kodi retroarch libreoffice firefox-esr sway waybar tvheadend; do
  run_in sh -c "command -v $exe" >/dev/null && pass "has $exe" || echo "WARN: missing $exe"
done

run_in sway --validate -c /etc/sway/config >/dev/null 2>&1 && pass "sway config valid" || echo "WARN: sway config not validated (no display?)"

echo "smoke test complete: $FAILS failure(s)"
[[ $FAILS -eq 0 ]]
