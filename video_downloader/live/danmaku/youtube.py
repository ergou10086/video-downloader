"""Normalize yt-dlp's native live_chat JSON; no second chat protocol implementation."""
from __future__ import annotations

from .models import CommentEvent


def text(value):
    if not isinstance(value, dict):
        return str(value or "")
    return value.get("simpleText") or "".join(
        run.get("text") or next(iter(run.get("emoji", {}).get("shortcuts", [])), "")
        for run in value.get("runs", []))


def messages(value, room, received, offset=None):
    if isinstance(value, list):
        for child in value:
            yield from messages(child, room, received, offset)
    elif isinstance(value, dict):
        replay = value.get("replayChatItemAction")
        if isinstance(replay, dict):
            yield from messages(replay.get("actions", []), room, received, int(replay.get("videoOffsetTimeMsec", 0)))
            return
        for key, kind in {"liveChatTextMessageRenderer":"chat", "liveChatPaidMessageRenderer":"superchat",
                          "liveChatPaidStickerRenderer":"gift", "liveChatMembershipItemRenderer":"guard"}.items():
            if key not in value:
                continue
            item = value[key]
            stamp = float(item["timestampUsec"]) / 1e6 if item.get("timestampUsec") else None
            body = text(item.get("message") or item.get("headerSubtext") or item.get("sticker", {}).get("accessibility", {}).get("accessibilityData", {}).get("label"))
            if kind == "superchat":
                body = "[SC " + text(item.get("purchaseAmountText")) + "] " + body
            if kind in {"gift", "guard"}:
                body = ("[礼物] " if kind == "gift" else "[会员] ") + (body or text(item.get("headerPrimaryText")) or kind)
            if body:
                yield CommentEvent("YouTube", room, "_timeline", offset or 0, body,
                                   str(item.get("authorExternalChannelId", "")), text(item.get("authorName")), kind,
                                   "scroll" if kind == "chat" else "top", utc_ts=stamp, recv_ts=received,
                                   message_id=str(item.get("id", "")), source="yt_dlp_live_chat",
                                   time_source="source_relative" if offset is not None else "server" if stamp else "receive")
            return
        for child in value.values():
            yield from messages(child, room, received, offset)
