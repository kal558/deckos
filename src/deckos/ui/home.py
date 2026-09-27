"""deck-home: the full-screen tile grid. Started once by sway; `deck-home` again
brings it to the front (single instance).

Keys: arrows move, Enter opens, typing starts global search, F1 cheat sheet.
"""
from __future__ import annotations

import sys

from .. import hardware, manifest, status
from .common import Gdk, GLib, Gtk, apply_theme, label, run_bg, spawn, watch_theme

REFRESH_S = 5


class Tile(Gtk.Button):
    def __init__(self, app: manifest.App):
        super().__init__()
        self.app = app
        self.add_css_class("tile")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        icon = Gtk.Image.new_from_icon_name(app.icon)
        icon.set_pixel_size(40)
        icon.set_halign(Gtk.Align.START)
        box.append(icon)
        box.append(label(app.name, "tile-name"))
        self.status = label("", "tile-status", wrap=True)
        box.append(self.status)
        self.set_child(box)
        self.connect("clicked", lambda *_: spawn(["deck-launch", app.id]))

    def update(self, present: dict[str, bool], text: str) -> None:
        miss = hardware.missing(self.app.requires, present)
        if miss:
            self.add_css_class("unavailable")
            self.status.set_text(", ".join(hardware.LABELS.get(m, m) for m in miss) + " not connected")
        else:
            self.remove_css_class("unavailable")
            self.status.set_text(text)


class Home(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="org.deckos.Home")
        self.win: Gtk.ApplicationWindow | None = None
        self.tiles: list[Tile] = []

    def do_activate(self) -> None:
        if self.win:
            self.win.present()
            return
        apply_theme()
        watch_theme()
        self.win = Gtk.ApplicationWindow(application=self, title="Home")
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=24, margin_bottom=16,
                        margin_start=28, margin_end=28)
        head = Gtk.Box(spacing=12)
        head.append(label("deckOS", "title"))
        self.clock = label("", "subtitle", xalign=1.0)
        self.clock.set_hexpand(True)
        head.append(self.clock)
        outer.append(head)
        outer.append(label("Type to search everything  ·  F1 keys  ·  ⊞+E emissions", "muted"))

        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                max_children_per_line=6, min_children_per_line=2,
                                row_spacing=14, column_spacing=14, valign=Gtk.Align.START)
        for app in manifest.load_all():
            t = Tile(app)
            self.tiles.append(t)
            self.flow.append(t)
        sw = Gtk.ScrolledWindow(vexpand=True)
        sw.set_child(self.flow)
        outer.append(sw)
        self.win.set_child(outer)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        self.win.add_controller(keys)
        self.win.present()
        if self.tiles:
            self.tiles[0].grab_focus()
        self.refresh()
        GLib.timeout_add_seconds(REFRESH_S, self.refresh)
        GLib.timeout_add_seconds(1, self.tick)
        self.tick()

    def tick(self) -> bool:
        self.clock.set_text(GLib.DateTime.new_now_local().format("%a %d %b  %H:%M"))
        return True

    def refresh(self) -> bool:
        if not self.win or not self.win.is_active():
            return True  # don't poll while hidden

        def work():
            present = hardware.detect()
            texts = {t.app.id: (status.tile(t.app.status) if t.app.status else "") for t in self.tiles}
            return present, texts

        def done(res) -> None:
            if isinstance(res, Exception):
                return
            present, texts = res
            for t in self.tiles:
                t.update(present, texts.get(t.app.id, ""))

        run_bg(work, done)
        return True

    def on_key(self, _ctl, keyval, _code, state) -> bool:
        if keyval == Gdk.KEY_F1:
            spawn(["deck-cheatsheet"])
            return True
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK):
            return False
        ch = Gdk.keyval_to_unicode(keyval)
        if ch and chr(ch).isprintable() and not chr(ch).isspace():
            spawn(["deck-search", "--query", chr(ch)])
            return True
        return False


def main(argv: list[str] | None = None) -> int:
    return Home().run(sys.argv[:1] if argv is None else argv)


if __name__ == "__main__":
    sys.exit(main())
