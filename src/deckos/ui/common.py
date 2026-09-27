"""Shared GTK plumbing: theme loading, window setup, background tasks."""
from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from .. import paths  # noqa: E402

HERE = Path(__file__).parent
_providers: list[Gtk.CssProvider] = []


def theme_mode() -> str:
    try:
        return (paths.user_state() / "theme").read_text().strip() or "night"
    except OSError:
        return "night"


def set_theme_mode(mode: str) -> None:
    (paths.user_state() / "theme").write_text(mode)


def apply_theme() -> None:
    display = Gdk.Display.get_default()
    if display is None:
        return
    for p in _providers:
        Gtk.StyleContext.remove_provider_for_display(display, p)
    _providers.clear()
    files = [HERE / "deck.css"]
    if theme_mode() == "day":
        files.append(HERE / "deck-day.css")
    for i, f in enumerate(files):
        prov = Gtk.CssProvider()
        prov.load_from_path(str(f))
        Gtk.StyleContext.add_provider_for_display(display, prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + i)
        _providers.append(prov)
    settings = Gtk.Settings.get_default()
    if settings:
        settings.set_property("gtk-application-prefer-dark-theme", theme_mode() != "day")


def watch_theme(interval_s: int = 2) -> None:
    """Re-apply the theme when ⊞+D flips it (the file changes)."""
    state = {"mode": theme_mode()}

    def tick() -> bool:
        m = theme_mode()
        if m != state["mode"]:
            state["mode"] = m
            apply_theme()
        return True

    GLib.timeout_add_seconds(interval_s, tick)


def run_bg(fn: Callable, done: Callable | None = None) -> None:
    """Run fn in a thread; call done(result_or_exception) on the GTK main loop."""
    def worker() -> None:
        try:
            res = fn()
        except Exception as e:  # noqa: BLE001 - handed to the UI
            res = e
        if done:
            GLib.idle_add(done, res)

    threading.Thread(target=worker, daemon=True).start()


def spawn(cmd: list[str] | tuple[str, ...]) -> None:
    subprocess.Popen(list(cmd), start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def in_terminal(cmd: list[str], hold: bool = True) -> None:
    """Run a command in a terminal window (for setup tasks that ask questions)."""
    spawn(["foot", "--app-id=deckos-terminal", *(["--hold"] if hold else []), *cmd])


def esc_closes(win: Gtk.Window) -> None:
    ctl = Gtk.EventControllerKey()

    def on_key(_c, keyval, _code, _state) -> bool:
        if keyval == Gdk.KEY_Escape:
            win.close()
            return True
        return False

    ctl.connect("key-pressed", on_key)
    win.add_controller(ctl)


def label(text: str = "", *classes: str, xalign: float = 0.0, wrap: bool = False) -> Gtk.Label:
    lab = Gtk.Label(label=text, xalign=xalign)
    lab.set_wrap(wrap)
    for c in classes:
        lab.add_css_class(c)
    return lab


def button(text: str, on_click: Callable, *classes: str) -> Gtk.Button:
    b = Gtk.Button(label=text)
    for c in classes:
        b.add_css_class(c)
    b.connect("clicked", lambda *_: on_click())
    return b


def scrolled(child: Gtk.Widget) -> Gtk.ScrolledWindow:
    sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
    sw.set_child(child)
    return sw


def message(parent: Gtk.Window | None, text: str) -> None:
    dlg = Gtk.AlertDialog(message=text)
    dlg.show(parent)
