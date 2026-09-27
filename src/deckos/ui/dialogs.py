"""Standalone yes/no prompt used by deck-launch (the heavy-app rule)."""
from __future__ import annotations

from .common import Gtk, apply_theme


def ask_yes_no(question: str, yes: str = "Close it", no: str = "Cancel") -> bool:
    result = {"yes": False}
    app = Gtk.Application(application_id="org.deckos.Prompt")

    def on_activate(a: Gtk.Application) -> None:
        apply_theme()
        win = Gtk.ApplicationWindow(application=a, title="deckOS")
        win.set_default_size(460, 180)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, margin_top=20, margin_bottom=20,
                      margin_start=20, margin_end=20)
        lab = Gtk.Label(label=question, wrap=True, xalign=0)
        box.append(lab)
        row = Gtk.Box(spacing=10, halign=Gtk.Align.END)
        b_no = Gtk.Button(label=no)
        b_yes = Gtk.Button(label=yes)
        b_yes.add_css_class("suggested-action")

        def choose(v: bool) -> None:
            result["yes"] = v
            win.close()

        b_no.connect("clicked", lambda *_: choose(False))
        b_yes.connect("clicked", lambda *_: choose(True))
        row.append(b_no)
        row.append(b_yes)
        box.append(row)
        win.set_child(box)
        win.set_default_widget(b_yes)
        win.present()
        b_yes.grab_focus()

    app.connect("activate", on_activate)
    app.run([])
    return result["yes"]
