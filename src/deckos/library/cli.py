"""deck-library: manage offline content.

    deck-library status                  what's installed, sizes, ages, free space
    deck-library install ID [ID...]      download (needs network)
    deck-library install --defaults      everything marked default in the catalogue
    deck-library update                  refresh every installed item that has a newer version
    deck-library remove ID
    deck-library import                  move files dropped in /deck/library/staging into place
    deck-library rebuild                 regenerate the kiwix catalogue
    deck-library share on|off            PC import share (Samba) on the current network

Downloads come only from the official Kiwix mirrors (metalink with SHA-256
verification by aria2c) and the Protomaps build server.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from .. import paths
from . import catalog, kiwix_opds, store

PROTOMAPS_BUILDS = "https://build-metadata.protomaps.dev/builds.json"
PROTOMAPS_BASE = "https://build.protomaps.com/"


def _gb(n: int) -> str:
    return f"{n / 1e9:.1f} GB"


def cmd_status(items: list[catalog.Item], as_json: bool) -> int:
    rows = []
    for it in items:
        inst = store.installed_item(it)
        rows.append({
            "id": it.id, "title": it.title, "group": it.group, "kind": it.kind,
            "installed": inst is not None,
            "date": inst.date if inst else None,
            "age_months": inst.age_months() if inst else None,
            "size_bytes": inst.size_bytes if inst else int(it.size_gb * 1e9),
            "default": it.default,
        })
    used, free = store.disk_usage()
    if as_json:
        print(json.dumps({"items": rows, "used": used, "free": free, "ssd": paths.ssd_available()}))
        return 0
    if not paths.ssd_available():
        print("SSD not connected.")
    group = None
    for r in rows:
        if r["group"] != group:
            group = r["group"]
            print(f"\n{group}")
        mark = "✔" if r["installed"] else " "
        age = f"{r['age_months']} months old" if r["age_months"] is not None else ""
        print(f"  [{mark}] {r['id']:20s} {_gb(r['size_bytes']):>9s}  {age}")
    print(f"\nUsed {_gb(used)}, free {_gb(free)}")
    return 0


def _download_zim(it: catalog.Item) -> bool:
    book = kiwix_opds.resolve(it.name)
    if book is None:
        print(f"{it.id}: '{it.name}' not found in the Kiwix catalogue (edit catalog.toml)")
        return False
    cur = store.installed_zims().get(it.name)
    if cur and cur.path.name == book.filename:
        print(f"{it.id}: already up to date ({cur.date})")
        return True
    staging = paths.library() / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    print(f"{it.id}: downloading {book.filename} ({_gb(book.size_bytes)})")
    r = subprocess.run([
        "aria2c", "--dir", str(staging), "--follow-metalink=mem", "--check-integrity=true",
        "--continue=true", "--max-connection-per-server=4", "--split=4", "--summary-interval=5",
        "--console-log-level=warn", "--file-allocation=none", book.meta4_url,
    ])
    f = staging / book.filename
    if r.returncode != 0 or not f.exists():
        print(f"{it.id}: download failed (it will resume next time)")
        return False
    store.zim_dir().mkdir(parents=True, exist_ok=True)
    shutil.move(str(f), store.zim_dir() / book.filename)
    for old in store.superseded_zims():
        old.unlink()
    print(f"{it.id}: installed")
    return True


def latest_protomaps_build() -> str:
    with urllib.request.urlopen(PROTOMAPS_BUILDS, timeout=30) as r:
        builds = json.load(r)
    keys = sorted(b["key"] for b in builds if b.get("key", "").endswith(".pmtiles"))
    if not keys:
        raise RuntimeError("no Protomaps builds listed")
    return PROTOMAPS_BASE + keys[-1]


def _download_pmtiles(it: catalog.Item) -> bool:
    src = latest_protomaps_build()
    store.maps_dir().mkdir(parents=True, exist_ok=True)
    tmp = store.maps_dir() / f"{it.id}.pmtiles.part"
    bbox = ",".join(str(x) for x in it.bbox)
    print(f"{it.id}: extracting z0-{it.maxzoom} for {bbox} from {src.rsplit('/', 1)[-1]}")
    r = subprocess.run(["pmtiles", "extract", src, str(tmp), f"--bbox={bbox}", f"--maxzoom={it.maxzoom}"])
    if r.returncode != 0 or not tmp.exists():
        print(f"{it.id}: extract failed")
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(store.maps_dir() / f"{it.id}.pmtiles")
    print(f"{it.id}: installed")
    return True


def install(items: list[catalog.Item], ids: list[str]) -> int:
    if not paths.ssd_available():
        print("SSD not connected.")
        return 1
    by_id = {i.id: i for i in items}
    failed = 0
    for iid in ids:
        it = by_id.get(iid)
        if it is None:
            print(f"unknown item: {iid}")
            failed += 1
            continue
        try:
            if it.kind == "zim":
                ok = _download_zim(it)
            elif it.kind == "pmtiles":
                ok = _download_pmtiles(it)
            else:
                print(f"{it.id}: build this on a PC with tools/build-map-data.sh, copy it into "
                      f"/deck/library/staging, then run 'deck-library import'")
                ok = store.installed_item(it) is not None
        except OSError as e:
            print(f"{it.id}: network error: {e}")
            ok = False
        if ok and it.replaces and it.replaces in by_id:
            old = store.installed_item(by_id[it.replaces])
            if old:
                old.path.unlink()
                print(f"removed {it.replaces} (replaced by {it.id})")
        failed += 0 if ok else 1
    store.rebuild_kiwix_library()
    return 1 if failed else 0


def import_staging() -> int:
    staging = paths.library() / "staging"
    moved = 0
    for f in sorted(staging.glob("*")) if staging.is_dir() else []:
        if f.suffix == ".zim":
            dest = store.zim_dir() / f.name
        elif f.suffix == ".pmtiles":
            dest = store.maps_dir() / f.name
        elif f.name == "places.sqlite":
            dest = paths.library() / "places" / f.name
        elif f.name == "valhalla_tiles.tar":
            dest = paths.library() / "valhalla" / f.name
        else:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), dest)
        print(f"imported {f.name}")
        moved += 1
    for old in store.superseded_zims():
        old.unlink()
    store.rebuild_kiwix_library()
    # Allowed without a password by /etc/sudoers.d/deckos
    subprocess.run(["sudo", "-n", "/usr/bin/systemctl", "try-restart", "valhalla.service"], check=False)
    print(f"{moved} file(s) imported")
    return 0


SMB_INCLUDE = Path("/run/deckos/smb-interfaces.conf")


def share(on: bool) -> int:
    if os.geteuid() != 0:
        os.execvp("sudo", ["sudo", "/usr/bin/deck-library", "share", "on" if on else "off"])
    if not on:
        subprocess.run(["systemctl", "stop", "smbd.service"])
        subprocess.run(["nft", "delete", "table", "inet", "deckos_share"], stderr=subprocess.DEVNULL)
        print("PC import share is off.")
        return 0
    out = subprocess.run(["nmcli", "-t", "-f", "DEVICE,STATE", "device"], capture_output=True, text=True).stdout
    ifaces = [line.split(":")[0] for line in out.splitlines() if line.endswith(":connected") and not line.startswith("lo")]
    if not ifaces:
        print("Not connected to a network. Turn on Wi-Fi (or plug in Ethernet) first.")
        return 1
    SMB_INCLUDE.parent.mkdir(parents=True, exist_ok=True)
    SMB_INCLUDE.write_text(f"interfaces = {' '.join(ifaces)}\nbind interfaces only = yes\n")
    import getpass

    pw = getpass.getpass("Password for the share (you'll type it on your PC): ")
    subprocess.run(["smbpasswd", "-a", "-s", "deck"], input=f"{pw}\n{pw}\n", text=True, check=True)
    rules = "table inet deckos_share {\n chain input {\n  type filter hook input priority -10;\n" + \
        "".join(f'  iifname "{i}" tcp dport 445 accept\n' for i in ifaces) + " }\n}\n"
    subprocess.run(["nft", "-f", "-"], input=rules, text=True, check=True)
    subprocess.run(["systemctl", "start", "smbd.service"], check=True)
    ip = subprocess.run(["hostname", "-I"], capture_output=True, text=True).stdout.split()
    print(f"Share is on. From Windows: \\\\{ip[0] if ip else 'deck'}\\deck  (user: deck)")
    print("It switches off at reboot, or run 'deck-library share off'.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="deck-library", description="Offline library manager")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status")
    s.add_argument("--json", action="store_true")
    i = sub.add_parser("install")
    i.add_argument("ids", nargs="*")
    i.add_argument("--defaults", action="store_true")
    sub.add_parser("update")
    r = sub.add_parser("remove")
    r.add_argument("id")
    sub.add_parser("import")
    sub.add_parser("rebuild")
    sh = sub.add_parser("share")
    sh.add_argument("state", choices=("on", "off"))
    args = ap.parse_args(argv)
    items = catalog.load()

    if args.cmd == "status":
        return cmd_status(items, args.json)
    if args.cmd == "install":
        ids = [i.id for i in items if i.default] if args.defaults else args.ids
        if not ids:
            print("nothing to install")
            return 2
        return install(items, ids)
    if args.cmd == "update":
        ids = [i.id for i in items if i.kind != "prebuilt" and store.installed_item(i)]
        return install(items, ids)
    if args.cmd == "remove":
        it = next((i for i in items if i.id == args.id), None)
        inst = store.installed_item(it) if it else None
        if inst is None:
            print("not installed")
            return 1
        inst.path.unlink()
        store.rebuild_kiwix_library()
        print(f"removed {args.id}")
        return 0
    if args.cmd == "import":
        return import_staging()
    if args.cmd == "rebuild":
        print(f"{store.rebuild_kiwix_library()} books in catalogue")
        return 0
    if args.cmd == "share":
        return share(args.state == "on")
    return 2


if __name__ == "__main__":
    sys.exit(main())
