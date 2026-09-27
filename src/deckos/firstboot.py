"""First-boot setup, run once on tty1 before the desktop starts.

1. Set the deck user's password (used for sudo and unlocking the screen).
2. Create the encrypted /persist partition in the SD/eMMC's free space.
3. Optionally prepare the SSD's encrypted personal folder and restore a backup.
4. Record the power bank capacity (optional).
5. Switch the root filesystem to read-only and reboot.
"""
from __future__ import annotations

import getpass
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import paths, ssd

PERSIST_LABEL = "deckpersist"
MIN_FREE_BYTES = 1 << 30
FALLBACK_IMG = Path("/var/lib/deckos/persist.img")
PERSIST_DIRS = ("home", "state", "notes", "system/nm", "system/bluetooth", "system/tvheadend")


def sh(*cmd: str, input: str | None = None, check: bool = True) -> str:
    r = subprocess.run(list(cmd), check=check, text=True, input=input, capture_output=True)
    return r.stdout.strip()


def banner(text: str) -> None:
    print("\n" + "=" * 60 + f"\n  {text}\n" + "=" * 60)


def set_password() -> None:
    banner("1/5  Deck password")
    print("Used for admin tasks and the screen lock.")
    while True:
        a = getpass.getpass("New password: ")
        if len(a) >= 6 and a == getpass.getpass("Again: "):
            sh("chpasswd", input=f"deck:{a}\n")
            return
        print("Too short or didn't match.")


def root_disk() -> tuple[str, str]:
    src = sh("findmnt", "-no", "SOURCE", "/")
    disk = "/dev/" + sh("lsblk", "-no", "PKNAME", src).splitlines()[0]
    return src, disk


def free_tail_bytes(disk: str) -> int:
    """Size of the free region after the last partition (`sfdisk -F` rows: start end sectors size)."""
    out = sh("sfdisk", "-F", "--bytes", disk, check=False)
    sizes = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 4 and all(p.isdigit() for p in parts):
            sizes.append(int(parts[3]))
    return sizes[-1] if sizes else 0


def create_persist_device() -> str:
    """Append a partition in the free tail of the boot disk; fall back to a file."""
    _, disk = root_disk()
    if free_tail_bytes(disk) >= MIN_FREE_BYTES:
        before = set(sh("lsblk", "-lnpo", "NAME", disk).split())
        sh("sfdisk", "--append", "--no-reread", disk, input=",,L\n")
        sh("partx", "-u", disk, check=False)
        sh("udevadm", "settle")
        new = sorted(set(sh("lsblk", "-lnpo", "NAME", disk).split()) - before)
        if new:
            return new[-1]
    print("No free space after the OS; using a 4 GB encrypted file instead.")
    FALLBACK_IMG.parent.mkdir(parents=True, exist_ok=True)
    sh("fallocate", "-l", "4G", str(FALLBACK_IMG))
    os.chmod(FALLBACK_IMG, 0o600)
    return str(FALLBACK_IMG)


def setup_persist(passphrase: str) -> None:
    dev = create_persist_device()
    sh("cryptsetup", "luksFormat", "--type", "luks2", "--label", PERSIST_LABEL, "--batch-mode", "--key-file=-", dev,
       input=passphrase)
    sh("cryptsetup", "open", "--key-file=-", dev, "persist", input=passphrase)
    sh("mkfs.ext4", "-q", "-L", "persist", "/dev/mapper/persist")
    Path("/persist").mkdir(exist_ok=True)
    sh("mount", "/dev/mapper/persist", "/persist")
    for d in PERSIST_DIRS:
        Path("/persist", d).mkdir(parents=True, exist_ok=True)
    shutil.copytree("/home/deck", "/persist/home", dirs_exist_ok=True, symlinks=True)
    sh("chown", "-R", "deck:deck", "/persist/home", "/persist/state", "/persist/notes")
    os.chmod("/persist", 0o755)

    ident = f"UUID={sh('cryptsetup', 'luksUUID', dev)}" if dev.startswith("/dev/") else dev
    with open("/etc/crypttab", "a") as f:
        f.write(f"persist {ident} none luks,nofail,tries=3,timeout=180\n")
    with open("/etc/fstab", "a") as f:
        f.write("/dev/mapper/persist /persist ext4 noatime,nofail,x-systemd.device-timeout=200 0 2\n")


def setup_ssd(passphrase: str) -> None:
    banner("3/5  SSD")
    if not paths.ssd_available():
        print("No DECKDATA SSD found. You can set it up later from Settings → Storage.")
        return
    if not (paths.deck() / "personal.luks").exists():
        ssd.make_dirs(paths.deck())
        ssd.create_swap(paths.deck())
        print("Creating the encrypted personal folder on the SSD (same passphrase)...")
        ssd.create_personal(paths.deck(), passphrase)
    else:
        sh("cryptsetup", "open", "--key-file=-", str(paths.deck() / "personal.luks"), "personal",
           input=passphrase, check=False)
        sh("mount", "/dev/mapper/personal", str(paths.personal()), check=False)
    if (paths.personal() / "backup/persist").is_dir():
        if input("A backup from a previous deckOS was found. Restore it? [Y/n] ").strip().lower() != "n":
            from . import backup

            print(backup.restore())


def ask_capacity() -> None:
    banner("4/5  Power bank")
    print("Capacity in Wh from the power bank's label (e.g. 20000 mAh ≈ 74 Wh).")
    raw = input("Wh (blank to skip): ").strip()
    try:
        wh = float(raw)
    except ValueError:
        return
    state = paths.persist() / "state/power.json"
    state.write_text(json.dumps({"profile": "normal", "capacity_wh": wh, "used_wh": 0.0,
                                 "charged_at": None, "last_tick": None}))


def main() -> int:
    if os.geteuid() != 0:
        print("deck-firstboot must run as root", file=sys.stderr)
        return 1
    if Path("/etc/deckos/firstboot-done").exists():
        return 0
    banner("Welcome to deckOS")
    set_password()
    banner("2/5  Encrypted personal storage")
    print("Choose a passphrase. You'll type it at every boot to unlock your messages,")
    print("notes, keys and settings. Skipping it at boot still gives you the library,")
    print("maps, radio and media. If you forget it, personal data cannot be recovered.")
    passphrase = ssd.ask_passphrase("Passphrase")
    setup_persist(passphrase)
    setup_ssd(passphrase)
    ask_capacity()
    banner("5/5  Locking the system")
    Path("/etc/deckos/readonly").touch()
    Path("/etc/deckos/firstboot-done").touch()
    sh("sync")
    print("Done. Rebooting into deckOS...")
    subprocess.run(["systemctl", "reboot"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
