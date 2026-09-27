"""meshd: sole owner of the Meshtastic node.

- Connects to /dev/meshtastic (udev symlink) and reconnects when it's replugged.
- On every connect, applies the EMCON policy (receive-only by default, private
  channel, blurred or no position, random node name).
- Stores messages/nodes/waypoints in personal storage (RAM-only if locked).
- Serves other apps over /run/deckos/meshd.sock (see client.py).
"""
from __future__ import annotations

import json
import logging
import os
import socketserver
import sys
import threading
import time
from pathlib import Path

from .. import paths
from . import policy as pol_mod
from .store import BROADCAST, Store

log = logging.getLogger("meshd")
DEVICE = "/dev/meshtastic"
BROADCAST_NUM = 0xFFFFFFFF


def _node_id(num: int | None) -> str:
    if num is None or num == BROADCAST_NUM:
        return BROADCAST
    return f"!{num:08x}"


class Mesh:
    def __init__(self, store: Store, policy_path: Path):
        self.store = store
        self.policy_path = policy_path
        self.policy = pol_mod.load(policy_path)
        self.iface = None
        self.me = ""
        self.lock = threading.RLock()

    # ---- connection ----------------------------------------------------------

    def connected(self) -> bool:
        return self.iface is not None

    def connect(self) -> None:
        from meshtastic.serial_interface import SerialInterface
        from pubsub import pub

        pub.subscribe(self._on_receive, "meshtastic.receive")
        pub.subscribe(self._on_lost, "meshtastic.connection.lost")
        iface = SerialInterface(devPath=DEVICE)
        with self.lock:
            self.iface = iface
            info = iface.getMyNodeInfo() or {}
            self.me = _node_id(info.get("num"))
        log.info("connected as %s", self.me)
        self.enforce()
        self._sync_nodes()

    def _on_lost(self, interface=None, **_kw) -> None:
        log.warning("connection lost")
        with self.lock:
            self.iface = None

    def close(self) -> None:
        with self.lock:
            if self.iface is not None:
                try:
                    self.iface.close()
                except Exception:  # noqa: BLE001
                    pass
                self.iface = None

    # ---- policy enforcement -------------------------------------------------------

    def _device_config(self) -> pol_mod.DeviceConfig:
        node = self.iface.localNode
        cfg = node.localConfig
        ch0 = node.channels[0]
        secondaries = tuple(
            c.index for c in node.channels[1:]
            if c is not None and int(c.role) != 0  # 0 = DISABLED
        )
        user = (self.iface.getMyNodeInfo() or {}).get("user", {})
        from meshtastic.protobuf import config_pb2

        return pol_mod.DeviceConfig(
            tx_enabled=bool(cfg.lora.tx_enabled),
            role=config_pb2.Config.DeviceConfig.Role.Name(cfg.device.role),
            channel_name=ch0.settings.name,
            psk=bytes(ch0.settings.psk),
            position_precision=int(ch0.settings.module_settings.position_precision),
            smart_position=bool(cfg.position.position_broadcast_smart_enabled),
            long_name=user.get("longName", ""),
            short_name=user.get("shortName", ""),
            secondary_channels=secondaries,
        )

    def enforce(self) -> list[tuple]:
        with self.lock:
            if self.iface is None:
                return []
            actions = pol_mod.diff(self.policy, self._device_config())
            if actions:
                log.info("applying policy: %s", [a[0] for a in actions])
                self._apply(actions)
            return actions

    def _apply(self, actions: list[tuple]) -> None:
        from meshtastic.protobuf import config_pb2

        node = self.iface.localNode
        begin = getattr(node, "beginSettingsTransaction", None)
        commit = getattr(node, "commitSettingsTransaction", None)
        if begin:
            begin()
        for act in actions:
            kind = act[0]
            if kind == "lora_tx":
                node.localConfig.lora.tx_enabled = act[1]
                node.writeConfig("lora")
            elif kind == "delete_channel":
                node.deleteChannel(act[1])
            elif kind == "primary_channel":
                ch = node.channels[0]
                ch.settings.name = act[1]
                ch.settings.psk = act[2]
                ch.settings.module_settings.position_precision = act[3]
                node.writeChannel(0)
            elif kind == "role":
                node.localConfig.device.role = config_pb2.Config.DeviceConfig.Role.Value(act[1])
                node.writeConfig("device")
            elif kind == "smart_position":
                node.localConfig.position.position_broadcast_smart_enabled = act[1]
                node.writeConfig("position")
            elif kind == "owner":
                node.setOwner(long_name=act[1], short_name=act[2])
        if commit:
            commit()

    def update_policy(self, **changes) -> pol_mod.Policy:
        with self.lock:
            for k, v in changes.items():
                setattr(self.policy, k, v)
            pol_mod.save(self.policy_path, self.policy)
            self.enforce()
            return self.policy

    # ---- traffic -------------------------------------------------------------------

    def _on_receive(self, packet: dict, interface=None) -> None:
        decoded = packet.get("decoded", {})
        port = decoded.get("portnum")
        from_id = _node_id(packet.get("from"))
        if port == "TEXT_MESSAGE_APP":
            self.store.add_message(
                from_id=from_id, to_id=_node_id(packet.get("to")), text=decoded.get("text", ""),
                channel=int(packet.get("channel", 0)), packet_id=packet.get("id"),
                snr=packet.get("rxSnr"), ts=packet.get("rxTime") or time.time(),
            )
        elif port == "WAYPOINT_APP":
            wp = decoded.get("waypoint", {})
            if "latitudeI" in wp and "longitudeI" in wp:
                self.store.add_waypoint(
                    wp.get("name", "Waypoint"), wp["latitudeI"] / 1e7, wp["longitudeI"] / 1e7,
                    wp.get("description", ""), from_id,
                )
        self.store.upsert_node(from_id, last_heard=packet.get("rxTime") or time.time(), snr=packet.get("rxSnr"))

    def _sync_nodes(self) -> None:
        if self.iface is None:
            return
        for node_id, n in (self.iface.nodes or {}).items():
            user = n.get("user", {})
            pos = n.get("position", {})
            self.store.upsert_node(
                node_id, long_name=user.get("longName"), short_name=user.get("shortName"),
                lat=pos.get("latitude"), lon=pos.get("longitude"),
                last_heard=n.get("lastHeard"), snr=n.get("snr"),
            )
        own = (self.iface.nodes or {}).get(self.me, {}).get("position", {})
        if "latitude" in own:
            _write_json(paths.run() / "mesh-position.json",
                        {"lat": own["latitude"], "lon": own["longitude"], "time": own.get("time")})

    def send_text(self, text: str, to: str = BROADCAST, channel: int = 0) -> None:
        with self.lock:
            if self.iface is None:
                raise RuntimeError("mesh radio not connected")
            if not self.policy.tx_enabled:
                raise RuntimeError("Mesh is receive-only (EMCON). Enable transmit first.")
            pkt = self.iface.sendText(text, destinationId=to, channelIndex=channel)
        self.store.add_message(from_id=self.me, to_id=to, text=text, channel=channel,
                               packet_id=getattr(pkt, "id", None), direction="out")

    def send_waypoint(self, name: str, lat: float, lon: float, description: str = "") -> None:
        with self.lock:
            if self.iface is None:
                raise RuntimeError("mesh radio not connected")
            if not self.policy.tx_enabled:
                raise RuntimeError("Mesh is receive-only (EMCON). Enable transmit first.")
            send = getattr(self.iface, "sendWaypoint", None)
            if send is None:
                raise RuntimeError("this meshtastic library version cannot send waypoints")
            send(name=name, description=description, latitude=lat, longitude=lon,
                 expire=int(time.time()) + 7 * 86400, destinationId=BROADCAST, channelIndex=0)

    # ---- API ------------------------------------------------------------------------

    def handle(self, req: dict) -> dict:
        cmd = req.get("cmd")
        if cmd == "status":
            self._sync_nodes() if self.connected() else None
            return {
                "connected": self.connected(), "me": self.me,
                "tx_enabled": self.policy.tx_enabled and self.connected(),
                "policy_tx": self.policy.tx_enabled,
                "share_position": self.policy.share_position,
                "precision_bits": self.policy.precision_bits,
                "node_name": self.policy.long_name,
                "unread": self.store.unread_count(),
                "persistent": paths.persist_available(),
            }
        if cmd == "set_tx":
            self.update_policy(tx_enabled=bool(req["enabled"]))
            return {"tx_enabled": self.policy.tx_enabled}
        if cmd == "set_position":
            changes = {"share_position": bool(req["enabled"])}
            if "precision_bits" in req:
                bits = int(req["precision_bits"])
                if bits not in pol_mod.PRECISION_CHOICES:
                    raise ValueError("unsupported precision")
                changes["precision_bits"] = bits
            self.update_policy(**changes)
            return {}
        if cmd == "new_channel_key":
            import base64
            import secrets

            self.update_policy(psk_b64=base64.b64encode(secrets.token_bytes(32)).decode())
            return {"psk_b64": self.policy.psk_b64}
        if cmd == "set_channel":
            import base64
            import binascii

            try:
                key = base64.b64decode(str(req["psk_b64"]), validate=True)
            except binascii.Error:
                raise ValueError("the key isn't valid base64") from None
            if len(key) not in (16, 32):
                raise ValueError("the key must be 16 or 32 bytes (AES-128/256)")
            name = str(req["name"]).strip()[:11]
            if not name:
                raise ValueError("the channel needs a name")
            self.update_policy(channel_name=name, psk_b64=str(req["psk_b64"]))
            return {}
        if cmd == "get_channel":
            return {"name": self.policy.channel_name, "psk_b64": self.policy.psk_b64}
        if cmd == "conversations":
            return {"conversations": self.store.conversations(self.me)}
        if cmd == "messages":
            return {"messages": self.store.messages(req["peer"], self.me)}
        if cmd == "mark_read":
            self.store.mark_read(req["peer"], self.me)
            return {}
        if cmd == "send":
            self.send_text(str(req["text"])[:200], req.get("to", BROADCAST), int(req.get("channel", 0)))
            return {}
        if cmd == "nodes":
            if self.connected():
                self._sync_nodes()
            return {"nodes": self.store.nodes()}
        if cmd == "waypoints":
            return {"waypoints": self.store.waypoints()}
        if cmd == "add_waypoint":
            wid = self.store.add_waypoint(req["name"], float(req["lat"]), float(req["lon"]), req.get("description", ""))
            return {"id": wid}
        if cmd == "delete_waypoint":
            self.store.delete_waypoint(int(req["id"]))
            return {}
        if cmd == "share_waypoint":
            self.send_waypoint(req["name"], float(req["lat"]), float(req["lon"]), req.get("description", ""))
            return {}
        if cmd == "search":
            return {"results": self.store.search(req["query"])}
        raise ValueError(f"unknown command: {cmd}")


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        line = self.rfile.readline()
        try:
            req = json.loads(line)
            result = self.server.mesh.handle(req)  # type: ignore[attr-defined]
            reply = {"ok": True, "result": result}
        except Exception as e:  # noqa: BLE001 - errors go back to the caller
            reply = {"ok": False, "error": str(e)}
        self.wfile.write(json.dumps(reply, default=str).encode() + b"\n")


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    state = paths.user_state()
    store = Store(state / "mesh.sqlite")
    mesh = Mesh(store, state / "mesh-policy.json")

    sock = paths.run() / "meshd.sock"
    sock.parent.mkdir(parents=True, exist_ok=True)
    sock.unlink(missing_ok=True)
    server = _Server(str(sock), _Handler)
    server.mesh = mesh  # type: ignore[attr-defined]
    os.chmod(sock, 0o660)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("listening on %s (storage: %s)", sock, "persistent" if paths.persist_available() else "RAM only")

    while True:
        if not mesh.connected() and os.path.exists(DEVICE):
            try:
                mesh.connect()
            except Exception as e:  # noqa: BLE001 - retry on any connection failure
                log.warning("connect failed: %s", e)
                mesh.close()
        time.sleep(5)


if __name__ == "__main__":
    sys.exit(main())
