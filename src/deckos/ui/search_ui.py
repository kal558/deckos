"""deck-search: the ⊞+Space overlay. Type once, search everything."""
from __future__ import annotations

import argparse
import sys

from .. import search
from .common import GLib, Gtk, apply_theme, esc_closes, label, run_bg, scrolled, spawn

DEBOUNCE_MS = 350


class SearchApp(Gtk.Application):
    def __init__(self, initial: str = "") -> None:
        super().__init__(application_id="org.deckos.Search")
        self.initial = initial
        self.win = None
        self.pending = 0
        self.generation = 0

    def do_activate(self) -> None:
        if self.win:
            self.win.present()
            return
        apply_theme()
        self.win = Gtk.ApplicationWindow(application=self, title="Search")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=24, margin_bottom=16,
                      margin_start=28, margin_end=28)
        self.entry = Gtk.Entry(placeholder_text="Search Wikipedia, library, places, files, notes, mesh, apps…")
        self.entry.add_css_class("search")
        self.entry.connect("changed", self.on_changed)
        self.entry.connect("activate", self.on_enter)
        box.append(self.entry)
        self.status = label("", "muted")
        box.append(self.status)
        self.list = Gtk.ListBox()
        self.list.connect("row-activated", self.on_row)
        box.append(scrolled(self.list))
        self.win.set_child(box)
        esc_closes(self.win)
        self.win.present()
        if self.initial:
            self.entry.set_text(self.initial)
            self.entry.set_position(-1)
        self.entry.grab_focus()

    def on_changed(self, _e) -> None:
        if self.pending:
            GLib.source_remove(self.pending)
        self.pending = GLib.timeout_add(DEBOUNCE_MS, self.run_search)

    def run_search(self) -> bool:
        self.pending = 0
        q = self.entry.get_text()
        self.generation += 1
        gen = self.generation
        if len(q.strip()) < 2:
            self.show({}, "")
            return False
        self.status.set_text("Searching…")
        run_bg(lambda: search.grouped(search.search(q)), lambda res: gen == self.generation and self.show(res, q))
        return False

    def show(self, groups, q: str) -> None:
        if isinstance(groups, Exception):
            self.status.set_text(f"Search failed: {groups}")
            return
        while (row := self.list.get_row_at_index(0)) is not None:
            self.list.remove(row)
        total = 0
        order = ["Apps", "Places", "Mesh", "Notes", "Files"]
        for src in sorted(groups, key=lambda s: (order.index(s) if s in order else 1, s)):
            head = Gtk.ListBoxRow(selectable=False, activatable=False)
            head.set_child(label(src.upper(), "group-header"))
            self.list.append(head)
            for r in groups[src]:
                row = Gtk.ListBoxRow()
                row.result = r
                b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                b.append(label(r.title))
                if r.subtitle:
                    b.append(label(r.subtitle, "subtitle"))
                row.set_child(b)
                self.list.append(row)
                total += 1
        self.status.set_text(f"{total} results" if q else "")

    def on_enter(self, _e) -> None:
        for i in range(200):
            row = self.list.get_row_at_index(i)
            if row is None:
                return
            if getattr(row, "result", None):
                self.on_row(self.list, row)
                return

    def on_row(self, _lb, row) -> None:
        r = getattr(row, "result", None)
        if r and r.command:
            spawn(r.command)
            self.win.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="deck-search")
    ap.add_argument("--query", default="")
    args = ap.parse_args(argv)
    return SearchApp(args.query).run(sys.argv[:1])


if __name__ == "__main__":
    sys.exit(main())
