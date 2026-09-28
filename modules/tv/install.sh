#!/bin/bash
# tv: tvheadend (Freeview HD backend) + Kodi Live TV.
# tvheadend isn't in Debian, so it comes from the project's official package
# repository. Demodulator firmware for common DVB-T2 sticks comes from the
# LibreELEC firmware collection (see BLOBS.md).
set -euo pipefail
source "$DECK_SRC/lib/common.sh"

TVH_REPO="https://dl.cloudsmith.io/public/tvheadend/tvheadend"
TVH_SUITE="${TVH_SUITE:-trixie}"   # the repo carries arm64 builds for trixie

if ! apt-get install -y --no-install-recommends tvheadend 2>/dev/null; then
  apt_install gpg
  if fetch_optional "$TVH_REPO/gpg.key" /tmp/tvh.key; then
    gpg --dearmor < /tmp/tvh.key > /usr/share/keyrings/tvheadend.gpg
    echo "deb [signed-by=/usr/share/keyrings/tvheadend.gpg] $TVH_REPO/deb/debian $TVH_SUITE main" \
      > /etc/apt/sources.list.d/tvheadend.list
    # tvheadend's installer asks for an admin user; we run it with --noacl on localhost instead
    echo "tvheadend tvheadend/admin_username string deck" | debconf-set-selections
    echo "tvheadend tvheadend/admin_password password deck" | debconf-set-selections
    if apt-get update && apt-get install -y --no-install-recommends tvheadend; then
      log "tvheadend installed from $TVH_REPO"
    else
      warn "tvheadend install failed: TV unavailable"
      # Don't leave a broken repository behind for later apt runs
      rm -f /etc/apt/sources.list.d/tvheadend.list
      apt-get update || true
    fi
  fi
fi
# Only runs while a tuner is plugged in (udev starts it)
systemctl disable tvheadend.service 2>/dev/null || true

# DVB-T2 demodulator/tuner firmware (Si2168/Si2157 family used by Hauppauge WinTV-dualHD etc.)
FW="https://raw.githubusercontent.com/LibreELEC/dvb-firmware/master/firmware"
mkdir -p /lib/firmware
for f in dvb-demod-si2168-b40-01.fw dvb-demod-si2168-d60-01.fw dvb-tuner-si2158-a20-01.fw dvb-usb-dib0700-1.20.fw; do
  [[ -f "/lib/firmware/$f" ]] || fetch_optional "$FW/$f" "/lib/firmware/$f" || true
done

# Persist tvheadend's channel scan in personal storage when unlocked
grep -q '/var/lib/tvheadend' /etc/fstab || \
  echo "/persist/system/tvheadend /var/lib/tvheadend none bind,nofail,x-systemd.requires-mounts-for=/persist 0 0" >> /etc/fstab
