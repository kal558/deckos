"""SQLite storage for mesh messages, nodes and waypoints (WAL, crash-safe)."""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    packet_id INTEGER,
    ts REAL NOT NULL,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    channel INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    snr REAL,
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    read INTEGER NOT NULL DEFAULT 0,
    UNIQUE (packet_id, from_id)
);
CREATE INDEX IF NOT EXISTS messages_peer ON messages (from_id, to_id, ts);
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    long_name TEXT,
    short_name TEXT,
    lat REAL,
    lon REAL,
    last_heard REAL,
    snr REAL
);
CREATE TABLE IF NOT EXISTS waypoints (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    from_id TEXT,
    ts REAL NOT NULL
);
"""

BROADCAST = "^all"


class Store:
    def __init__(self, path: Path | str):
        self._lock = threading.Lock()
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def add_message(self, *, from_id: str, to_id: str, text: str, channel: int = 0,
                    packet_id: int | None = None, snr: float | None = None,
                    direction: str = "in", ts: float | None = None) -> bool:
        """Insert a message; returns False if it's a duplicate (same packet from same node)."""
        with self._lock, self.db:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO messages (packet_id, ts, from_id, to_id, channel, text, snr, direction, read)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (packet_id, ts or time.time(), from_id, to_id, channel, text, snr, direction,
                 1 if direction == "out" else 0),
            )
            return cur.rowcount == 1

    def conversations(self, me: str) -> list[dict]:
        """One row per conversation: broadcast channels and direct peers."""
        rows = self.db.execute(
            """
            SELECT CASE WHEN to_id = ? THEN from_id WHEN direction = 'out' AND to_id != ? THEN to_id
                        ELSE '#' || channel END AS peer,
                   MAX(ts) AS last_ts,
                   SUM(CASE WHEN read = 0 THEN 1 ELSE 0 END) AS unread
            FROM messages GROUP BY peer ORDER BY last_ts DESC
            """,
            (me, BROADCAST),
        ).fetchall()
        return [dict(r) for r in rows]

    def messages(self, peer: str, me: str, limit: int = 200) -> list[dict]:
        if peer.startswith("#"):
            ch = int(peer[1:])
            q = ("SELECT * FROM messages WHERE channel = ? AND to_id = ? ORDER BY ts DESC LIMIT ?", (ch, BROADCAST, limit))
        else:
            q = (
                "SELECT * FROM messages WHERE (from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?)"
                " ORDER BY ts DESC LIMIT ?",
                (peer, me, me, peer, limit),
            )
        return [dict(r) for r in reversed(self.db.execute(*q).fetchall())]

    def mark_read(self, peer: str, me: str) -> None:
        with self._lock, self.db:
            if peer.startswith("#"):
                self.db.execute("UPDATE messages SET read = 1 WHERE channel = ? AND to_id = ?", (int(peer[1:]), BROADCAST))
            else:
                self.db.execute("UPDATE messages SET read = 1 WHERE from_id = ? AND to_id = ?", (peer, me))

    def unread_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM messages WHERE read = 0").fetchone()[0]

    def search(self, query: str, limit: int = 20) -> list[dict]:
        like = f"%{query}%"
        rows = self.db.execute(
            "SELECT m.*, n.long_name FROM messages m LEFT JOIN nodes n ON n.id = m.from_id"
            " WHERE m.text LIKE ? OR n.long_name LIKE ? ORDER BY m.ts DESC LIMIT ?",
            (like, like, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_node(self, node_id: str, **fields) -> None:
        cols = ["long_name", "short_name", "lat", "lon", "last_heard", "snr"]
        vals = {c: fields.get(c) for c in cols}
        with self._lock, self.db:
            self.db.execute(
                "INSERT INTO nodes (id, long_name, short_name, lat, lon, last_heard, snr) VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET"
                " long_name = COALESCE(excluded.long_name, long_name),"
                " short_name = COALESCE(excluded.short_name, short_name),"
                " lat = COALESCE(excluded.lat, lat), lon = COALESCE(excluded.lon, lon),"
                " last_heard = COALESCE(excluded.last_heard, last_heard), snr = COALESCE(excluded.snr, snr)",
                (node_id, *[vals[c] for c in cols]),
            )

    def nodes(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM nodes ORDER BY last_heard DESC").fetchall()]

    def add_waypoint(self, name: str, lat: float, lon: float, description: str = "",
                     from_id: str | None = None) -> int:
        with self._lock, self.db:
            cur = self.db.execute(
                "INSERT INTO waypoints (name, description, lat, lon, from_id, ts) VALUES (?, ?, ?, ?, ?, ?)",
                (name, description, lat, lon, from_id, time.time()),
            )
            return int(cur.lastrowid)

    def waypoints(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM waypoints ORDER BY ts DESC").fetchall()]

    def delete_waypoint(self, wp_id: int) -> None:
        with self._lock, self.db:
            self.db.execute("DELETE FROM waypoints WHERE id = ?", (wp_id,))
