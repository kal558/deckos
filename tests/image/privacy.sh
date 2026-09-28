#!/bin/bash
# Privacy test: boot the image with a network attached, capture everything it
# sends while idle, and fail if it sends anything other than link setup
# (DHCP, IPv6 neighbour/router discovery, ARP). Pass condition: zero connections.
# Usage: sudo tests/image/privacy.sh IMAGE [minutes=60]
set -euo pipefail
source "$(dirname "$0")/lib.sh"
MINUTES="${2:-60}"
command -v tcpdump >/dev/null || die "install tcpdump"

open_image "$1"
boot_container --network-veth
IFACE="ve-${MACHINE:0:12}"
ip link set "$IFACE" up || true
# Give the container a DHCP server so it is genuinely online during the test
ip addr add 10.77.0.1/24 dev "$IFACE" 2>/dev/null || true
if command -v dnsmasq >/dev/null; then
  dnsmasq --interface="$IFACE" --bind-interfaces --dhcp-range=10.77.0.50,10.77.0.99,1h --port=0 \
    --pid-file="$WORK/dnsmasq.pid"
fi

echo "Capturing for $MINUTES minutes on $IFACE..."
timeout "$((MINUTES * 60))" tcpdump -n -i "$IFACE" -w "$WORK/capture.pcap" \
  'not (arp or udp port 67 or udp port 68 or udp port 546 or udp port 547 or icmp6 or igmp)' 2>/dev/null || true
[[ -f "$WORK/dnsmasq.pid" ]] && kill "$(cat "$WORK/dnsmasq.pid")" 2>/dev/null || true

# Only count traffic the deck originated (not our DHCP server's)
leaks=$(tcpdump -n -r "$WORK/capture.pcap" 'not src host 10.77.0.1' 2>/dev/null | head -n 50 || true)
if [[ -n "$leaks" ]]; then
  echo "$leaks"
  die "the deck sent traffic while idle"
fi
pass "no outbound traffic in $MINUTES minutes"
