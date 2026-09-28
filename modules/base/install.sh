#!/bin/bash
# base: user, read-only root, encrypted storage layout, hardening, services.
set -euo pipefail
source "$DECK_SRC/lib/common.sh"

# ---- the deck user (password is set by deck-firstboot) ------------------------
if ! id deck >/dev/null 2>&1; then
  # useradd exits 9 if a "deck" group already exists and it's asked to create one
  if getent group deck >/dev/null; then
    useradd -m -s /bin/bash -g deck deck
  else
    useradd -m -s /bin/bash -U deck
  fi
fi
for g in sudo audio video render input plugdev dialout netdev bluetooth lp; do
  if getent group "$g" >/dev/null; then usermod -aG "$g" deck; fi
done
passwd -l deck
passwd -l root
# Armbian's interactive first-login wizard is replaced by deck-firstboot
rm -f /root/.not_logged_in_yet
# fake-hwclock is replaced by deck-clock (which never moves the clock backwards)
for svc in armbian-firstrun-config armbian-resize-filesystem armbian-zram-config armbian-ramlog \
           fake-hwclock fake-hwclock-load fake-hwclock-save; do
  systemctl disable "$svc.service" 2>/dev/null || true
done

# ---- locale / time / names -----------------------------------------------------------
sed -i 's/^# *en_GB.UTF-8/en_GB.UTF-8/' /etc/locale.gen
locale-gen
update-locale LANG=en_GB.UTF-8
ln -sf /usr/share/zoneinfo/Europe/London /etc/localtime
echo deck > /etc/hostname
sed -i 's/^127\.0\.1\.1.*/127.0.1.1\tdeck/' /etc/hosts
grep -q 'deck$' /etc/hosts || echo -e "127.0.1.1\tdeck" >> /etc/hosts
# Don't advertise the OS on the console banner
echo "deckOS \l" > /etc/issue
: > /etc/motd
chmod -x /etc/update-motd.d/* 2>/dev/null || true

# ---- remove anything that listens on the network or phones home -------------------------
apt-get purge -y unattended-upgrades avahi-daemon openssh-server apt-listchanges 2>/dev/null || true
systemctl mask systemd-timesyncd.service ssh.service sshd.service 2>/dev/null || true
cat > /etc/apt/apt.conf.d/20deckos-no-auto <<'EOF'
APT::Periodic::Enable "0";
APT::Periodic::Update-Package-Lists "0";
APT::Periodic::Unattended-Upgrade "0";
EOF
systemctl disable apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true

# ---- read-only root: overlay in the initramfs ------------------------------------------------
grep -qx overlay /etc/initramfs-tools/modules || echo overlay >> /etc/initramfs-tools/modules
mkdir -p /media/root-ro /media/root-rw

# ---- storage layout ------------------------------------------------------------------------------
# /persist is added to crypttab/fstab by deck-firstboot (it needs the partition UUID).
mkdir -p /persist /deck
cat >> /etc/crypttab <<'EOF'
# deckOS: SSD personal folder (same passphrase as /persist; systemd reuses the cached one)
personal /deck/personal.luks none luks,nofail,tries=1,timeout=60
# deckOS: encrypted swap on the SSD with a fresh random key every boot
swap /deck/swapfile /dev/urandom swap,cipher=aes-xts-plain64,size=512,nofail
EOF
cat >> /etc/fstab <<'EOF'
# deckOS
LABEL=DECKDATA /deck ext4 noatime,nofail,x-systemd.device-timeout=10 0 2
/dev/mapper/personal /deck/personal ext4 noatime,nofail,x-systemd.requires-mounts-for=/deck 0 2
/dev/mapper/swap none swap sw,nofail,pri=10 0 0
/persist/home /home/deck none bind,nofail,x-systemd.requires-mounts-for=/persist 0 0
/persist/system/bluetooth /var/lib/bluetooth none bind,nofail,x-systemd.requires-mounts-for=/persist 0 0
EOF

# ---- runtime dirs, permissions -------------------------------------------------------------------
chmod 0440 /etc/sudoers.d/deckos
visudo -cf /etc/sudoers.d/deckos

systemctl enable NetworkManager.service systemd-resolved.service nftables.service chrony.service \
  zramswap.service deck-emcon-boot.service deck-clock.service deck-backup.service deck-firstboot.service
systemctl enable gpsd.socket 2>/dev/null || true
# /etc/resolv.conf -> resolved's stub is set at boot by tmpfiles.d/deckos.conf
# (changing it here would break DNS inside the build chroot).

update-initramfs -u -k all
