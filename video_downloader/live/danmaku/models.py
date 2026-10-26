"""Normalized source time remains separate from the export media timeline."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CommentEvent:
    platform: str
    room_id: str
    segment_id: str
    relative_ms: int
    text: str
    user_id: str = ""
    user_name: str = ""
    kind: str = "chat"
    placement: str = "scroll"
    color: int = 0xFFFFFF
    utc_ts: float | None = None
    recv_ts: float | None = None
    message_id: str = ""
    source: str = "bililive_xml"
    time_source: str = "source_relative"
    anonymized: bool = False

    def __post_init__(self):
        if self.kind not in {"chat", "superchat", "gift", "guard"}:
            raise ValueError("Invalid comment kind")
        if self.placement not in {"scroll", "top", "bottom"} or not 0 <= self.color <= 0xFFFFFF:
            raise ValueError("Invalid comment layout")
        if not isinstance(self.relative_ms, int) or abs(self.relative_ms) > 31 * 86400000:
            raise ValueError("Invalid relative comment time")
        if not self.text or len(self.text) > 10000:
            raise ValueError("Invalid comment text")
        if self.time_source not in {"source_relative", "server", "receive"}:
            raise ValueError("Invalid comment time source")
        for value in (self.utc_ts, self.recv_ts):
            if value is not None and not math.isfinite(value):
                raise ValueError("Invalid absolute comment time")

    def to_dict(self):
        return asdict(self)

    @property
    def identity(self):
        # Brec's p[7] is always zero, NOT a message ID. Do not use it for dedup.
        point = self.utc_ts if self.utc_ts is not None else (self.segment_id, self.relative_ms)
        values = [self.platform, self.room_id, self.source, self.message_id] if self.message_id else [
            self.platform, self.room_id, point, self.user_id, self.kind, self.text]
        return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()
