"""deck-emcon-panel (⊞+E): what the deck may transmit, with one-tap silence."""
from __future__ import annotations

import subprocess
import sys

from .. import emcon
from .common import GLib, Gtk, apply_theme, button, esc_closes, label, run_bg

ROWS = [
    ("wifi", "Wi-Fi", "Needed for internet. Random MAC address, no background scanning."),
    ("bluetooth", "Bluetooth", "Not discoverable. Pair new devices from Settings."),
    ("mesh", "Mesh transmit", "Send messages. Encrypted, but a transmitter can be located by direction-finding."),
]


def set_tx(kind: str, on: bool) -> None:
    subprocess.run(["deck-emcon", "set", kind, "on" if on else "off"], timeout=60)


class Panel(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="org.deckos.Emcon")
        self.win = None
        self.switches: dict[str, tuple[Gtk.Switch, int]] = {}

    def do_activate(self) -> None:
        if self.win:
            self.win.present()
            return
        apply_theme()
        self.win = Gtk.ApplicationWindow(application=self, title="Emissions control")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=24, margin_bottom=24,
                      margin_start=32, margin_end=32)
        self.head = label("", "big")
        box.append(self.head)
        box.append(label("Radio, TV, GPS and the SDR only receive and are always allowed.", "dim", wrap=True))
        for key, name, help_text in ROWS:
            row = Gtk.Box(spacing=16)
            txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
            txt.append(label(name, "title"))
            txt.append(label(help_text, "subtitle", wrap=True))
            row.append(txt)
            sw = Gtk.Switch(valign=Gtk.Align.CENTER)
            hid = sw.connect("state-set", lambda _s, st, k=key: self.toggle(k, st))
            self.switches[key] = (sw, hid)
            row.append(sw)
            box.append(row)
        tor = Gtk.Box(spacing=16)
        tt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        tt.append(label("Tor mode", "title"))
        tt.append(label("Route all internet traffic through Tor (slower).", "subtitle"))
        tor.append(tt)
        self.tor = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.tor_hid = self.tor.connect("state-set", lambda _s, st: self.toggle_tor(st))
        tor.append(self.tor)
        box.append(tor)
        box.append(button("GO SILENT  (⊞+Shift+E)", self.silent, "destructive-action"))
        self.win.set_child(box)
        esc_closes(self.win)
        self.win.present()
        self.refresh()
        GLib.timeout_add_seconds(3, self.refresh)

    def refresh(self) -> bool:
        run_bg(emcon.read_state, self.render)
        return True

    def render(self, st) -> None:
        if isinstance(st, Exception):
            return
        text, cls = emcon.summarize(st)
        self.head.set_text(text)
        for c in ("silent", "transmitting"):
            self.head.remove_css_class(c)
        self.head.add_css_class(cls)
        for key, (sw, hid) in self.switches.items():
            sw.handler_block(hid)
            sw.set_active(getattr(st, key))
            sw.handler_unblock(hid)
        self.switches["mesh"][0].set_sensitive(st.mesh_connected)
        self.tor.handler_block(self.tor_hid)
        self.tor.set_active(st.tor)
        self.tor.handler_unblock(self.tor_hid)

    def toggle(self, key: str, on: bool) -> bool:
        run_bg(lambda: set_tx(key, on), lambda _r: self.refresh())
        return False

    def toggle_tor(self, on: bool) -> bool:
        run_bg(lambda: subprocess.run(["deck-emcon", "tor", "on" if on else "off"], timeout=60),
               lambda _r: self.refresh())
        return False

    def silent(self) -> None:
        run_bg(lambda: subprocess.run(["deck-emcon", "silent"], timeout=60), lambda _r: self.refresh())


def main(argv: list[str] | None = None) -> int:
    return Panel().run(sys.argv[:1])


if __name__ == "__main__":
    sys.exit(main())
