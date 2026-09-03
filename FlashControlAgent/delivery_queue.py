# -*- coding: utf-8 -*-
"""Durable, stdlib-only delivery queue for Observation payloads."""

from __future__ import print_function

import json
import os
import sqlite3
import time


class QueueFullError(RuntimeError):
    pass


def observation_event_id(observation):
    if not isinstance(observation, dict):
        return None
    event_id = observation.get("event_id")
    if event_id:
        return str(event_id)
    event = observation.get("event") or {}
    event_id = event.get("id")
    return str(event_id) if event_id else None


class DeliveryQueue(object):
    def __init__(self, path, max_items=100000, clock=None):
        self.path = os.path.abspath(path)
        self.max_items = max(1, int(max_items))
        self.clock = clock or time.time
        folder = os.path.dirname(self.path)
        if folder and not os.path.exists(folder):
            os.makedirs(folder)
        self.connection = sqlite3.connect(self.path, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS delivery_queue (
                event_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at REAL NOT NULL,
                last_error TEXT
            )
            """
        )
        self.connection.commit()

    def close(self):
        self.connection.close()

    def _observations(self, json_text):
        try:
            from FlashControlAgent.observation_payload import expand_observations
        except ImportError:
            from observation_payload import expand_observations
        observations = expand_observations(json.loads(json_text))
        if not observations:
            raise ValueError("payload must contain at least one observation")
        for observation in observations:
            if not isinstance(observation, dict) or not observation_event_id(observation):
                raise ValueError("every observation must contain event_id")
        return observations

    def enqueue_json(self, json_text):
        observations = self._observations(json_text)
        now = float(self.clock())
        event_ids = [observation_event_id(item) for item in observations]
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("payload contains duplicate event_id values")

        placeholders = ",".join(["?"] * len(event_ids))
        existing = self.connection.execute(
            "SELECT COUNT(*) FROM delivery_queue WHERE event_id IN (%s)" % placeholders,
            event_ids,
        ).fetchone()[0]
        current = self.count()
        if current + len(event_ids) - existing > self.max_items:
            raise QueueFullError("delivery queue limit reached (%s items)" % self.max_items)

        with self.connection:
            for observation in observations:
                event_id = observation_event_id(observation)
                payload = json.dumps(
                    observation,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                self.connection.execute(
                    """
                    INSERT OR IGNORE INTO delivery_queue
                        (event_id, payload_json, created_at, next_attempt_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (event_id, payload, now, now),
                )
        return event_ids

    def due(self, limit=100):
        return self.connection.execute(
            """
            SELECT event_id, payload_json, attempts, next_attempt_at, last_error
            FROM delivery_queue
            WHERE next_attempt_at <= ?
            ORDER BY created_at, event_id
            LIMIT ?
            """,
            (float(self.clock()), max(1, int(limit))),
        ).fetchall()

    def mark_delivered(self, event_id):
        with self.connection:
            self.connection.execute(
                "DELETE FROM delivery_queue WHERE event_id = ?", (str(event_id),)
            )

    def mark_failed(self, event_id, error, base_delay=30, max_delay=3600):
        row = self.connection.execute(
            "SELECT attempts FROM delivery_queue WHERE event_id = ?", (str(event_id),)
        ).fetchone()
        if row is None:
            return None
        attempts = int(row[0]) + 1
        delay = min(float(max_delay), float(base_delay) * (2 ** min(attempts - 1, 16)))
        next_attempt_at = float(self.clock()) + delay
        with self.connection:
            self.connection.execute(
                """
                UPDATE delivery_queue
                SET attempts = ?, next_attempt_at = ?, last_error = ?
                WHERE event_id = ?
                """,
                (attempts, next_attempt_at, str(error)[:2000], str(event_id)),
            )
        return delay

    def count(self):
        return int(self.connection.execute("SELECT COUNT(*) FROM delivery_queue").fetchone()[0])


def deliver_due(queue, sender, limit=100, base_delay=30, max_delay=3600,
                on_failure=None):
    """Deliver due rows and acknowledge them only after sender succeeds."""
    delivered = 0
    for item in queue.due(limit):
        event_id = item["event_id"]
        try:
            sender(item["payload_json"])
            queue.mark_delivered(event_id)
            delivered += 1
        except Exception as exc:
            delay = queue.mark_failed(
                event_id, exc, base_delay=base_delay, max_delay=max_delay
            )
            if on_failure is not None:
                on_failure(event_id, exc, delay)
    return delivered
