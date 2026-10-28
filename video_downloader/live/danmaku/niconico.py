"""NDGR wire adapter using the upstream pinned generated protobuf definitions.

Protocol research: tsukumijima/NDGRClient dab9bf7. The heavy client SDK is not
embedded; framing and model decoding use protobuf's generated classes.
"""
from __future__ import annotations

import json
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urlencode

from .dependencies import library
from .models import CommentEvent
from .transport import remote_url


def protocol():
    return library("ndgr_client.proto.dwango.nicolive.chat.service.edge.payload_pb2")


class EmbeddedData(HTMLParser):
    def __init__(self):
        super().__init__()
        self.value = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id") == "embedded-data":
            self.value = json.loads(values["data-props"])


def frames(chunks, message_type):
    pending = bytearray()
    for chunk in chunks:
        pending.extend(chunk)
        while pending:
            size, shift, header = 0, 0, 0
            for index, byte in enumerate(pending[:5]):
                size |= (byte & 127) << shift
                shift += 7
                if byte < 128:
                    header = index + 1
                    break
            if not header:
                if len(pending) >= 5:
                    raise ValueError("ndgr_invalid_varint")
                break
            if size > 4 * 1024 * 1024:
                raise ValueError("ndgr_oversized_frame")
            if len(pending) < header + size:
                break
            message = message_type()
            message.ParseFromString(bytes(pending[header:header + size]))
            del pending[:header + size]
            yield message
    if pending:
        raise ValueError("ndgr_truncated_frame")


def normalize(message, room, received):
    if not message.HasField("meta") or not message.HasField("message"):
        return None
    field = "chat" if message.message.HasField("chat") else "overflowed_chat" if message.message.HasField("overflowed_chat") else None
    if field is None:
        return None
    chat = getattr(message.message, field)
    if not chat.content:
        return None
    modifier = chat.modifier
    position_name = modifier.DESCRIPTOR.fields_by_name["position"].enum_type.values_by_number[modifier.position].name.lower()
    position = {"ue": "top", "top": "top", "shita": "bottom", "bottom": "bottom"}.get(position_name, "scroll")
    color = 0xFFFFFF
    if modifier.HasField("full_color"):
        color = (modifier.full_color.r << 16) | (modifier.full_color.g << 8) | modifier.full_color.b
    elif modifier.HasField("named_color"):
        name = modifier.DESCRIPTOR.fields_by_name["named_color"].enum_type.values_by_number[modifier.named_color].name.lower()
        color = {"red":0xFF0000, "pink":0xFF8080, "orange":0xFFC000, "yellow":0xFFFF00,
                 "green":0x00FF00, "cyan":0x00FFFF, "blue":0x0000FF, "purple":0xC000FF,
                 "black":0x000000}.get(name, color)
    stamp = message.meta.at.seconds + message.meta.at.nanos / 1e9
    return CommentEvent("Niconico", room, "_timeline", int(chat.vpos) * 10, chat.content,
                        str(chat.raw_user_id or chat.hashed_user_id), placement=position, color=color,
                        utc_ts=stamp, recv_ts=received, message_id=message.meta.id, source="niconico_ndgr", time_source="server")


def collect(context, transport, stop, emit, stats):
    proto = protocol()
    page = EmbeddedData()
    page.feed(transport.text(context["url"]))
    if not page.value:
        raise ValueError("niconico_watch_metadata_unavailable")
    room = page.value["program"]["nicoliveProgramId"]
    ws_url = page.value["site"]["relive"]["webSocketUrl"]
    ws = transport.socket(remote_url(ws_url, ["nicovideo.jp"], websocket=True), origin="https://live.nicovideo.jp")
    view = ""
    try:
        ws.send(json.dumps({"type":"startWatching", "data":{"reconnect":False}}))
        deadline = time.monotonic() + 20
        while not stop.is_set() and time.monotonic() < deadline:
            try:
                data = json.loads(ws.recv())
            except library("websocket").WebSocketTimeoutException:
                continue
            if data.get("type") == "ping":
                ws.send(json.dumps({"type":"pong"}))
            elif data.get("type") in {"error", "disconnect"}:
                raise PermissionError("niconico_watch_session_unavailable")
            elif data.get("type") == "messageServer":
                view = remote_url(data["data"]["viewUri"], ["nicovideo.jp"])
                break
    finally:
        ws.close()
    if not view:
        raise ValueError("niconico_ndgr_view_unavailable")
    seen, order, futures = set(), deque(), set()
    at = 'now'
    cutoff = stats.get("latest_server_utc", time.time() - 30) - 2
    def accept(message):
        event = normalize(message, room, time.time())
        if event:
            stats["latest_server_utc"] = max(event.utc_ts, stats.get("latest_server_utc", 0))
            emit(event)
    def segment(uri):
        with transport.stream(remote_url(uri, ["nicovideo.jp"])) as chunks:
            for message in frames(chunks, proto.ChunkedMessage):
                if stop.is_set():
                    break
                accept(message)
    def backward(uri):
        # Recover a disconnect from retained server history, without assuming its
        # retention period or reading an unlimited programme archive.
        for _ in range(32):
            if stop.is_set():
                return
            packed = proto.PackedSegment()
            packed.ParseFromString(transport.response(remote_url(uri, ["nicovideo.jp"])))
            oldest = time.time()
            for message in packed.messages:
                accept(message)
                if message.HasField("meta"):
                    oldest = min(oldest, message.meta.at.seconds)
            if oldest <= cutoff or not packed.next.uri:
                return
            uri = packed.next.uri
        stats["possible_gap"] = True
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="ndgr-segment") as pool:
        while not stop.is_set():
            uri = view + (("&" if "?" in view else "?") + urlencode({"at":at}) if at is not None else "")
            with transport.stream(uri) as chunks:
                for entry in frames(chunks, proto.ChunkedEntry):
                    if stop.is_set():
                        break
                    for future in list(futures):
                        if future.done():
                            future.result()
                            futures.remove(future)
                    if entry.HasField("next"):
                        at = entry.next.at
                    elif entry.HasField("backward") and "backward" not in seen:
                        seen.add("backward")
                        futures.add(pool.submit(backward, entry.backward.segment.uri))
                    else:
                        item = entry.segment if entry.HasField("segment") else entry.previous if entry.HasField("previous") else None
                        if item and item.uri not in seen:
                            if len(futures) >= 8:
                                stats["possible_gap"] = True
                                continue
                            seen.add(item.uri)
                            order.append(item.uri)
                            if len(order) > 2048:
                                seen.discard(order.popleft())
                            futures.add(pool.submit(segment, item.uri))
            if stop.wait(1):
                break
        for future in futures:
            future.result()
