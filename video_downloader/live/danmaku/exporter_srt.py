"""Readable, bounded subtitles; pysubs2 owns format serialization."""
from __future__ import annotations

import re
import unicodedata

from .dependencies import library


def plain_text(value):
    # User content must not become ASS overrides, SRT HTML, or hard spaces.
    text = "".join(c for c in value if c in "\n\t" or unicodedata.category(c) != "Cc")
    return text.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("<", "＜").replace(">", "＞")


def wrap(value, columns=42):
    lines, line, width = [], "", 0
    for char in re.sub(r"\s+", " ", value).strip():
        size = 2 if unicodedata.east_asian_width(char) in "WF" else 1
        if width + size > columns:
            lines.append(line)
            line, width = "", 0
        line, width = line + char, width + size
    lines.append(line)
    return "\n".join(lines[:2]) + ("…" if len(lines) > 2 else "")


def export_srt(events, path, *, duration_ms=None):
    subs = library("pysubs2")
    result, dropped, previous_end = subs.SSAFile(), 0, 0
    for event in events:
        if event.relative_ms < 0 or (duration_ms is not None and event.relative_ms >= duration_ms):
            dropped += 1
            continue
        # Drop congested comments instead of progressively shifting them away
        # from the video. At most one cue is active; source time is never moved.
        if event.relative_ms < previous_end:
            dropped += 1
            continue
        text = wrap(plain_text((event.user_name + ": " if event.user_name else "") + event.text))
        end = event.relative_ms + min(6000, max(2500, 1800 + len(text) * 60))
        if duration_ms is not None:
            end = min(end, duration_ms)
        result.append(subs.SSAEvent(start=event.relative_ms, end=end, text=text.replace("\n", r"\N")))
        previous_end = end
    result.save(str(path), format_="srt", encoding="utf-8-sig")
    return {"exported_count": len(result), "dropped_count": dropped}
