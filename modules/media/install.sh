#!/bin/bash
# media: Kodi library sources on the SSD, hardware video decoding for mpv.
set -euo pipefail
source "$DECK_SRC/lib/common.sh"

K=/home/deck/.kodi/userdata
mkdir -p "$K"
cat > "$K/sources.xml" <<'EOF'
<sources>
  <video>
    <default pathversion="1"></default>
    <source><name>Video</name><path pathversion="1">/deck/media/video/</path></source>
    <source><name>TV recordings</name><path pathversion="1">/deck/media/recordings/</path></source>
  </video>
  <music>
    <default pathversion="1"></default>
    <source><name>Music</name><path pathversion="1">/deck/media/music/</path></source>
  </music>
  <pictures>
    <default pathversion="1"></default>
    <source><name>Photos</name><path pathversion="1">/deck/media/photos/</path></source>
    <source><name>Weather satellites</name><path pathversion="1">/deck/media/satellite/</path></source>
    <source><name>Weather fax</name><path pathversion="1">/deck/media/wefax/</path></source>
  </pictures>
</sources>
EOF
cat > "$K/advancedsettings.xml" <<'EOF'
<advancedsettings version="1.0">
  <cache><memorysize>20971520</memorysize><readfactor>4</readfactor></cache>
  <network><disablehttp2>true</disablehttp2></network>
  <loglevel>-1</loglevel>
</advancedsettings>
EOF
chown -R deck:deck /home/deck/.kodi

# mpv: hardware decoding where the kernel supports it
mkdir -p /etc/mpv
cat > /etc/mpv/mpv.conf <<EOF
hwdec=auto-safe
vo=gpu
gpu-context=wayland
ytdl=no
EOF
