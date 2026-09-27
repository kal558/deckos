"""deck-mesh: Meshtastic conversations, nodes and EMCON controls (talks to meshd)."""
from __future__ import annotations

import sys
import time

from ..mesh import client
from ..mesh.policy import PRECISION_CHOICES
from .common import GLib, Gtk, apply_theme, button, label, message, run_bg, scrolled, watch_theme

POLL_S = 3


def ago(ts: float | None) -> str:
    if not ts:
        return "never"
    d = time.time() - ts
    if d < 90:
        return "just now"
    if d < 5400:
        return f"{d / 60:.0f} min ago"
    if d < 172800:
        return f"{d / 3600:.0f} h ago"
    return f"{d / 86400:.0f} days ago"


def call(req: dict, timeout: float = 5.0) -> dict:
    return client.request(req, timeout)


class MeshApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="org.deckos.Mesh")
        self.win = None
        self.peer = "#0"
        self.names: dict[str, str] = {}
        self.me = ""

    def do_activate(self) -> None:
        if self.win:
            self.win.present()
            return
        apply_theme()
        watch_theme()
        self.win = Gtk.ApplicationWindow(application=self, title="Mesh")
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=8, margin_start=8,
                       margin_end=8, margin_bottom=8)

        # EMCON strip
        strip = Gtk.Box(spacing=10)
        self.state_lbl = label("", "silent")
        self.state_lbl.set_hexpand(True)
        strip.append(self.state_lbl)
        strip.append(label("Transmit", "dim"))
        self.tx = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.tx_handler = self.tx.connect("state-set", self.on_tx)
        strip.append(self.tx)
        strip.append(label("Share position", "dim"))
        self.pos = Gtk.DropDown.new_from_strings(list(PRECISION_CHOICES.values()))
        self.pos_handler = self.pos.connect("notify::selected", self.on_pos)
        strip.append(self.pos)
        strip.append(button("Channel key…", self.channel_dialog))
        root.append(strip)
        self.warn = label("Transmitting. Messages are encrypted, but anyone with direction-finding gear can locate "
                          "an active transmitter.", wrap=True)
        box = Gtk.Box()
        box.add_css_class("warning-box")
        box.append(self.warn)
        self.warn_box = box
        box.set_visible(False)
        root.append(box)

        body = Gtk.Paned(vexpand=True)
        left = Gtk.Notebook()
        self.convs = Gtk.ListBox()
        self.convs.connect("row-activated", lambda _l, r: self.open_peer(r.peer))
        left.append_page(scrolled(self.convs), label("Chats"))
        self.nodes = Gtk.ListBox()
        self.nodes.connect("row-activated", lambda _l, r: self.open_peer(r.peer))
        left.append_page(scrolled(self.nodes), label("Nodes"))
        body.set_start_child(left)
        body.set_position(300)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.title = label("", "title")
        right.append(self.title)
        self.msgs = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.msg_scroll = scrolled(self.msgs)
        right.append(self.msg_scroll)
        send = Gtk.Box(spacing=6)
        self.entry = Gtk.Entry(hexpand=True, max_length=200, placeholder_text="Message (receive-only until Transmit is on)")
        self.entry.connect("activate", lambda *_: self.send())
        send.append(self.entry)
        send.append(button("Send", self.send, "suggested-action"))
        right.append(send)
        body.set_end_child(right)
        root.append(body)
        self.win.set_child(root)
        self.win.present()
        self.refresh()
        GLib.timeout_add_seconds(POLL_S, self.refresh)

    # ---- data
    def refresh(self) -> bool:
        if not self.win.is_active() and self.me:
            return True

        def work():
            st = call({"cmd": "status"})
            convs = call({"cmd": "conversations"})["conversations"]
            nodes = call({"cmd": "nodes"})["nodes"]
            msgs = call({"cmd": "messages", "peer": self.peer})["messages"]
            return st, convs, nodes, msgs

        run_bg(work, self.render)
        return True

    def render(self, res) -> None:
        if isinstance(res, Exception):
            self.state_lbl.set_text(f"Mesh service unavailable: {res}")
            return
        st, convs, nodes, msgs = res
        self.me = st.get("me", "")
        self.names = {n["id"]: n.get("long_name") or n["id"] for n in nodes}
        if not st["connected"]:
            txt = "Mesh radio not connected"
        else:
            txt = f"{st['node_name']} · " + ("TRANSMIT ON" if st["tx_enabled"] else "receive only")
        if not st.get("persistent"):
            txt += " · personal storage locked: messages not saved"
        self.state_lbl.set_text(txt)
        for cls in ("silent", "transmitting"):
            self.state_lbl.remove_css_class(cls)
        self.state_lbl.add_css_class("transmitting" if st["tx_enabled"] else "silent")
        self.warn_box.set_visible(bool(st["policy_tx"]))
        self.tx.handler_block(self.tx_handler)
        self.tx.set_active(bool(st["policy_tx"]))
        self.tx.handler_unblock(self.tx_handler)
        keys = list(PRECISION_CHOICES)
        sel = keys.index(st["precision_bits"]) if st["share_position"] and st["precision_bits"] in keys else 0
        self.pos.handler_block(self.pos_handler)
        self.pos.set_selected(sel)
        self.pos.handler_unblock(self.pos_handler)

        self._fill(self.convs, [("#0", "Primary channel", "")] + [
            (c["peer"], self.names.get(c["peer"], c["peer"]) if not c["peer"].startswith("#") else f"Channel {c['peer'][1:]}",
             f"{c['unread']} new" if c["unread"] else "") for c in convs if c["peer"] != "#0"])
        self._fill(self.nodes, [(n["id"], n.get("long_name") or n["id"],
                                 f"heard {ago(n.get('last_heard'))}" + (f" · SNR {n['snr']:.1f}" if n.get("snr") is not None else ""))
                                for n in nodes if n["id"] != self.me])
        self.title.set_text(self.names.get(self.peer, "Primary channel" if self.peer == "#0" else self.peer))
        self._render_msgs(msgs)

    def _fill(self, lb: Gtk.ListBox, rows: list[tuple[str, str, str]]) -> None:
        while (r := lb.get_row_at_index(0)) is not None:
            lb.remove(r)
        for peer, name, sub in rows:
            row = Gtk.ListBoxRow()
            row.peer = peer
            b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            b.append(label(name))
            if sub:
                b.append(label(sub, "subtitle"))
            row.set_child(b)
            lb.append(row)

    def _render_msgs(self, msgs: list[dict]) -> None:
        while (c := self.msgs.get_first_child()) is not None:
            self.msgs.remove(c)
        for m in msgs:
            who = "me" if m["direction"] == "out" else self.names.get(m["from_id"], m["from_id"])
            t = time.strftime("%H:%M", time.localtime(m["ts"]))
            line = label(f"{t}  {who}: {m['text']}", wrap=True, xalign=1.0 if m["direction"] == "out" else 0.0)
            line.set_selectable(True)
            self.msgs.append(line)
        adj = self.msg_scroll.get_vadjustment()
        GLib.idle_add(lambda: adj.set_value(adj.get_upper()) or False)
        run_bg(lambda: call({"cmd": "mark_read", "peer": self.peer}))

    def open_peer(self, peer: str) -> None:
        self.peer = peer
        self.refresh()

    # ---- actions
    def send(self) -> None:
        text = self.entry.get_text().strip()
        if not text:
            return
        to = "^all" if self.peer.startswith("#") else self.peer
        ch = int(self.peer[1:]) if self.peer.startswith("#") else 0

        def done(res) -> None:
            if isinstance(res, Exception):
                message(self.win, str(res))
            else:
                self.entry.set_text("")
                self.refresh()

        run_bg(lambda: call({"cmd": "send", "text": text, "to": to, "channel": ch}, 15), done)

    def on_tx(self, _sw, state: bool) -> bool:
        run_bg(lambda: call({"cmd": "set_tx", "enabled": state}, 20), lambda _r: self.refresh())
        return False

    def on_pos(self, dd, _p) -> None:
        bits = list(PRECISION_CHOICES)[dd.get_selected()]
        run_bg(lambda: call({"cmd": "set_position", "enabled": bits != 0, **({"precision_bits": bits} if bits else {})}, 20),
               lambda _r: self.refresh())

    def channel_dialog(self) -> None:
        try:
            ch = call({"cmd": "get_channel"})
        except (OSError, client.MeshdError) as e:
            message(self.win, str(e))
            return
        win = Gtk.Window(transient_for=self.win, modal=True, title="Channel key")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=16, margin_bottom=16,
                      margin_start=16, margin_end=16)
        box.append(label("Everyone in your group needs the same channel name and key. Share them in person, "
                         "never over the radio.", wrap=True))
        name = Gtk.Entry(text=ch["name"], max_length=11)
        key = Gtk.Entry(text=ch["psk_b64"])
        box.append(label("Channel name", "dim"))
        box.append(name)
        box.append(label("Key (base64)", "dim"))
        box.append(key)
        row = Gtk.Box(spacing=6, halign=Gtk.Align.END)

        def new_key() -> None:
            key.set_text(call({"cmd": "new_channel_key"})["psk_b64"])

        def save() -> None:
            try:
                call({"cmd": "set_channel", "name": name.get_text(), "psk_b64": key.get_text().strip()}, 20)
                win.close()
            except (OSError, client.MeshdError) as e:
                message(win, str(e))

        row.append(button("Generate new key", new_key))
        row.append(button("Cancel", win.close))
        row.append(button("Save", save, "suggested-action"))
        box.append(row)
        win.set_child(box)
        win.present()


def main(argv: list[str] | None = None) -> int:
    return MeshApp().run(sys.argv[:1])


if __name__ == "__main__":
    sys.exit(main())
