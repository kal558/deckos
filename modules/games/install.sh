#!/bin/bash
# games: RetroArch with Debian's cores plus the libretro buildbot's aarch64 cores
# that Debian doesn't package, and ES-DE as the game-library front end.
set -euo pipefail
source "$DECK_SRC/lib/common.sh"

CORES_DIR=/usr/lib/aarch64-linux-gnu/libretro
BUILDBOT=https://buildbot.libretro.com/nightly/linux/aarch64/latest
EXTRA_CORES=(pcsx_rearmed mupen64plus_next flycast fbneo dosbox_pure scummvm ppsspp picodrive)
mkdir -p "$CORES_DIR"
tmp=$(mktemp -d)
for c in "${EXTRA_CORES[@]}"; do
  if fetch_optional "$BUILDBOT/${c}_libretro.so.zip" "$tmp/$c.zip"; then
    unzip -o -q "$tmp/$c.zip" -d "$CORES_DIR"
  fi
done
rm -rf "$tmp"

# ES-DE (EmulationStation Desktop Edition) aarch64 AppImage, extracted so it runs without FUSE
ESDE_URL="${ESDE_URL:-}"
if [[ -z "$ESDE_URL" ]]; then
  ESDE_URL=$(curl -fsSL "https://gitlab.com/api/v4/projects/es-de%2Femulationstation-de/releases" \
    | jq -r '.[0].assets.links[].url' | grep -iE 'aarch64.*AppImage$' | grep -viE 'steamdeck' | head -n1 || true)
fi
if [[ -n "$ESDE_URL" ]] && fetch_optional "$ESDE_URL" /tmp/es-de.AppImage; then
  chmod +x /tmp/es-de.AppImage
  (cd /opt && /tmp/es-de.AppImage --appimage-extract >/dev/null && rm -rf /opt/es-de && mv squashfs-root /opt/es-de) \
    || warn "ES-DE AppImage could not be extracted; RetroArch will be the games front end"
  rm -f /tmp/es-de.AppImage
else
  warn "ES-DE not downloaded; RetroArch will be the games front end"
fi

# Settings: ROMs, BIOS and saves all live on the SSD
mkdir -p /home/deck/ES-DE/settings /home/deck/.config/retroarch
cat > /home/deck/ES-DE/settings/es_settings.xml <<'EOF'
<?xml version="1.0"?>
<string name="ROMDirectory" value="/deck/games/roms" />
<string name="MediaDirectory" value="/deck/games/media" />
<bool name="ScraperUseAccountScreenScraper" value="false" />
<bool name="ApplicationUpdaterCheck" value="false" />
EOF
cat > /home/deck/.config/retroarch/retroarch.cfg <<EOF
libretro_directory = "$CORES_DIR"
libretro_info_path = "/usr/share/libretro/info"
system_directory = "/deck/games/bios"
savefile_directory = "/deck/games/saves"
savestate_directory = "/deck/games/saves/states"
rgui_browser_directory = "/deck/games/roms"
video_driver = "gl"
video_fullscreen = "true"
audio_driver = "pulse"
menu_driver = "ozone"
network_cmd_enable = "false"
netplay_public_announce = "false"
cheevos_enable = "false"
core_updater_auto_extract_archive = "true"
EOF
chown -R deck:deck /home/deck/ES-DE /home/deck/.config
