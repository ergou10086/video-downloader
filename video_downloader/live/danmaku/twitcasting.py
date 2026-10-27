"""Normalize the web client's event.pubsub events, retaining receive-clock provenance."""
from __future__ import annotations

from .models import CommentEvent
from .timeline import epoch


def events(payload, room, received):
    if isinstance(payload, dict):
        payload = payload.get("data", payload.get("events", [payload]))
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind not in {"comment", "gift"}:
            continue
        author = item.get("author") or item.get("sender") or {}
        body = item.get("message") or item.get("item", {}).get("name") or ""
        if not body:
            continue
        stamp = epoch(item.get("createdAt"))
        if stamp and stamp > 100000000000:
            stamp /= 1000
        yield CommentEvent("TwitCasting", room, "_timeline", 0,
                           ("[礼物] " if kind == "gift" else "") + body,
                           str(author.get("id", "")), str(author.get("name") or author.get("screenName") or ""),
                           "gift" if kind == "gift" else "chat", "top" if kind == "gift" else "scroll",
                           utc_ts=stamp, recv_ts=received, message_id=str(item.get("id", "")),
                           source="twitcasting_pubsub", time_source="server" if stamp else "receive")
