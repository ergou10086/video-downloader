"""Per-job loopback webhook receiver; no access to the product's session token."""
from __future__ import annotations

import json
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class LiveJobEvent:
    event_id: str
    kind: str
    data: dict


class BrecEvents:
    def __init__(self, session, media_root, room_id):
        self.session, self.media_root, self.room_id = session, Path(media_root).resolve(), int(room_id)
        self.lock = threading.RLock()
        self.seen = set()
        self.opened, self.closed = set(), set()
        self.file_intervals = {}
        self.session_ended = threading.Event()
        self.stream_ended = threading.Event()
        self.failed = threading.Event()
        self.token = secrets.token_urlsafe(32)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reject(self, status):
                # Leaving a small request body unread can make Windows reset the
                # connection before the caller receives the rejection status.
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if 0 < length <= 65537:
                        self.rfile.read(length)
                except (ValueError, OSError):
                    pass
                self.send_error(status)

            def do_POST(self):
                self.connection.settimeout(3)
                if (self.client_address[0] != "127.0.0.1" or self.headers.get("Origin") or
                        not secrets.compare_digest(self.path, owner.route)):
                    self.reject(403)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 65536:
                        self.reject(413)
                        return
                    if self.headers.get_content_type() != "application/json":
                        self.reject(415)
                        return
                    self.connection.settimeout(3)
                    owner.accept(json.loads(self.rfile.read(length).decode("utf-8")))
                except (ValueError, TypeError, KeyError, OSError):
                    self.send_error(400)
                    return
                self.send_response(204)
                self.end_headers()

        self.route = "/api/live/webhook/brec/" + self.token
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}{self.route}"

    def accept(self, payload):
        if not isinstance(payload, dict) or not isinstance(payload.get("EventData"), dict):
            raise ValueError("invalid webhook")
        data, event_id, kind = payload["EventData"], payload.get("EventId"), payload.get("EventType")
        if (not isinstance(event_id, str) or len(event_id) > 128 or not event_id or
                not isinstance(kind, str) or len(kind) > 128):
            raise ValueError("invalid event identity")
        if int(data.get("RoomId", 0)) != self.room_id and int(data.get("ShortId", 0)) != self.room_id:
            raise ValueError("wrong room")
        relative = data.get("RelativePath")
        if kind in {"FileOpening", "FileClosed"} and (not isinstance(relative, str) or not relative or len(relative) > 4096):
            raise ValueError("missing file path")
        if relative is not None:
            path = (self.media_root / relative).resolve()
            if not path.is_relative_to(self.media_root) or Path(relative).is_absolute():
                raise ValueError("path outside recording directory")
        with self.lock:
            if event_id in self.seen:
                return
            self.session.event("brec", event_id=event_id, event_type=kind, data=data)
            self.seen.add(event_id)
            if kind == "FileOpening":
                self.opened.add(relative)
                self.session.data["probe"] = {"source": "BililiveRecorder", "title": data.get("Title", ""),
                                              "room_id": data.get("RoomId"), "quality": data.get("QnDescription", "")}
                self.session.save()
            elif kind == "FileClosed":
                self.closed.add(relative)
                self.file_intervals[relative] = {key: data.get(key) for key in ("FileOpenTime", "FileCloseTime", "Duration")}
            elif kind == "SessionEnded":
                self.session_ended.set()
            elif kind == "StreamEnded":
                self.stream_ended.set()
            elif kind in {"FileError", "Error"}:
                self.failed.set()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def timeline_has_gap(self):
        with self.lock:
            try:
                values = list(self.file_intervals.values())
                if not values:
                    return False
                start = min(datetime.fromisoformat(v["FileOpenTime"]).timestamp() for v in values)
                end = max(datetime.fromisoformat(v["FileCloseTime"]).timestamp() for v in values)
                duration = sum(float(v["Duration"]) for v in values)
                return end - start - duration > 3
            except (ValueError, TypeError, KeyError):
                return False
