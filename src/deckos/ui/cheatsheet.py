"""deck-cheatsheet (F1 / ⊞+F1): every key on one screen."""
from __future__ import annotations

import sys

from .common import Gtk, apply_theme, esc_closes, label

KEYS = [
    ("Everywhere", [
        ("⊞  (tap)", "Ctrl+Alt+Space", "Home"),
        ("⊞+Space", "Ctrl+Alt+S", "Search everything"),
        ("⊞+Tab", "Alt+Tab", "Next app"),
        ("⊞+Q", "Ctrl+Alt+Q", "Close app"),
        ("⊞+Esc", "Ctrl+Alt+Del", "Power menu"),
        ("⊞+E", "Ctrl+Alt+E", "Emissions control"),
        ("⊞+Shift+E", "Ctrl+Alt+Shift+E", "Go silent (all transmitters off)"),
        ("⊞+D", "Ctrl+Alt+D", "Day / night theme"),
        ("⊞+Enter", "Ctrl+Alt+T", "Terminal"),
        ("F1", "⊞+F1", "This sheet"),
    ]),
    ("Reader (Wikipedia, library, maps)", [
        ("Ctrl+T / Ctrl+W", "", "New / close tab"),
        ("Ctrl+Tab", "", "Next tab"),
        ("Alt+← / Alt+→", "", "Back / forward"),
        ("Ctrl+F", "", "Find in page"),
        ("Ctrl+D / Ctrl+L", "", "Bookmark / read later"),
        ("Ctrl+B", "", "Bookmarks"),
        ("Ctrl+ + / − / 0", "", "Zoom"),
    ]),
    ("Home screen", [
        ("Arrows + Enter", "", "Open a tile"),
        ("Just type", "", "Search"),
    ]),
]


class Sheet(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="org.deckos.Cheatsheet")

    def do_activate(self) -> None:
        apply_theme()
        win = Gtk.ApplicationWindow(application=self, title="Keys")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=24, margin_bottom=24,
                      margin_start=32, margin_end=32)
        box.append(label("Keys  ·  Esc to close", "title"))
        for section, rows in KEYS:
            box.append(label(section.upper(), "group-header"))
            grid = Gtk.Grid(column_spacing=24, row_spacing=4)
            for i, (k, alt, what) in enumerate(rows):
                grid.attach(label(k), 0, i, 1, 1)
                grid.attach(label(alt, "muted"), 1, i, 1, 1)
                grid.attach(label(what, "dim"), 2, i, 1, 1)
            box.append(grid)
        sw = Gtk.ScrolledWindow(vexpand=True)
        sw.set_child(box)
        win.set_child(sw)
        esc_closes(win)
        win.present()


def main(argv: list[str] | None = None) -> int:
    return Sheet().run(sys.argv[:1])


if __name__ == "__main__":
    sys.exit(main())
