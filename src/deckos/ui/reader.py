"""deck-reader: one offline reader for the library (kiwix-serve) and the map app.

Single process with tabs; running it again opens a tab in the existing window.
It only loads pages from this deck (127.0.0.1). External links are blocked and
can be handed to Firefox on request, so reading never touches the network.

    deck-reader --open wikipedia|medical|practical|reference|library|maps|bookmarks
    deck-reader --url http://127.0.0.1:8080/...

Keys: Ctrl+T new tab · Ctrl+W close · Ctrl+Tab next · Alt+←/→ back/forward
      Ctrl+F find · Ctrl+D bookmark · Ctrl+L read later · Ctrl+B bookmarks · Ctrl+±/0 zoom
"""
from __future__ import annotations

import argparse
import html
import json
import sys
import time
import urllib.parse

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")
from gi.repository import Gio, WebKit  # noqa: E402

from .. import paths  # noqa: E402
from ..library import catalog, store  # noqa: E402
from .common import Gdk, GLib, Gtk, apply_theme, label, spawn, theme_mode  # noqa: E402

KIWIX = "http://127.0.0.1:8080"
MAPS = "http://127.0.0.1:8090/"
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
GROUP_FOR_TARGET = {"medical": "Medical", "practical": "Practical", "reference": "Reference"}

NIGHT_CSS = """
html { filter: invert(0.9) hue-rotate(180deg) sepia(0.35) saturate(1.4) !important; background: #fff !important; }
img, video, picture, canvas, svg image, .mwe-math-fallback-image-inline { filter: invert(1) hue-rotate(180deg) !important; }
"""


# ---- bookmarks ------------------------------------------------------------------

def _bm_file():
    return paths.user_state() / "bookmarks.json"


def load_bookmarks() -> dict[str, list[dict]]:
    try:
        d = json.loads(_bm_file().read_text())
        return {"bookmarks": d.get("bookmarks", []), "later": d.get("later", [])}
    except (OSError, ValueError):
        return {"bookmarks": [], "later": []}


def add_bookmark(kind: str, title: str, url: str) -> None:
    d = load_bookmarks()
    d[kind] = [b for b in d[kind] if b["url"] != url]
    d[kind].insert(0, {"title": title or url, "url": url, "time": time.time()})
    _bm_file().write_text(json.dumps(d, indent=1))


# ---- generated pages ----------------------------------------------------------------

def _page(title: str, body: str) -> str:
    night = theme_mode() != "day"
    bg, fg, dim = ("#0b0906", "#ffb000", "#b07a00") if night else ("#fff", "#000", "#333")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>body{{background:{bg};color:{fg};font:16px/1.5 "DejaVu Sans Mono",monospace;margin:2em 3em}}
