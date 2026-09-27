"""deck-settings: radios, power, display, location, storage, updates, system."""
from __future__ import annotations

import json
import subprocess
import sys

from .. import backup, board, emcon, gps, paths, power
from .common import (Gtk, apply_theme, button, in_terminal, label, message, run_bg, set_theme_mode, spawn,
                     theme_mode, watch_theme)


def page(title: str) -> Gtk.Box:
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=16, margin_start=20, margin_end=20)
    b.append(label(title, "title"))
    return b


def row(title: str, subtitle: str, widget: Gtk.Widget) -> Gtk.Box:
    r = Gtk.Box(spacing=16)
    t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
    t.append(label(title))
    if subtitle:
        t.append(label(subtitle, "subtitle", wrap=True))
    r.append(t)
    widget.set_valign(Gtk.Align.CENTER)
    r.append(widget)
    return r


def removable_disks() -> list[tuple[str, str]]:
    """(device, description) for disks that aren't the boot disk."""
    out = subprocess.run(["lsblk", "-J", "-d", "-o", "NAME,SIZE,MODEL,TRAN,TYPE"], capture_output=True, text=True).stdout
    root = subprocess.run(["findmnt", "-no", "SOURCE", "/media/root-ro"], capture_output=True, text=True).stdout.strip() \
        or subprocess.run(["findmnt", "-no", "SOURCE", "/"], capture_output=True, text=True).stdout.strip()
    disks = []
    for d in json.loads(out or '{"blockdevices": []}').get("blockdevices", []):
        if d.get("type") != "disk" or d["name"].startswith(("mmcblk", "zram", "loop")):
            continue
        dev = f"/dev/{d['name']}"
        if root.startswith(dev):
            continue
        disks.append((dev, f"{dev}  {d.get('size', '')}  {d.get('model') or ''} ({d.get('tran') or '?'})"))
    return disks


