"""JSONL fact log with a rebuildable SQLite WAL index, scoped to one recording."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from dataclasses import replace
from pathlib import Path

from .models import CommentEvent


class CommentStore:
    def __init__(self, root, *, anonymize=False):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "events.jsonl"
        self.db = sqlite3.connect(self.root / "events.sqlite")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("DROP TABLE IF EXISTS events")
        self.db.execute("CREATE TABLE events (id TEXT PRIMARY KEY, payload TEXT NOT NULL, relative_ms INTEGER, segment_id TEXT)")
        self.db.execute("CREATE INDEX timeline ON events(segment_id, relative_ms, id)")
        self.db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('salt', ?)", (secrets.token_hex(32),))
        self.salt = self.db.execute("SELECT value FROM metadata WHERE key='salt'").fetchone()[0].encode()
        self.anonymize = anonymize
        # A crash can leave SQLite ahead or behind. Rebuild only from complete
        # JSONL records, truncating an incomplete final line before appending.
        if self.path.exists():
            with self.path.open("r+b") as source:
                while True:
                    start = source.tell()
                    line = source.readline()
                    if not line:
                        break
                    if not line.endswith(b"\n"):
                        source.truncate(start)
                        break
                    record = json.loads(line)
                    CommentEvent(**record["event"])
                    self.db.execute("INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?)",
                                    (record["id"], json.dumps(record["event"], ensure_ascii=False),
                                     record["event"]["relative_ms"], record["event"]["segment_id"]))
        self.db.commit()
        self.output = self.path.open("a", encoding="utf-8", newline="\n")
        self.pending, self.last_sync = 0, time.monotonic()

    def append(self, event):
        identity = event.identity
        if self.db.execute("SELECT 1 FROM events WHERE id=?", (identity,)).fetchone():
            return False
        if self.anonymize:
            def private(value):
                return hmac.new(self.salt, value.encode(), hashlib.sha256).hexdigest()[:16] if value else ""
            event = replace(event, user_id=private(event.user_id), user_name=private(event.user_name))
        payload = json.dumps(event.to_dict(), ensure_ascii=False, allow_nan=False)
        self.output.write(json.dumps({"id": identity, "event": event.to_dict()}, ensure_ascii=False) + "\n")
        self.db.execute("INSERT INTO events VALUES (?, ?, ?, ?)",
                        (identity, payload, event.relative_ms, event.segment_id))
        self.pending += 1
        if self.pending >= 200 or time.monotonic() - self.last_sync >= 1:
            self.sync()
        return True

    def events(self, segment_id=None):
        return list(self.iter_events(segment_id))

    def iter_events(self, segment_id=None):
        query = "SELECT payload FROM events"
        args = ()
        if segment_id is not None:
            query += " WHERE segment_id=?"
            args = (segment_id,)
        for payload, in self.db.execute(query + " ORDER BY relative_ms, id", args):
            yield CommentEvent(**json.loads(payload))

    def sync(self):
        self.output.flush()
        os.fsync(self.output.fileno())
        self.db.commit()
        self.pending, self.last_sync = 0, time.monotonic()

    def close(self):
        if getattr(self, "output", None):
            self.sync()
            self.output.close()
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
