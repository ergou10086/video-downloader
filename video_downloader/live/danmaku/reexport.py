"""Re-export finalized owned recordings without touching media or privacy policy."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from ...core.validation import validate_config
from ..session import atomic_json
from .service import process_comments


def export_saved(root, job_id, values):
    allowed = {"LIVE_DANMAKU_FORMATS", "LIVE_DANMAKU_OFFSET_MS"}
    if not isinstance(values, dict) or values.keys() - allowed:
        return {"error": "只允许调整字幕格式和时间偏移"}
    config, errors = validate_config(values)
    if errors:
        return {"error": "；".join(str(e) for e in errors)}
    root = Path(root).resolve()
    try:
        data = json.loads((root / "session.json").read_text(encoding="utf-8"))
        report = json.loads((root / "integrity-report.json").read_text(encoding="utf-8"))
        if data.get("state") != "finished" or data.get("job_id") != job_id:
            return {"error": "只能重新导出已结束的录制"}
        settings = dict(data.get("comment_settings") or {})
        if not settings.get("LIVE_DANMAKU_ENABLED"):
            return {"error": "该次录制未启用弹幕采集"}
        media_root = (root / "media").resolve()
        if not media_root.is_relative_to(root):
            raise ValueError("invalid media root")
        paths = [Path(f["path"]) for f in report["files"]]
        paths += [Path(p["directory"]) for p in data.get("parts", [])]
        if any(not p.is_absolute() or not p.resolve().is_relative_to(media_root) for p in paths):
            raise ValueError("invalid recording path")
        # Reject links throughout the owned tree before import/export can follow
        # a sidecar, subtitle, SQLite index or fact-log link outside this job.
        if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in root.rglob("*")):
            raise ValueError("linked recording path")
        settings.update({k: config[k] for k in values})
        comments = process_comments(SimpleNamespace(root=root, data=data), report, settings)
        report["comments"] = data["comments"] = comments
        data["comment_settings"] = settings
        atomic_json(root / "integrity-report.json", report)
        atomic_json(root / "session.json", data)
        return {"ok": True, "comments": comments}
    except (OSError, ValueError, KeyError, TypeError):
        return {"error": "录制记录不可用或包含无效路径"}
