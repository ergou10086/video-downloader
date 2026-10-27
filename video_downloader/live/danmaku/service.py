"""Post-recording sidecar pipeline: independent failures and per-media anchors."""
from __future__ import annotations

from pathlib import Path
from dataclasses import replace

from ..session import atomic_json
from .bilibili import read_xml
from .exporter_ass import export_ass
from .exporter_srt import export_srt
from .store import CommentStore
from .preferences import enabled
from .timeline import project
from .withny import read_chat


def process_comments(session, media_report, config):
    platform = session.data.get("platform", "")
    if not enabled(config, platform):
        return {"status": "disabled"}
    capture = session.data.get("comment_capture") or {}
    report = {"status": "unavailable", "sources": [], "outputs": [], "errors": [], "capture":capture,
              "anchor_error_ms": None, "anchor_note": "保留源时间与时钟来源；未知误差不等于零误差"}
    root = session.root / "danmaku"
    try:
        formats = str(config.get("LIVE_DANMAKU_FORMATS", "srt,ass")).split(",")
        with CommentStore(root, anonymize=bool(config.get("LIVE_DANMAKU_ANONYMIZE", 0))) as store:
            for file in media_report["files"]:
                media = Path(file["path"])
                segment = media.relative_to(session.root).as_posix()
                xml = media.with_suffix(".xml") if platform == "Bilibili" else None
                chat = next((p for p in [media.with_suffix(".chat.json"), media.with_suffix(".comments.json")]
                             if platform == "Withny" and p.is_file()), None)
                source = xml if xml and xml.is_file() else chat
                if source is None and not capture:
                    continue
                stats = {"path": str(source) if source else str(root / "events.jsonl"), "segment_id": segment,
                         "imported_count": 0, "duplicate_count": 0}
                try:
                    if source:
                        reader = read_xml if platform == "Bilibili" else read_chat
                        for event in reader(source, segment, stats):
                            stats["imported_count" if store.append(event) else "duplicate_count"] += 1
                    native_relative = platform == "Bilibili" and source
                    source_segment = segment if source else "_timeline"
                    part = next((p for p in session.data.get("parts", [])
                                 if media.is_relative_to(Path(p["directory"]))), {})
                    anchor = file.get("anchor_utc", part.get("media_started_at", part.get("started_at")))
                    source_count = store.count(source_segment)
                    stats["event_count"] = source_count
                    video = next((s for s in file.get("streams", []) if s.get("codec_type") == "video"
                                  and not s.get("attached_pic")), {})
                    duration = round(file["duration"] * 1000) if file.get("duration", 0) > 0 else None
                    for format_ in formats:
                        events = store.iter_events(source_segment)
                        offset = int(config.get("LIVE_DANMAKU_OFFSET_MS", 0))
                        if native_relative:
                            events = (replace(e, relative_ms=e.relative_ms + offset) for e in events)
                        else:
                            events = project(events, segment=segment, anchor_utc=anchor,
                                             mode=session.data.get("mode"), platform=platform, duration_ms=duration,
                                             offset_ms=offset, stats=stats,
                                             clock_ranges=file.get('comment_clock', {}).get('ranges', []))
                        output = media.with_suffix("." + format_)
                        if format_ == "srt":
                            counts = export_srt(events, output, duration_ms=duration)
                        elif format_ == "ass":
                            counts = export_ass(events, output, width=video.get("width") or 1920,
                                                height=video.get("height") or 1080, duration_ms=duration)
                        else:
                            continue
                        if counts["exported_count"]:
                            report["outputs"].append({"path": str(output), "format": format_, **counts})
                        else:
                            output.unlink(missing_ok=True)
                            report.setdefault("empty_exports", []).append({"format":format_, **counts})
                    report["sources"].append(stats)
                except Exception as exc:
                    report["errors"].append({"source": str(source), "error": type(exc).__name__})
        uncertain = any(s.get('clock_estimated_count') or (s.get("event_count") and s.get("anchor_source") in {
            "clock_estimate", "programme_relative_unverified_head"}) for s in report["sources"])
        report['sync'] = {key:sum(s.get(key, 0) for s in report['sources'])
                          for key in ('clock_verified_count', 'clock_estimated_count', 'unmapped_count')}
        report['sync']['scope'] = 'sampled_media_clock_mapping'
        report['sync']['manual_offset_ms'] = int(config.get('LIVE_DANMAKU_OFFSET_MS', 0))
        errors = [s['anchor_error_ms'] for s in report['sources'] if s.get('anchor_error_ms') is not None]
        if errors and not uncertain and not report['sync']['unmapped_count']:
            report['anchor_error_ms'] = max(errors)
        report["status"] = "partial" if report["errors"] or uncertain or capture.get("status") in {"failed","partial","unavailable"} or any(
            s.get("truncated") or s.get("rejected_count") for s in report["sources"]) else (
                "exported" if report["outputs"] else "empty" if report["sources"] else "unavailable")
    except Exception as exc:
        report["status"] = "failed"
        report["errors"].append({"error": type(exc).__name__})
    # This report is intentionally separate from media success/failure.
    atomic_json(session.root / "comments-report.json", report)
    return report
