"""NicoChannel Plus comment history API, following yt-dlp's field contract."""
from __future__ import annotations

import re
import time
from urllib.parse import urlsplit

from .models import CommentEvent
from .timeline import epoch
from .transport import option, remote_url


def normalize(item, room, received):
    if not isinstance(item, dict):
        raise TypeError('invalid_nicochannel_comment')
    stamp = epoch(item.get("sent_at") or item.get("created_at") or item.get("updated_at"))
    playback = item.get('playback_time')
    relative = round(float(playback) * 1000) if playback is not None else 0
    return CommentEvent("NicoChannel", room, "_timeline", relative, str(item.get("message") or ""),
                        str(item.get("sender_id", "")), str(item.get("nickname") or ""),
                        utc_ts=stamp, recv_ts=received, message_id=str(item.get("id", "")),
                        source="nicochannel_history", time_source="source_relative" if playback is not None else "server" if stamp else "receive")


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
    settings = transport.json('https://nicochannel.jp/site/settings.json')
    api = remote_url(settings['api_base_url'], ['nicochannel.jp']).rstrip('/')
    headers = {"fc_use_device": "null", "fc_site_id":str(settings['fanclub_site_id']),
               "Origin": "https://nicochannel.jp", "Referer": context["url"]}
    if option(context["command"], "--username") == "jwt_token":
        headers["Authorization"] = "Bearer " + option(context["command"], "--password", "")
    channel = urlsplit(context['url']).path.strip('/').split('/')[0]
    provider = transport.json(api + '/content_providers/channel_domain', headers=headers,
                              params={'current_site_domain':'https://nicochannel.jp/' + channel})
    headers['fc_site_id'] = str(provider['data']['content_providers']['id'])
    base = api + "/video_pages/" + room
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
        ids = {str(r.get("id")) for r in rows if isinstance(r, dict)}
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
