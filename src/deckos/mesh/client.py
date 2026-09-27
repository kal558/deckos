"""Client for meshd's local UNIX socket (one JSON request -> one JSON reply per line)."""
from __future__ import annotations

import json
import socket
from pathlib import Path

from .. import paths


class MeshdError(RuntimeError):
    pass


def socket_path() -> Path:
    return paths.run() / "meshd.sock"


def request(req: dict, timeout: float = 5.0) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(str(socket_path()))
        s.sendall(json.dumps(req).encode() + b"\n")
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    try:
        reply = json.loads(buf.decode() or "{}")
    except ValueError as e:
        raise MeshdError(f"bad reply from meshd: {e}") from e
    if not reply.get("ok", False):
        raise MeshdError(reply.get("error", "meshd error"))
    return reply.get("result", {})
