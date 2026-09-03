import json
import sqlite3
import threading
import time


class QueueFullError(RuntimeError):
    pass


class ProxyQueue:
    def __init__(self, path, max_items=100000, clock=None):
        self.clock = clock or time.time
        self.max_items = max(1, int(max_items))
        self.lock = threading.RLock()
        self.connection = sqlite3.connect(path, timeout=30, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS forward_queue (
                item_key TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at REAL NOT NULL,
                last_error TEXT
            )
        """)
        self.connection.commit()

    def close(self):
        with self.lock:
            self.connection.close()

    def _expand_observations(self, payload):
        if isinstance(payload, dict) and "observations" in payload:
            values = payload.get("observations") or []
            shared = {
                key: payload[key]
                for key in ("schema_version", "probe_version", "host", "session")
                if key in payload
            }
            expanded = []
            for value in values:
                if not isinstance(value, dict):
                    continue
                merged = dict(shared)
                merged.update(value)
                expanded.append(merged)
            return expanded
        return [payload] if payload else []

    def enqueue_observations(self, agent_id, payload):
        values = self._expand_observations(payload)
        if not values:
            raise ValueError("payload must contain observations")
        now = float(self.clock())
        with self.lock, self.connection:
            for value in values:
                event_id = None
                if isinstance(value, dict):
                    event_id = value.get("event_id")
                    if not event_id:
                        event = value.get("event") or {}
                        event_id = event.get("id")
                if not event_id:
                    raise ValueError("observation has no event_id")
                item_key = "observation:" + str(event_id)
                exists = self.connection.execute(
                    "SELECT 1 FROM forward_queue WHERE item_key=?", (item_key,)
                ).fetchone()
                if not exists and self.count() >= self.max_items:
                    raise QueueFullError("proxy queue limit reached")
                self.connection.execute(
                    "INSERT OR IGNORE INTO forward_queue "
                    "(item_key, kind, agent_id, payload_json, created_at, next_attempt_at) "
                    "VALUES (?, 'observation', ?, ?, ?, ?)",
                    (item_key, str(agent_id), json.dumps(value, separators=(",", ":")), now, now),
                )

    def enqueue_heartbeat(self, agent_id, payload):
        now = float(self.clock())
        with self.lock, self.connection:
            item_key = "heartbeat:" + str(agent_id)
            exists = self.connection.execute(
                "SELECT 1 FROM forward_queue WHERE item_key=?", (item_key,)
            ).fetchone()
            if not exists and self.count() >= self.max_items:
                raise QueueFullError("proxy queue limit reached")
            self.connection.execute(
                "INSERT INTO forward_queue "
                "(item_key, kind, agent_id, payload_json, created_at, next_attempt_at) "
                "VALUES (?, 'heartbeat', ?, ?, ?, ?) "
                "ON CONFLICT(item_key) DO UPDATE SET payload_json=excluded.payload_json, "
                "created_at=excluded.created_at, next_attempt_at=excluded.next_attempt_at, "
                "attempts=0, last_error=NULL",
                (item_key, str(agent_id), json.dumps(payload, separators=(",", ":")), now, now),
            )

    def due(self, limit=100):
        with self.lock:
            return self.connection.execute(
                "SELECT * FROM forward_queue WHERE next_attempt_at <= ? ORDER BY created_at LIMIT ?",
                (float(self.clock()), int(limit)),
            ).fetchall()

    def delivered(self, item_key):
        with self.lock, self.connection:
            self.connection.execute("DELETE FROM forward_queue WHERE item_key=?", (item_key,))

    def failed(self, item_key, error, base_delay=5, max_delay=600):
        with self.lock:
            row = self.connection.execute(
                "SELECT attempts FROM forward_queue WHERE item_key=?", (item_key,)
            ).fetchone()
        if row is None:
            return
        attempts = int(row[0]) + 1
        delay = min(max_delay, base_delay * (2 ** min(attempts - 1, 16)))
        with self.lock, self.connection:
            self.connection.execute(
                "UPDATE forward_queue SET attempts=?, next_attempt_at=?, last_error=? WHERE item_key=?",
                (attempts, float(self.clock()) + delay, str(error)[:2000], item_key),
            )

    def count(self):
        with self.lock:
            return self.connection.execute("SELECT COUNT(*) FROM forward_queue").fetchone()[0]
