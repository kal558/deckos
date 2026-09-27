"""deck-radio: preset-based receiver for the RTL-SDR.

Left: tabs grouped by section (Broadcast, Amateur, DX, Satellites).
Right: the selected tab's presets, bands to scan and controls.
Audio keeps playing if you switch to another app.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request

from ..radio import bands, pipelines, sdrlock
from ..radio.ft8 import spots_file
from ..radio.scan import find_peaks
from .common import GLib, Gtk, apply_theme, button, in_terminal, label, message, run_bg, scrolled, spawn, watch_theme

WELLE_PORT = 7979


def fmt_freq(hz: float) -> str:
    if hz >= 100e6:
        return f"{hz / 1e6:.3f} MHz"
    if hz >= 1e6:
        return f"{hz / 1e6:.4f} MHz"
    return f"{hz / 1e3:.0f} kHz"


class Player:
    """Owns the SDR lock and the running demodulator/playback processes."""

    def __init__(self) -> None:
        self.procs: list[subprocess.Popen] = []
        self.lock_cm = None
        self.what = ""

    def _acquire(self, name: str) -> None:
        if self.lock_cm is None:
            self.lock_cm = sdrlock.hold(name)
            try:
                self.lock_cm.__enter__()
            except sdrlock.Busy:
                self.lock_cm = None
                raise

    def stop(self) -> None:
        for p in self.procs:
            p.terminate()
        for p in self.procs:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
        self.procs = []
        if self.lock_cm is not None:
            self.lock_cm.__exit__(None, None, None)
            self.lock_cm = None
        self.what = ""

    def play_analog(self, mode: str, freq: float, gain: float | None) -> None:
        self.stop()
        self._acquire("Radio")
        pipe = pipelines.rtl_fm(mode, freq, gain, squelch=0)
        src = subprocess.Popen(pipe.source, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        out = subprocess.Popen(pipe.player(), stdin=src.stdout)
        src.stdout.close()
        self.procs = [src, out]
        self.what = fmt_freq(freq)

    def start_dab(self, channel: str) -> None:
        self.stop()
        self._acquire("Radio (DAB+)")
        self.procs = [subprocess.Popen(pipelines.welle_server(channel, WELLE_PORT),
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
        self.what = f"DAB {channel}"

    def play_dab_service(self, sid: str) -> None:
        # replace any running mpv, keep welle-cli
        for p in self.procs[1:]:
            p.terminate()
        self.procs = self.procs[:1] + [subprocess.Popen(
            ["mpv", "--no-video", "--really-quiet", f"http://127.0.0.1:{WELLE_PORT}/mp3/{sid}"])]

    def start_ft8(self, freq: float) -> None:
        self.stop()  # deck-ft8 takes the lock itself
        self.procs = [subprocess.Popen(["deck-ft8", "--freq", str(int(freq))])]
        self.what = f"FT8 {fmt_freq(freq)}"

    def scan(self, band: bands.Band) -> list[float]:
        self.stop()
        with sdrlock.hold("Radio (scan)"):
            out = subprocess.run(
                ["rtl_power", "-f", f"{int(band.start)}:{int(band.end)}:{int(max(band.step, 1e3))}",
                 "-i", "2", "-1", "-"], capture_output=True, text=True, timeout=180).stdout
        return find_peaks(out)


class RadioApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="org.deckos.Radio")
        self.win = None
        self.player = Player()
        self.gain: float | None = None

    def do_activate(self) -> None:
        if self.win:
            self.win.present()
            return
        apply_theme()
        watch_theme()
        self.tabs = bands.load_all()
        self.win = Gtk.ApplicationWindow(application=self, title="Radio")
        self.win.connect("close-request", lambda *_: self.player.stop() or False)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=8, margin_start=8, margin_end=8, margin_bottom=8)
        top = Gtk.Box(spacing=12)
        self.now = label("Stopped", "freq")
        self.now.set_hexpand(True)
        top.append(self.now)
        gain = Gtk.DropDown.new_from_strings(["Gain: auto", "Gain: 20", "Gain: 30", "Gain: 40", "Gain: 49"])
        gain.connect("notify::selected", self.on_gain)
        top.append(gain)
        top.append(button("■ Stop", self.stop))
        top.append(button("SDR++ (advanced)", lambda: spawn(["deck-sdr-lock", "run", "SDR++", "--", "sdr-advanced"])))
        root.append(top)

        stack = Gtk.Stack()
        side = Gtk.StackSidebar(stack=stack)
        side.set_size_request(220, -1)
        for tab in self.tabs:
            stack.add_titled(self.build_tab(tab), tab.id, f"{tab.section} · {tab.tab}")
        body = Gtk.Box(spacing=8, vexpand=True)
        body.append(side)
        body.append(stack)
        root.append(body)
        self.win.set_child(root)
        self.win.present()

    def on_gain(self, dd, _pspec) -> None:
        self.gain = [None, 20, 30, 40, 49][dd.get_selected()]

    def stop(self) -> None:
        self.player.stop()
        self.now.set_text("Stopped")

    def _guard(self, fn) -> None:
        try:
            fn()
            self.now.set_text(self.player.what or "Stopped")
        except sdrlock.Busy as e:
            message(self.win, f"{e}. Close it first.")
        except FileNotFoundError as e:
            message(self.win, f"Missing program: {e.filename}")

    # ---- tab builders
    def build_tab(self, tab: bands.Tab) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=8)
        if tab.note:
            box.append(label(tab.note, "dim", wrap=True))
        if tab.mode == "dab":
            return self.build_dab(tab, box)
        if tab.mode == "satellite":
            return self.build_sat(tab, box)
        lst = Gtk.ListBox()
        self.fill_presets(tab, lst)
        lst.connect("row-activated", lambda _l, row: self.activate_preset(tab, row.preset))
        box.append(scrolled(lst))
        if tab.bands:
            row = Gtk.Box(spacing=6)
            row.append(label("Scan:", "dim"))
            for b in tab.bands:
                row.append(button(b.name, lambda b=b: self.scan(tab, b, lst)))
            box.append(row)
        manual = Gtk.Box(spacing=6)
        entry = Gtk.Entry(placeholder_text="Frequency, e.g. 98.8M or 7110k")
        entry.connect("activate", lambda e: self.manual(tab, e.get_text()))
        manual.append(entry)
        box.append(manual)
        if tab.mode == "ft8":
            self.spots = Gtk.Label(xalign=0, css_classes=["log"])
            box.append(label("Recent spots (also on the map):", "dim"))
            box.append(scrolled(self.spots))
            GLib.timeout_add_seconds(15, self.refresh_spots)
        return box

    def fill_presets(self, tab: bands.Tab, lst: Gtk.ListBox) -> None:
        while (r := lst.get_row_at_index(0)) is not None:
            lst.remove(r)
        for p in tab.presets:
            row = Gtk.ListBoxRow()
            row.preset = p
            h = Gtk.Box(spacing=12)
            h.append(label(p.name))
            f = label(fmt_freq(p.freq), "dim", xalign=1.0)
            f.set_hexpand(True)
            h.append(f)
            row.set_child(h)
            lst.append(row)

    def activate_preset(self, tab: bands.Tab, p: bands.Preset) -> None:
        if tab.mode == "ft8":
            self._guard(lambda: self.player.start_ft8(p.freq))
        elif tab.mode == "app":
            self.stop()
            spawn(["deck-sdr-pipe", "--freq", str(int(p.freq + tab.dial_offset)), "--mode", tab.app_mode,
                   "--name", tab.tab, "--then", *tab.app])
            self.now.set_text(f"{tab.tab} {fmt_freq(p.freq)}")
        else:
            self._guard(lambda: self.player.play_analog(tab.mode, p.freq, self.gain))

    def manual(self, tab: bands.Tab, text: str) -> None:
        t = text.strip().lower().replace(" ", "")
        mult = 1e6 if t.endswith("m") else 1e3 if t.endswith("k") else (1e6 if "." in t else 1e3)
        try:
            f = float(t.rstrip("mkhz")) * mult
        except ValueError:
            message(self.win, "Couldn't read that frequency.")
            return
        if not bands.MIN_HZ <= f <= bands.MAX_HZ:
            message(self.win, "Outside the SDR's range (0.5–1766 MHz).")
            return
        self.activate_preset(tab, bands.Preset(fmt_freq(f), f))

    def scan(self, tab: bands.Tab, band: bands.Band, lst: Gtk.ListBox) -> None:
        self.now.set_text(f"Scanning {band.name}…")

        def done(res) -> None:
            if isinstance(res, Exception):
                message(self.win, f"Scan failed: {res}")
                self.now.set_text("Stopped")
                return
            for f in res:
                bands.save_preset(tab.id, bands.Preset(f"Found {fmt_freq(f)}", round(f / band.step) * band.step))
            tab.presets = [p for p in tab.presets if not p.name.startswith("Found")] + [
                p for p in bands.saved_presets(tab.id) if p.name.startswith("Found")]
            self.fill_presets(tab, lst)
            self.now.set_text(f"{len(res)} signals found")

        run_bg(lambda: self.player.scan(band), done)

    def refresh_spots(self) -> bool:
        try:
            spots = json.loads(spots_file().read_text())[:40]
        except (OSError, ValueError):
            spots = []
        self.spots.set_text("\n".join(
            f"{time.strftime('%H:%M', time.localtime(s['time']))}  {s['call']:10s} {s['grid']:6s} {s['snr']:+d} dB"
            for s in spots) or "No spots yet (decodes every 15 s).")
        return True

    def build_dab(self, tab: bands.Tab, box: Gtk.Box) -> Gtk.Widget:
        muxes = Gtk.ListBox()
        for p in tab.presets:
            row = Gtk.ListBoxRow()
            row.channel = p.channel
            row.set_child(label(f"{p.name} ({p.channel})"))
            muxes.append(row)
        for ch in tab.channels:
            if ch in {p.channel for p in tab.presets}:
                continue
            row = Gtk.ListBoxRow()
            row.channel = ch
            row.set_child(label(f"Channel {ch}", "dim"))
            muxes.append(row)
        services = Gtk.ListBox()
        services.connect("row-activated", lambda _l, row: self.player.play_dab_service(row.sid))

        def pick(_l, row) -> None:
            self._guard(lambda: self.player.start_dab(row.channel))
            self.now.set_text(f"DAB {row.channel}: tuning…")
            GLib.timeout_add_seconds(4, lambda: self.load_services(services))

        muxes.connect("row-activated", pick)
        pane = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True)
        pane.set_start_child(scrolled(muxes))
        pane.set_end_child(scrolled(services))
        pane.set_position(260)
        box.append(pane)
        return box

    def load_services(self, services: Gtk.ListBox, attempt: int = 0) -> bool:
        def fetch():
            with urllib.request.urlopen(f"http://127.0.0.1:{WELLE_PORT}/mux.json", timeout=3) as r:
                return json.load(r)

        def done(res) -> None:
            while (r := services.get_row_at_index(0)) is not None:
                services.remove(r)
            svcs = [] if isinstance(res, Exception) else res.get("services", [])
            for s in svcs:
                name = (s.get("label") or {}).get("label", "").strip() or s.get("sid", "?")
                row = Gtk.ListBoxRow()
                row.sid = s.get("sid")
                row.set_child(label(name))
                services.append(row)
            if not svcs and attempt < 5:
                GLib.timeout_add_seconds(3, lambda: self.load_services(services, attempt + 1))
            self.now.set_text(f"{self.player.what}: {len(svcs)} stations" if svcs else f"{self.player.what}: searching…")

        run_bg(fetch, done)
        return False

    def build_sat(self, tab: bands.Tab, box: Gtk.Box) -> Gtk.Widget:
        passes = label("", "log", wrap=True)
        passes.set_selectable(True)

        def load() -> None:
            def work():
                return subprocess.run(["deck-sat", "passes"], capture_output=True, text=True, timeout=60)

            run_bg(work, lambda r: passes.set_text(
                str(r) if isinstance(r, Exception) else (r.stdout or r.stderr or "No good passes in the next 24 h")))

        row = Gtk.Box(spacing=6)
        row.append(button("Show passes", load))
        row.append(button("Update orbit data (online)", lambda: in_terminal(["deck-sat", "update-tle"])))
        for s in tab.satellites:
            row.append(button(f"Record next {s.name}", lambda s=s: (self.stop(), in_terminal(["deck-sat", "record", s.name]))))
        box.append(row)
        box.append(scrolled(passes))
        load()
        return box


def main(argv: list[str] | None = None) -> int:
    return RadioApp().run(sys.argv[:1])


if __name__ == "__main__":
    sys.exit(main())
