"""Stream Brec's native XML, without another connection or copied GPL code.

Format reference: BililiveRecorder v2.20.0 BasicDanmakuWriter.cs.
Only direct children of <i> are events; embedded XSLT is never evaluated.
"""
from __future__ import annotations

import math
from datetime import datetime

from .dependencies import library
from .models import CommentEvent


def read_xml(path, segment_id, stats):
    xml = library("defusedxml.ElementTree")
    room, started, depth, root = "", None, 0, None
    stats.update(source="bililive_xml", anchor_source="brec_relative", anchor_error_ms=None,
                 rejected_count=0, truncated=False)
    try:
        with open(path, "rb") as source:
            for action, node in xml.iterparse(source, events=("start", "end"), forbid_dtd=True):
                if action == "start":
                    depth += 1
                    if depth == 1:
                        if node.tag != "i":
                            raise ValueError("Not a Bilibili XML document")
                        root = node
                    continue
                if depth == 2:
                    if node.tag == "BililiveRecorderRecordInfo":
                        room = node.get("roomid", "")
                        try:
                            started = datetime.fromisoformat(node.get("start_time", "")).timestamp()
                            stats["record_start_time"] = started
                        except ValueError:
                            pass
                    elif node.tag in {"d", "sc", "gift", "guard"}:
                        try:
                            kind = {"d": "chat", "sc": "superchat", "gift": "gift", "guard": "guard"}[node.tag]
                            params = node.get("p", "").split(",")
                            seconds = float(params[0] if kind == "chat" else node.get("ts", ""))
                            if not math.isfinite(seconds):
                                raise ValueError("Invalid timestamp")
                            relative = round(seconds * 1000)
                            if kind == "chat":
                                uid = params[6]
                                color = int(params[3])
                                placement = {"4": "bottom", "5": "top"}.get(params[1], "scroll")
                                # p[4] is a send timestamp, sometimes ms; retain it
                                # for cross-segment dedup, never as the media anchor.
                                sent = float(params[4])
                                utc = (sent / 1000 if sent > 100000000000 else sent) if sent > 0 else None
                                text = node.text or ""
                            else:
                                uid, color, placement, utc = node.get("uid", ""), 0xFFFFFF, "top", None
                                text = node.text or ""
                                if kind == "superchat":
                                    text = "[SC ¥" + node.get("price", "0") + "] " + text
                                elif kind == "gift":
                                    text = "[礼物] " + node.get("giftname", "") + " ×" + node.get("giftcount", "1")
                                else:
                                    text = "[舰长] 等级 " + node.get("level", "") + " ×" + node.get("count", "1")
                            yield CommentEvent("Bilibili", room, segment_id, relative, text, uid,
                                               node.get("user", ""), kind, placement, color, utc)
                        except (ValueError, IndexError, OverflowError):
                            stats["rejected_count"] += 1
                    node.clear()
                    root.clear()
                depth -= 1
    except xml.ParseError:
        # A killed recorder can leave an unclosed final element; completed
        # preceding messages are useful, but the report must disclose truncation.
        stats["truncated"] = True
