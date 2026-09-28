#!/bin/bash
# radio: RTL-SDR tools from Debian, plus SDR++ and SatDump release packages when
# they're available for this architecture (both are optional; the Radio app
# falls back to gqrx and reports SatDump as missing).
set -euo pipefail
source "$DECK_SRC/lib/common.sh"

# Keep the kernel's DVB driver off the RTL-SDR so rtl_* tools can use it
cat > /etc/modprobe.d/deckos-rtlsdr.conf <<'EOF'
blacklist dvb_usb_rtl28xxu
blacklist rtl2832_sdr
blacklist rtl2832
blacklist r820t
EOF

install_release_deb() {  # repo  asset-regex  name
  local repo="$1" pattern="$2" name="$3" url tmp
  url=$(curl -fsSL "https://api.github.com/repos/$repo/releases" \
        | jq -r '.[].assets[].browser_download_url' | grep -E "$pattern" | head -n1 || true)
  if [[ -z "$url" ]]; then
    warn "$name: no arm64 Debian package found in $repo releases"
    return 0
  fi
  tmp=$(mktemp -d)
  if fetch_optional "$url" "$tmp/pkg.deb"; then
    apt-get install -y --no-install-recommends "$tmp/pkg.deb" || warn "$name: package failed to install"
  fi
  rm -rf "$tmp"
}

install_release_deb "AlexandreRouma/SDRPlusPlus" "sdrpp_debian_(trixie|bookworm)_aarch64\.deb$" "SDR++"
install_release_deb "SatDump/SatDump" "satdump.*(arm64|aarch64).*\.deb$" "SatDump"

# fldigi keeps weather-fax images in ~/.fldigi/images; point that at Media
mkdir -p /etc/skel/.fldigi
ln -sfn /deck/media/wefax /etc/skel/.fldigi/images
mkdir -p /home/deck/.fldigi
ln -sfn /deck/media/wefax /home/deck/.fldigi/images
chown -R deck:deck /home/deck/.fldigi
