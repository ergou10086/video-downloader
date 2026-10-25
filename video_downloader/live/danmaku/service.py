"""Post-recording sidecar pipeline: independent failures and per-media anchors."""
from __future__ import annotations

from pathlib import Path

from ..session import atomic_json
from .bilibili import read_xml
from .exporter_ass import export_ass
from .exporter_srt import export_srt
from .store import CommentStore


def process_comments(session, media_report, config):
    if not config.get("LIVE_DANMAKU_ENABLED", 0):
        return {"status": "disabled"}
    report = {"status": "unavailable", "sources": [], "outputs": [], "errors": [],
              "anchor_error_ms": None, "anchor_note": "录播姬 XML 相对时间；媒体起点误差尚未实测标定"}
    root = session.root / "danmaku"
    try:
        formats = str(config.get("LIVE_DANMAKU_FORMATS", "srt,ass")).split(",")
        with CommentStore(root, anonymize=bool(config.get("LIVE_DANMAKU_ANONYMIZE", 0))) as store:
            for file in media_report["files"]:
                media = Path(file["path"])
                xml = media.with_suffix(".xml")
                if not xml.is_file():
                    continue
                segment = media.relative_to(session.root).as_posix()
                stats = {"path": str(xml), "segment_id": segment, "imported_count": 0, "duplicate_count": 0}
                try:
                    for event in read_xml(xml, segment, stats):
                        stats["imported_count" if store.append(event) else "duplicate_count"] += 1
                    video = next((s for s in file.get("streams", []) if s.get("codec_type") == "video"
                                  and not s.get("attached_pic")), {})
                    duration = round(file["duration"] * 1000) if file.get("duration", 0) > 0 else None
                    for format_ in formats:
                        events = store.iter_events(segment)
                        output = media.with_suffix("." + format_)
                        if format_ == "srt":
                            counts = export_srt(events, output, duration_ms=duration)
                        elif format_ == "ass":
                            counts = export_ass(events, output, width=video.get("width") or 1920,
                                                height=video.get("height") or 1080, duration_ms=duration)
                        else:
                            continue
                        report["outputs"].append({"path": str(output), "format": format_, **counts})
                    report["sources"].append(stats)
                except Exception as exc:
                    report["errors"].append({"source": str(xml), "error": type(exc).__name__})
        report["status"] = "partial" if report["errors"] or any(
            s.get("truncated") or s.get("rejected_count") for s in report["sources"]) else (
                "exported" if report["sources"] else "unavailable")
    except Exception as exc:
        report["status"] = "failed"
        report["errors"].append({"error": type(exc).__name__})
    # This report is intentionally separate from media success/failure.
    atomic_json(session.root / "comments-report.json", report)
    return report
