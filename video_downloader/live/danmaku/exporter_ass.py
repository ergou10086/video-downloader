"""Conservative lanes with no catch-up collisions; serialization is pysubs2's."""
from __future__ import annotations

from .dependencies import library
from .exporter_srt import plain_text, wrap


def export_ass(events, path, *, width=1920, height=1080, duration_ms=None):
    subs = library("pysubs2")
    result = subs.SSAFile()
    result.info.update(PlayResX=str(width), PlayResY=str(height), WrapStyle="2", ScaledBorderAndShadow="yes")
    font = max(12, round(height * 38 / 1080))
    result.styles["Default"] = subs.SSAStyle(fontname="Microsoft YaHei", fontsize=font,
                                           outline=2, shadow=0, alignment=subs.Alignment.TOP_LEFT)
    for name, rgb in {"SP":(255,210,100), "MSG":(170,220,255)}.items():
        result.styles[name] = subs.SSAStyle(fontname="Microsoft YaHei", fontsize=font, bold=True,
                                          primarycolor=subs.Color(*rgb), outline=2, shadow=0,
                                          alignment=subs.Alignment.TOP_CENTER)
    # A lane stays occupied until the entire previous message exits. This
    # deliberately trades density for collision-free layout, even for long text.
    lanes = {kind: [0] * max(1, height // (font * 3) // 3) for kind in ("scroll", "top", "bottom")}
    dropped = 0
    for event in events:
        start = event.relative_ms
        if start < 0 or (duration_ms is not None and start >= duration_ms):
            dropped += 1
            continue
        kind = "top" if event.kind != "chat" else event.placement
        lane = next((i for i, end in enumerate(lanes[kind]) if end <= start), None)
        if lane is None:
            dropped += 1
            continue
        end = start + (12000 if kind == "scroll" else 5000)
        if duration_ms is not None:
            end = min(end, duration_ms)
        lanes[kind][lane] = end
        # Independent vertical bands also prevent fixed vs moving collisions.
        band = {"top": 0, "scroll": height // 3, "bottom": height * 2 // 3}[kind]
        y = band + lane * font * 3 + font
        text = wrap(plain_text(event.text), columns=42).replace("\n", r"\N")
        color = subs.Color((event.color >> 16) & 255, (event.color >> 8) & 255, event.color & 255)
        rgb = f"{color.b:02X}{color.g:02X}{color.r:02X}"
        position = (rf"\move({width + font},{y},{-width},{y})" if kind == "scroll"
                    else rf"\an8\pos({width // 2},{y})")
        style = "SP" if event.kind == "superchat" else "MSG" if event.kind in {"gift","guard"} else "Default"
        color_tag = rf"\c&H{rgb}&" if style == "Default" else ""
        result.append(subs.SSAEvent(start=start, end=end, style=style, text="{" + position + color_tag + "}" + text))
    result.save(str(path), format_="ass", encoding="utf-8")
    return {"exported_count": len(result), "dropped_count": dropped,
            "resolution": [width, height], "layout": "exclusive_lanes"}
