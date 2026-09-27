"""Prepare a USB SSD as DECKDATA, or add the encrypted personal container to one.

    deck-ssd-setup format /dev/sdX      # ERASES the disk
    deck-ssd-setup personal             # add personal.luks to the mounted SSD
    deck-ssd-setup dirs                 # (re)create the standard folders
"""
from __future__ import annotations

import getpass
import os
import pwd
import subprocess
import sys
from pathlib import Path

from . import paths

LABEL = "DECKDATA"
PERSONAL_SIZE = "16G"
SWAP_SIZE = "2G"
DIRS = (
    "library/zim", "library/maps", "library/places", "library/valhalla", "library/staging",
    "media/video", "media/music", "media/photos", "media/recordings", "media/satellite", "media/wefax",
    "games/roms", "games/bios", "games/saves", "personal", ".deckos",
)


def _run(*cmd: str, input: str | None = None) -> None:
    subprocess.run(list(cmd), check=True, text=True, input=input)


def make_dirs(base: Path) -> None:
    try:
        deck = pwd.getpwnam("deck")
        uid, gid = deck.pw_uid, deck.pw_gid
    except KeyError:
        uid = gid = None
    for d in DIRS:
        p = base / d
        p.mkdir(parents=True, exist_ok=True)
        if uid is not None:
            os.chown(p, uid, gid)


def ask_passphrase(prompt: str = "Passphrase") -> str:
    while True:
        a = getpass.getpass(f"{prompt}: ")
        if len(a) < 8:
            print("Use at least 8 characters.")
            continue
        if a == getpass.getpass("Again: "):
            return a
        print("They didn't match. Try again.")


def create_personal(base: Path, passphrase: str) -> None:
    img = base / "personal.luks"
    if img.exists():
        print("personal.luks already exists; leaving it alone.")
        return
    _run("fallocate", "-l", PERSONAL_SIZE, str(img))
    os.chmod(img, 0o600)
    _run("cryptsetup", "luksFormat", "--type", "luks2", "--batch-mode", "--key-file=-", str(img), input=passphrase)
    _run("cryptsetup", "open", "--key-file=-", str(img), "personal", input=passphrase)
    _run("mkfs.ext4", "-q", "-L", "personal", "/dev/mapper/personal")
    (base / "personal").mkdir(exist_ok=True)
    _run("mount", "/dev/mapper/personal", str(base / "personal"))
    for sub in ("documents", "backup"):
        (base / "personal" / sub).mkdir(exist_ok=True)
    _run("chown", "-R", "deck:deck", str(base / "personal"))


def create_swap(base: Path) -> None:
    sw = base / "swapfile"
    if not sw.exists():
        _run("fallocate", "-l", SWAP_SIZE, str(sw))
        os.chmod(sw, 0o600)


def format_disk(dev: str) -> None:
    print(f"\nThis will ERASE EVERYTHING on {dev}.")
    subprocess.run(["lsblk", "-o", "NAME,SIZE,MODEL,LABEL", dev])
    if input('Type ERASE to continue: ').strip() != "ERASE":
        print("Cancelled.")
        sys.exit(1)
    subprocess.run(["umount", "-q", f"{dev}1"], stderr=subprocess.DEVNULL)
    _run("parted", "-s", dev, "mklabel", "gpt", "mkpart", "deckdata", "ext4", "1MiB", "100%")
    _run("udevadm", "settle")
    part = f"{dev}1" if not dev[-1].isdigit() else f"{dev}p1"
    _run("mkfs.ext4", "-q", "-L", LABEL, "-m", "1", part)
    paths.deck().mkdir(exist_ok=True)
    _run("mount", part, str(paths.deck()))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if os.geteuid() != 0:
        os.execvp("sudo", ["sudo", "/usr/bin/deck-ssd-setup", *argv])
    base = paths.deck()
    cmd = argv[0] if argv else ""
    if cmd == "format" and len(argv) == 2:
        format_disk(argv[1])
        make_dirs(base)
        create_swap(base)
        create_personal(base, ask_passphrase("Passphrase for the SSD personal folder (use your deck passphrase)"))
    elif cmd == "personal":
        if not paths.ssd_available():
            print("SSD not mounted at /deck")
            return 1
        create_personal(base, ask_passphrase("Passphrase (use your deck passphrase)"))
    elif cmd == "dirs":
        make_dirs(base)
    else:
        print(__doc__)
        return 2
    print("SSD ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