class Settings(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="org.deckos.Settings")
        self.win = None

    def do_activate(self) -> None:
        if self.win:
            self.win.present()
            return
        apply_theme()
        watch_theme()
        self.win = Gtk.ApplicationWindow(application=self, title="Settings")
        stack = Gtk.Stack()
        for name, builder in (("Radios", self.radios), ("Power", self.power), ("Display", self.display),
                              ("Location", self.location), ("Storage", self.storage),
                              ("Updates", self.updates), ("System", self.system)):
            sw = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
            sw.set_child(builder())
            stack.add_titled(sw, name, name)
        side = Gtk.StackSidebar(stack=stack)
        side.set_size_request(180, -1)
        box = Gtk.Box()
        box.append(side)
        box.append(stack)
        self.win.set_child(box)
        self.win.present()

    # ---- pages
    def radios(self) -> Gtk.Widget:
        p = page("Radios")
        st = emcon.read_state()
        p.append(label("Wi-Fi and Bluetooth are switched off at every start-up. Turn them on here when you need them.",
                       "dim", wrap=True))
        wifi = Gtk.Switch(active=st.wifi)
        wifi.connect("state-set", lambda _s, on: run_bg(lambda: subprocess.run(["deck-emcon", "set", "wifi", "on" if on else "off"])) or False)
        p.append(row("Wi-Fi", "Random MAC per network; never joins open networks by itself.", wifi))
        p.append(row("Connect to a network", "", button("Choose network…", lambda: in_terminal(["nmtui-connect"], hold=False))))
        bt = Gtk.Switch(active=st.bluetooth)
        bt.connect("state-set", lambda _s, on: run_bg(lambda: subprocess.run(["deck-emcon", "set", "bluetooth", "on" if on else "off"])) or False)
        p.append(row("Bluetooth", "Never discoverable.", bt))
        p.append(row("Pair a device", "Opens pairing for 60 seconds.",
                     button("Pair…", lambda: (subprocess.run(["deck-emcon", "bt-pair"]), in_terminal(["bluetoothctl"], hold=False)))))
        p.append(row("Emissions control", "Mesh transmit, Tor mode, go silent.", button("Open", lambda: spawn(["deck-emcon-panel"]))))
        return p

    def power(self) -> Gtk.Widget:
        p = page("Power")
        st = power.status(board.load())
        prof = Gtk.DropDown.new_from_strings(["Field", "Normal", "Performance"])
        prof.set_selected(list(power.PROFILES).index(st["profile"]))
        prof.connect("notify::selected", lambda d, _p: subprocess.run(["deck-power", "profile", power.PROFILES[d.get_selected()]]))
        p.append(row("Profile", "Field: slower CPU, screen off sooner, TV/FT8/routing services stopped.", prof))
        cap = Gtk.SpinButton.new_with_range(0, 1000, 1)
        cap.set_value(st["capacity_wh"] or 0)
        p.append(row("Power bank capacity (Wh)", "From its label: mAh × 3.7 ÷ 1000.", cap))
        p.append(row("", "", button("Save capacity", lambda: subprocess.run(["deck-power", "set-capacity", str(cap.get_value())]))))
        p.append(row("I just charged or swapped the power bank", "Resets the runtime estimate.",
                     button("Reset", lambda: subprocess.run(["deck-power", "charged"]))))
        est = f"~{st['estimate_hours']} h left (estimate)" if st["estimate_hours"] is not None else "Set the capacity for an estimate."
        p.append(label(f"Temperature {st['temp_c']:.0f}°C · {est}", "dim"))
        p.append(row("Standby", "Screen off, CPU minimum; mesh keeps receiving. Any key wakes.",
                     button("Standby now", lambda: spawn(["deck-power", "standby"]))))
        return p

    def display(self) -> Gtk.Widget:
        p = page("Display")
        day = Gtk.Switch(active=theme_mode() == "day")

        def flip(_s, on: bool) -> bool:
            set_theme_mode("day" if on else "night")
            apply_theme()
            return False

        day.connect("state-set", flip)
        p.append(row("Daylight mode", "High contrast black on white for sunlight (⊞+D).", day))
        return p

    def location(self) -> Gtk.Widget:
        p = page("Location")
        p.append(label("Used for satellite passes when there's no GPS fix. Stored encrypted.", "dim", wrap=True))
        f = paths.user_state() / "location.json"
        try:
            cur = json.loads(f.read_text())
        except (OSError, ValueError):
            cur = {"lat": "", "lon": ""}
        lat = Gtk.Entry(text=str(cur["lat"]), placeholder_text="51.5")
        lon = Gtk.Entry(text=str(cur["lon"]), placeholder_text="-0.12")
        p.append(row("Latitude", "", lat))
        p.append(row("Longitude", "", lon))

        def save() -> None:
            try:
                f.write_text(json.dumps({"lat": float(lat.get_text()), "lon": float(lon.get_text())}))
                message(self.win, "Saved.")
            except ValueError:
                message(self.win, "Enter decimal degrees, e.g. 51.5 and -0.12")

        def from_gps() -> None:
            fix = gps.current(5)
            if fix:
                lat.set_text(f"{fix.lat:.4f}")
                lon.set_text(f"{fix.lon:.4f}")
            else:
                message(self.win, "No GPS fix right now.")

        r = Gtk.Box(spacing=6)
        r.append(button("Use GPS", from_gps))
        r.append(button("Save", save, "suggested-action"))
        p.append(r)
        return p

    def storage(self) -> Gtk.Widget:
        p = page("Storage")
        p.append(label(f"Personal storage: {'unlocked' if paths.persist_available() else 'LOCKED'}   ·   "
                       f"SSD: {'connected' if paths.ssd_available() else 'not connected'}   ·   "
                       f"SSD personal folder: {'unlocked' if paths.personal_available() else 'locked'}", "dim", wrap=True))
        disks = removable_disks()
        dd = Gtk.DropDown.new_from_strings([d[1] for d in disks] or ["No USB disks found"])
        p.append(row("Prepare a new SSD", "ERASES the chosen disk and sets it up as DECKDATA.", dd))

        def fmt() -> None:
            if disks:
                in_terminal(["deck-ssd-setup", "format", disks[dd.get_selected()][0]])

        p.append(row("", "", button("Erase and set up…", fmt, "destructive-action")))
        p.append(row("Add encrypted personal folder", "For an SSD prepared elsewhere.",
                     button("Add…", lambda: in_terminal(["deck-ssd-setup", "personal"]))))
        info = backup.info()
        p.append(row("Back up personal data now", "Also happens at every shutdown.",
                     button("Back up", lambda: run_bg(backup.backup, lambda r: message(self.win, str(r))))))
        p.append(label("Last backup: " + ("see deck-backup info" if info else "none yet"), "muted"))
        p.append(row("Restore from SSD backup", "", button("Restore…", lambda: in_terminal(["sudo", "deck-backup", "restore"]))))
        return p

    def updates(self) -> Gtk.Widget:
        p = page("Updates")
        p.append(label("Nothing updates by itself. Turn on Wi-Fi, then check. Updates apply to the locked system "
                       "and take effect after a reboot.", "dim", wrap=True))
        p.append(row("System updates", "", button("Check", lambda: in_terminal(["deck-update", "check"]))))
        p.append(row("", "", button("Apply updates", lambda: in_terminal(["deck-update", "apply"]), "suggested-action")))
        p.append(row("Library and maps", "", button("Open Library", lambda: spawn(["deck-launch", "library"]))))
        return p

    def system(self) -> Gtk.Widget:
        p = page("System")
        b = board.load()
        try:
            ver = (paths.etc() / "version").read_text().strip()
        except OSError:
            ver = "dev"
        p.append(label(f"deckOS {ver} · {b.name} · {board.mem_total_kib() / 1048576:.1f} GB RAM"
                       + (" (low-memory mode: one heavy app at a time)" if board.is_low_memory() else ""), "dim", wrap=True))
        p.append(row("Self-test", "Checks hardware, firewall, emissions and video decoding.",
                     button("Run", lambda: in_terminal(["deck-selftest"]))))
        p.append(row("Change password", "", button("Change…", lambda: in_terminal(["passwd"]))))
        p.append(row("Factory reset", "Erases personal storage and settings. The library on the SSD is kept.",
                     button("Reset…", lambda: in_terminal(["sudo", "deck-factory-reset"]), "destructive-action")))
        return p


def main(argv: list[str] | None = None) -> int:
    return Settings().run(sys.argv[:1])


if __name__ == "__main__":
    sys.exit(main())
