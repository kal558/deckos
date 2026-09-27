# Shared helpers for image tests: boot the built image's root filesystem in a
# systemd-nspawn container (arm64 via qemu-user-static on an x86 host).
# Requires: root, systemd-container, qemu-user-static (binfmt), xz-utils, util-linux.

MACHINE=deckos-test
WORK=""
LOOP=""

die() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

open_image() {
  local img="$1"
  [[ $EUID -eq 0 ]] || die "run as root"
  WORK=$(mktemp -d /tmp/deckos-test.XXXX)
  if [[ "$img" == *.xz ]]; then
    xz -dkc "$img" > "$WORK/image.img"
    img="$WORK/image.img"
  fi
  LOOP=$(losetup -Pf --show "$img")
  udevadm settle
  # the root filesystem is the largest ext4 partition
  local part
  part=$(lsblk -lnpo NAME,FSTYPE,SIZE -b "$LOOP" | awk '$2=="ext4"{print $3, $1}' | sort -n | tail -n1 | cut -d' ' -f2)
  [[ -n "$part" ]] || die "no ext4 root partition in image"
  mkdir -p "$WORK/root"
  mount -o ro "$part" "$WORK/root"
  trap close_image EXIT
}

close_image() {
  machinectl terminate "$MACHINE" >/dev/null 2>&1 || true
  sleep 2
  umount "$WORK/root" 2>/dev/null || true
  [[ -n "$LOOP" ]] && losetup -d "$LOOP" 2>/dev/null || true
  rm -rf "$WORK"
}

# boot_container [extra nspawn args...]
boot_container() {
  systemd-nspawn --quiet --machine="$MACHINE" -D "$WORK/root" --volatile=overlay \
    --boot "$@" -- systemd.mask=deck-firstboot.service systemd.mask=getty@tty1.service \
    >"$WORK/console.log" 2>&1 &
  local i
  for i in $(seq 1 180); do
    if systemd-run -M "$MACHINE" --wait -q -P /bin/true 2>/dev/null; then
      systemd-run -M "$MACHINE" --wait -q -P systemctl is-system-running --wait >/dev/null 2>&1 || true
      return 0
    fi
    sleep 2
  done
  tail -n 50 "$WORK/console.log"
  die "container did not boot"
}

run_in() {
  systemd-run -M "$MACHINE" --wait -q -P "$@"
}
