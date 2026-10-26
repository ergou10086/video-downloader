"""Consume withny-dl's native JSON, including its trailing-comma array format."""
from __future__ import annotations

import json
import time

from .models import CommentEvent
from .timeline import epoch


def read_chat(path, segment, stats):
    stats.update(source="withny_json", rejected_count=0, truncated=False)
    decoder, pending = json.JSONDecoder(), ""
    with open(path, encoding="utf-8-sig") as source:
        for chunk in iter(lambda: source.read(65536), ""):
            pending += chunk
            while True:
                pending = pending.lstrip(" \r\n\t[,]")
                if not pending:
                    break
                try:
                    item, end = decoder.raw_decode(pending)
                except ValueError:
                    if len(pending) > 1024 * 1024:
                        raise ValueError("oversized Withny chat record")
                    break
                pending = pending[end:]
                try:
                    if item.get("deletedAt"):
                        continue
                    kind = "gift" if item.get("itemID") else "superchat" if float(item.get("tipAmount") or 0) else "chat"
                    body = str(item.get("content") or item.get("itemName") or "")
                    if kind == "superchat":
                        body = "[SC " + str(item.get("tipAmount")) + "] " + body
                    elif kind == "gift":
                        body = "[礼物] " + body
                    stamp = epoch(item.get("createdAt"))
                    yield CommentEvent("Withny", str(item.get("streamUUID", "")), segment, 0, body,
                                       str(item.get("userUUID", "")), str(item.get("name") or item.get("username") or ""),
                                       kind, "scroll" if kind == "chat" else "top", utc_ts=stamp,
                                       message_id=str(item.get("commentUUID", "")), source="withny_json", time_source="server")
                except (ValueError, TypeError, AttributeError):
                    stats["rejected_count"] += 1
    stats["truncated"] = bool(pending.strip(" \r\n\t,]"))
