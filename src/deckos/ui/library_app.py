"""deck-library-ui: see what's installed, download or update content, import from a PC."""
from __future__ import annotations

import json
import subprocess
import sys
import threading

from .common import GLib, Gtk, apply_theme, button, in_terminal, label, message, scrolled, spawn, watch_theme


def gb(n: int) -> str:
    return f"{n / 1e9:.1f} GB"


class LibraryApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="org.deckos.Library")
        self.win = None
        self.checks: dict[str, Gtk.CheckButton] = {}
        self.proc: subprocess.Popen | None = None

    def do_activate(self) -> None:
        if self.win:
            self.win.present()
            return
        apply_theme()
        watch_theme()
        self.win = Gtk.ApplicationWindow(application=self, title="Library")
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=12, margin_start=16,
                       margin_end=16, margin_bottom=12)
        self.summary = label("", "title")
        root.append(self.summary)
        root.append(label("Downloads need Wi-Fi on (⊞+E). Files come only from the official Kiwix mirrors "
                          "(checksum-verified) and the Protomaps map builds.", "dim", wrap=True))
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        pane = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        pane.set_start_child(scrolled(self.list))
        self.log = Gtk.TextView(editable=False, monospace=True, cursor_visible=False)
        self.log.add_css_class("log")
        pane.set_end_child(scrolled(self.log))
        pane.set_position(420)
        root.append(pane)
        row = Gtk.Box(spacing=6)
        row.append(button("Download selected", self.install_selected, "suggested-action"))
        row.append(button("Update installed", lambda: self.run_cli(["update"])))
        row.append(button("Import from staging folder", lambda: self.run_cli(["import"])))
        row.append(button("PC import share on", lambda: in_terminal(["deck-library", "share", "on"])))
        row.append(button("Share off", lambda: in_terminal(["deck-library", "share", "off"], hold=False)))
        row.append(button("Stop", self.stop))
        root.append(row)
        self.win.set_child(root)
        self.win.present()
        self.reload()

    def reload(self) -> None:
        r = subprocess.run(["deck-library", "status", "--json"], capture_output=True, text=True)
        try:
            data = json.loads(r.stdout)
        except ValueError:
            self.summary.set_text("Library status unavailable")
            return
        if not data["ssd"]:
            self.summary.set_text("SSD not connected")
        else:
            n = sum(1 for i in data["items"] if i["installed"])
            self.summary.set_text(f"{n} installed · {gb(data['free'])} free")
        while (c := self.list.get_first_child()) is not None:
            self.list.remove(c)
        self.checks.clear()
        group = None
        for it in data["items"]:
            if it["group"] != group:
                group = it["group"]
                self.list.append(label(group.upper(), "group-header"))
            line = Gtk.Box(spacing=10)
            cb = Gtk.CheckButton(active=it["default"] and not it["installed"])
            self.checks[it["id"]] = cb
            line.append(cb)
            t = label(it["title"])
            t.set_hexpand(True)
            line.append(t)
            if it["installed"]:
                age = it["age_months"]
                state = f"installed {it['date']}" + (f" ({age} mo old)" if age else "")
            else:
                state = "not installed" if it["kind"] != "prebuilt" else "build on PC"
            line.append(label(state, "dim"))
            line.append(label(gb(it["size_bytes"]), "muted"))
            self.list.append(line)

    def append_log(self, text: str) -> bool:
        buf = self.log.get_buffer()
        buf.insert(buf.get_end_iter(), text)
        self.log.scroll_to_iter(buf.get_end_iter(), 0, False, 0, 0)
        return False

    def run_cli(self, args: list[str]) -> None:
        if self.proc and self.proc.poll() is None:
            message(self.win, "A download is already running.")
            return
        self.proc = subprocess.Popen(["deck-library", *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, bufsize=1)

        def pump(p: subprocess.Popen) -> None:
            for line in p.stdout:
                GLib.idle_add(self.append_log, line)
            p.wait()
            GLib.idle_add(self.append_log, f"— finished (exit {p.returncode})\n")
            GLib.idle_add(lambda: self.reload() or False)

        threading.Thread(target=pump, args=(self.proc,), daemon=True).start()

    def install_selected(self) -> None:
        ids = [i for i, cb in self.checks.items() if cb.get_active()]
        if not ids:
            message(self.win, "Tick the items you want first.")
            return
        self.run_cli(["install", *ids])

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.append_log("— stopped; downloads resume where they left off\n")


def main(argv: list[str] | None = None) -> int:
    return LibraryApp().run(sys.argv[:1])


if __name__ == "__main__":
    sys.exit(main())
