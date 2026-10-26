"""NicoChannel Plus comment history API, following yt-dlp's field contract."""
from __future__ import annotations

import re
import time
from urllib.parse import urlsplit

from .models import CommentEvent
from .timeline import epoch
from .transport import option


def normalize(item, room, received):
    stamp = epoch(item.get("sent_at") or item.get("created_at") or item.get("updated_at"))
    return CommentEvent("NicoChannel", room, "_timeline", 0, str(item.get("message") or ""),
                        str(item.get("sender_id", "")), str(item.get("nickname") or ""),
                        utc_ts=stamp, recv_ts=received, message_id=str(item.get("id", "")),
                        source="nicochannel_history", time_source="server" if stamp else "receive")


def collect(context, transport, stop, emit, stats):
    match = re.search(r"/(?:video|live)/(sm[a-zA-Z0-9]+)", urlsplit(context["url"]).path)
    if not match:
        from ..catchup import CatchUpPlanner
        info = CatchUpPlanner().metadata(context["command"], context["url"])
        room = str(info.get("id", ""))
        if not re.fullmatch(r"sm[a-zA-Z0-9]+", room):
            raise ValueError("nicochannel_event_url_required")
    else:
        room = match[1]
    headers = {"fc_use_device": "null", "Origin": "https://nicochannel.jp", "Referer": context["url"]}
    if option(context["command"], "--username") == "jwt_token":
        headers["Authorization"] = "Bearer " + option(context["command"], "--password", "")
    base = "https://nfc-api.nicochannel.jp/fc/video_pages/" + room
    video = transport.json(base, headers=headers)["data"]["video_page"]
    group = (video.get("video_comment_setting") or {}).get("comment_group_id")
    if not group:
        raise ValueError("nicochannel_comments_disabled")
    previous, token, refreshed = set(), "", 0
    stats["history_window"] = 120
    while not stop.is_set():
        if time.monotonic() - refreshed > 240 or not token:
            token = transport.json(base + "/comments_user_token", headers=headers)["data"]["access_token"]
            refreshed = time.monotonic()
        rows = transport.json("https://comm-api.sheeta.com/messages.history", method="POST",
                              params={"sort_direction": "desc", "limit": 120},
                              json={"token": token, "group_id": group})
        if not isinstance(rows, list):
            raise ValueError("nicochannel_history_schema_changed")
        ids = {str(r.get("id")) for r in rows}
        if previous and len(rows) >= 120 and not (ids & previous):
            stats["possible_gap"] = True
        for row in rows:
            try:
                emit(normalize(row, room, time.time()))
            except (ValueError, TypeError):
                stats["rejected_count"] += 1
        previous = ids
        if stop.wait(1):
            break
