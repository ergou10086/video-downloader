"""Read-only Twitch IRC: IRCv3 tags, batched lines and server keepalive."""
from __future__ import annotations

import re

from .models import CommentEvent


def unescape(value):
    return re.sub(r"\\(.)", lambda m: {"s":" ", ":":";", "r":"\r", "n":"\n", "\\":"\\"}.get(m[1], m[1]), value)


def parse_line(line, room, received):
    tags = {}
    if line.startswith("@"):
        raw, line = line[1:].split(" ", 1)
        tags = {k: unescape(v) for item in raw.split(";") for k, _, v in [item.partition("=")]}
    if not line.startswith(":"):
        return None
    prefix, line = line[1:].split(" ", 1)
    command, _, rest = line.partition(" ")
    if command != "PRIVMSG" or " :" not in rest:
        return None
    channel, body = rest.split(" :", 1)
    if channel.lower() != "#" + room.lower() or not body:
        return None
    if body.startswith("\x01ACTION ") and body.endswith("\x01"):
        body = body[8:-1]
    stamp = float(tags["tmi-sent-ts"]) / 1000 if tags.get("tmi-sent-ts") else None
    color = int(tags["color"].lstrip("#"), 16) if tags.get("color") else 0xFFFFFF
    return CommentEvent("Twitch", room, "_timeline", 0, body, tags.get("user-id", ""),
                        tags.get("display-name") or prefix.split("!")[0], color=color,
                        utc_ts=stamp, recv_ts=received, message_id=tags.get("id", ""),
                        source="twitch_irc", time_source="server" if stamp else "receive")