a{{color:{fg}}} h1{{letter-spacing:.08em}} .d{{color:{dim}}} li{{margin:.5em 0}}</style></head>
<body><h1>{html.escape(title)}</h1>{body}</body></html>"""


def group_index(group: str) -> str:
    items = [i for i in catalog.load() if i.kind == "zim" and i.group == group]
    zims = store.installed_zims()
    rows, missing = [], []
    for it in items:
        z = zims.get(it.name)
        if z:
            rows.append(f'<li><a href="{KIWIX}/content/{urllib.parse.quote(z.path.stem)}/">{html.escape(it.title)}</a>'
                        f' <span class="d">({z.date})</span></li>')
        else:
            missing.append(html.escape(it.title))
    body = f"<ul>{''.join(rows)}</ul>" if rows else "<p>Nothing installed yet.</p>"
    if missing:
        body += f'<p class="d">Not installed: {", ".join(missing)}. Open <b>Library</b> to download.</p>'
    return _page(group, body)


def bookmarks_page() -> str:
    d = load_bookmarks()

    def lst(items):
        if not items:
            return '<p class="d">None yet.</p>'
        return "<ul>" + "".join(f'<li><a href="{html.escape(b["url"])}">{html.escape(b["title"])}</a></li>'
                                for b in items) + "</ul>"

    return _page("Bookmarks", "<h2>Read later</h2>" + lst(d["later"]) + "<h2>Bookmarks</h2>" + lst(d["bookmarks"]))


def wikipedia_url() -> str | None:
    zims = store.installed_zims()
    for name in ("wikipedia_en_all_maxi", "wikipedia_en_all_nopic", "wikipedia_en_all_mini"):
        if name in zims:
            return f"{KIWIX}/content/{urllib.parse.quote(zims[name].path.stem)}/"
    return None


def is_local(uri: str) -> bool:
    u = urllib.parse.urlparse(uri)
    return u.scheme in ("about", "data", "blob") or (u.scheme in ("http", "https") and u.hostname in LOCAL_HOSTS)


# ---- window ------------------------------------------------------------------------------

class Reader(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="org.deckos.Reader", flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.win = None
        self.session = None
        self.ucm_css = None

    # command line from this or a later invocation
    def do_command_line(self, cmdline) -> int:
        ap = argparse.ArgumentParser(prog="deck-reader", add_help=False)
        ap.add_argument("--open", default="library")
        ap.add_argument("--url")
        args, _ = ap.parse_known_args(cmdline.get_arguments()[1:])
        self.ensure_window()
        if args.url:
            self.new_tab(args.url)
        else:
            self.open_target(args.open)
        self.win.present()
        return 0

    def ensure_window(self) -> None:
        if self.win:
            return
        apply_theme()
        self.session = WebKit.NetworkSession.new_ephemeral()
        self.win = Gtk.ApplicationWindow(application=self, title="Reader")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar = Gtk.Box(spacing=6, margin_top=4, margin_bottom=4, margin_start=6, margin_end=6)
        for text, fn in (("◀", lambda: self.view() and self.view().go_back()),
                         ("▶", lambda: self.view() and self.view().go_forward()),
                         ("⌂", lambda: self.open_target("library")),
                         ("★", lambda: self.bookmark("bookmarks")),
                         ("☰", lambda: self.open_target("bookmarks"))):
            b = Gtk.Button(label=text)
            b.connect("clicked", lambda *_, f=fn: f())
            bar.append(b)
        self.url_label = label("", "muted")
        self.url_label.set_hexpand(True)
        self.url_label.set_ellipsize(3)
        bar.append(self.url_label)
        box.append(bar)

        self.find_bar = Gtk.SearchBar()
        self.find_entry = Gtk.SearchEntry()
        self.find_entry.connect("search-changed", self.on_find)
        self.find_entry.connect("activate", lambda *_: self.view() and self.view().get_find_controller().search_next())
        self.find_bar.set_child(self.find_entry)
        self.find_bar.connect_entry(self.find_entry)
        box.append(self.find_bar)

        self.info = Gtk.InfoBar(revealed=False, show_close_button=True)
        self.info_label = label("")
        self.info.add_child(self.info_label)
        self.info_btn = Gtk.Button(label="Open in Firefox")
        self.info.add_action_widget(self.info_btn, 1)
        self.info.connect("response", self.on_info)
        self.blocked_uri = ""
        box.append(self.info)

        self.nb = Gtk.Notebook(scrollable=True, vexpand=True)
        self.nb.connect("switch-page", lambda *_: GLib.idle_add(self.sync_url))
        box.append(self.nb)
        self.win.set_child(box)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key)
        self.win.add_controller(keys)

    def make_view(self) -> WebKit.WebView:
        ucm = WebKit.UserContentManager()
        if theme_mode() != "day":
            ucm.add_style_sheet(WebKit.UserStyleSheet.new(
                NIGHT_CSS, WebKit.UserContentInjectedFrames.ALL_FRAMES, WebKit.UserStyleLevel.USER,
                [f"{KIWIX}/*"], None))
        view = WebKit.WebView(network_session=self.session, user_content_manager=ucm)
        s = view.get_settings()
        s.set_enable_webgl(True)
        s.set_enable_developer_extras(False)
        s.set_enable_back_forward_navigation_gestures(True)
        s.set_default_font_size(17)
        view.connect("decide-policy", self.on_policy)
        view.connect("notify::title", lambda v, *_: self.retitle(v))
        view.connect("notify::uri", lambda *_: self.sync_url())
        view.connect("create", self.on_create)
        return view

    def new_tab(self, uri: str | None = None, html_text: str | None = None, base: str = KIWIX + "/") -> WebKit.WebView:
        view = self.make_view()
        tab_label = label("…")
        tab_label.set_max_width_chars(22)
        tab_label.set_ellipsize(3)
        view.tab_label = tab_label
        idx = self.nb.append_page(view, tab_label)
        self.nb.set_tab_reorderable(view, True)
        if html_text is not None:
            view.load_html(html_text, base)
        elif uri:
            view.load_uri(uri)
        self.nb.set_current_page(idx)
        view.grab_focus()
        return view

    def open_target(self, target: str) -> None:
        if target == "wikipedia":
            url = wikipedia_url()
            if url:
                self.new_tab(url)
            else:
                self.new_tab(html_text=_page("Wikipedia", "<p>Wikipedia isn't installed. Open <b>Library</b> to download it.</p>"))
        elif target in GROUP_FOR_TARGET:
            self.new_tab(html_text=group_index(GROUP_FOR_TARGET[target]))
        elif target == "maps":
            self.new_tab(MAPS)
        elif target == "bookmarks":
            self.new_tab(html_text=bookmarks_page())
        else:
            self.new_tab(KIWIX + "/")

    def view(self) -> WebKit.WebView | None:
        page = self.nb.get_current_page()
        return self.nb.get_nth_page(page) if page >= 0 else None

    def retitle(self, view: WebKit.WebView) -> None:
        view.tab_label.set_text(view.get_title() or "…")

    def sync_url(self) -> bool:
        v = self.view()
        self.url_label.set_text(urllib.parse.unquote(v.get_uri() or "") if v else "")
        return False

    # ---- policies
    def on_policy(self, view, decision, kind) -> bool:
        if kind in (WebKit.PolicyDecisionType.NAVIGATION_ACTION, WebKit.PolicyDecisionType.NEW_WINDOW_ACTION):
            uri = decision.get_navigation_action().get_request().get_uri()
            if not is_local(uri):
                decision.ignore()
                self.blocked_uri = uri
                host = urllib.parse.urlparse(uri).hostname or uri
                self.info_label.set_text(f"The reader is offline-only. Blocked a link to {host}.")
                self.info.set_revealed(True)
                return True
            if kind == WebKit.PolicyDecisionType.NEW_WINDOW_ACTION:
                decision.ignore()
                self.new_tab(uri)
                return True
        return False

    def on_create(self, _view, action):
        uri = action.get_request().get_uri()
        if is_local(uri):
            self.new_tab(uri)
        return None

    def on_info(self, bar, response) -> None:
        if response == 1 and self.blocked_uri:
            spawn(["deck-launch", "browser", self.blocked_uri])
        bar.set_revealed(False)

    def on_find(self, entry) -> None:
        v = self.view()
        if v:
            v.get_find_controller().search(entry.get_text(), WebKit.FindOptions.CASE_INSENSITIVE | WebKit.FindOptions.WRAP_AROUND, 500)

    def bookmark(self, kind: str) -> None:
        v = self.view()
        if v and v.get_uri() and v.get_uri().startswith("http"):
            add_bookmark(kind, v.get_title() or "", v.get_uri())
            self.info_label.set_text("Saved to " + ("Read later" if kind == "later" else "Bookmarks"))
            self.blocked_uri = ""
            self.info.set_revealed(True)
            GLib.timeout_add_seconds(2, lambda: self.info.set_revealed(False) or False)

    def on_key(self, _c, keyval, _code, state) -> bool:
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        alt = bool(state & Gdk.ModifierType.ALT_MASK)
        v = self.view()
        if ctrl and keyval == Gdk.KEY_t:
            self.open_target("library")
        elif ctrl and keyval == Gdk.KEY_w:
            if v:
                self.nb.remove_page(self.nb.get_current_page())
            if self.nb.get_n_pages() == 0:
                self.win.close()
        elif ctrl and keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            n = self.nb.get_n_pages()
            if n:
                step = -1 if state & Gdk.ModifierType.SHIFT_MASK else 1
                self.nb.set_current_page((self.nb.get_current_page() + step) % n)
        elif ctrl and keyval == Gdk.KEY_f:
            self.find_bar.set_search_mode(True)
            self.find_entry.grab_focus()
        elif ctrl and keyval == Gdk.KEY_d:
            self.bookmark("bookmarks")
        elif ctrl and keyval == Gdk.KEY_l:
            self.bookmark("later")
        elif ctrl and keyval == Gdk.KEY_b:
            self.open_target("bookmarks")
        elif ctrl and keyval in (Gdk.KEY_plus, Gdk.KEY_equal) and v:
            v.set_zoom_level(min(3.0, v.get_zoom_level() + 0.1))
        elif ctrl and keyval == Gdk.KEY_minus and v:
            v.set_zoom_level(max(0.5, v.get_zoom_level() - 0.1))
        elif ctrl and keyval == Gdk.KEY_0 and v:
            v.set_zoom_level(1.0)
        elif alt and keyval == Gdk.KEY_Left and v:
            v.go_back()
        elif alt and keyval == Gdk.KEY_Right and v:
            v.go_forward()
        elif keyval == Gdk.KEY_Escape and self.find_bar.get_search_mode():
            self.find_bar.set_search_mode(False)
        else:
            return False
        return True


def main(argv: list[str] | None = None) -> int:
    return Reader().run(sys.argv if argv is None else ["deck-reader", *argv])


if __name__ == "__main__":
    sys.exit(main())
