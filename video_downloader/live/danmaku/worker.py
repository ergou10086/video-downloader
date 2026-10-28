"""Isolated comment process: bounded queues, retry/backoff and crash-recoverable log."""
from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path

from ..session import atomic_json, _process_exists
from .sources import SOURCES
from .store import CommentStore
from .transport import Transport
from .dependencies import MissingDependency


def run(context):
    root = Path(context["root"])
    stop = threading.Event()
    ordinary, priority = queue.Queue(49000), queue.Queue(1000)
    stats = {"status":"running", "source":context["platform"], "received_count":0, "duplicate_count":0,
             "rejected_count":0, "dropped_count":0, "reconnects":0, "errors":[], "anchor_error_ms":None}
    def emit(event):
        try:
            (ordinary if event.kind == "chat" else priority).put_nowait(event)
        except queue.Full:
            stats["dropped_count"] += 1
    def collect():
        while not stop.is_set():
            transport = None
            try:
                if context["platform"] == "YouTube":
                    transport = None
                else:
                    command = context["command"]
                    if context["platform"] == "Twitch":
                        from .transport import option
                        command = [command[0], "--proxy", option(command, "--proxy", "")]
                    transport = Transport(command)
                SOURCES[context["platform"]](context, transport, stop, emit, stats)
                return
            except Exception as exc:
                code = getattr(getattr(exc, "response", None), "status_code", None)
                stats["errors"] = [{"type":type(exc).__name__, "http_status":code}]
                if isinstance(exc, (PermissionError, ImportError, MissingDependency)) or code in {401,403}:
                    stats["status"] = "unavailable"
                    return
                stats["reconnects"] += 1
                delay = min(60, 2 ** min(stats["reconnects"], 6))
                if code in {412, 429}:
                    delay = max(30, delay)
                if context["platform"] in {"Twitch", "TwitCasting", "Niconico"}:
                    delay = 60
                if stop.wait(delay):
                    return
            finally:
                if transport:
                    transport.close()
    thread = threading.Thread(target=collect, name="comment-source", daemon=True)
    thread.start()
    try:
        with CommentStore(root, anonymize=bool(context.get("anonymize"))) as store:
            last_status = 0
            while thread.is_alive() or not ordinary.empty() or not priority.empty():
                if (root / "stop").exists() or (context.get("max_seconds") and time.time() >= context["deadline"]):
                    stop.set()
                event = None
                try:
                    event = priority.get_nowait()
                except queue.Empty:
                    try:
                        event = ordinary.get(timeout=0.2)
                    except queue.Empty:
                        pass
                if event:
                    stats["received_count" if store.append(event) else "duplicate_count"] += 1
                if time.monotonic() - last_status > 1:
                    if context.get("owner_pid") and not _process_exists(context["owner_pid"]):
                        stats["owner_interrupted"] = True
                        stop.set()
                    store.sync()
                    atomic_json(root / "capture-status.json", stats)
                    last_status = time.monotonic()
                if stop.is_set() and not thread.is_alive() and ordinary.empty() and priority.empty():
                    break
        if stats["status"] == "running":
            stats["status"] = "partial" if any(stats.get(key) for key in (
                "errors", "dropped_count", "possible_gap", "owner_interrupted", "rejected_count", "truncated")) else "captured"
    except Exception as exc:
        stats.update(status="failed", errors=[{"type":type(exc).__name__}])
    finally:
        stop.set()
        atomic_json(root / "capture-status.json", stats)
    return 0 if stats["status"] in {"captured","partial"} else 1


def main(path):
    request = Path(path).resolve()
    context = json.loads(request.read_text(encoding="utf-8"))
    root = Path(context["root"]).resolve()
    if request.parent != root or request.name != "request.json" or context["platform"] not in SOURCES:
        raise ValueError("invalid_comment_worker_request")
    if context.get("max_seconds"):
        context["deadline"] = time.time() + context["max_seconds"]
    return run(context)


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1]))
