"""Scoped archive invalidation for an explicitly requested re-download."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path


def archived_video_id(line):
    # yt-dlp releases differ: some include a title between the ID and message.
    match = re.match(r"\[download\] (.+?): .*?has already been recorded in the archive\b", line)
    return match.group(1) if match else None


def forget_archived_videos(command, video_ids, tool_dir):
    """Atomically forget only the selected IDs; yt-dlp records successes again."""
    archive = None
    for index, value in enumerate(command):
        if value == "--no-download-archive":
            archive = None
        elif value == "--download-archive" and index + 1 < len(command):
            archive = command[index + 1]
        elif value.startswith("--download-archive="):
            archive = value.split("=", 1)[1]
    if not archive:
        raise ValueError("未找到本次下载使用的归档文件，无法安全重新下载")
    path = Path(archive)
    if not path.is_absolute():
        path = Path(tool_dir) / path
    lines = path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    selected = set(video_ids)
    retained = []
    for line in lines:
        fields = line.split(maxsplit=1)
        if len(fields) != 2 or fields[1].strip() not in selected:
            retained.append(line)
    if len(retained) == len(lines):
        raise ValueError("归档中已找不到对应视频记录，请重新提交下载")
    descriptor, name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.writelines(retained)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def redownload_command(command):
    """Reuse the configured output paths and replace same-name damaged files."""
    conflicts = {"--no-overwrites", "--no-force-overwrites", "--force-overwrites", "--continue", "--no-continue", "-c", "-w"}
    result = [value for value in command if value not in conflicts]
    return [result[0], "--force-overwrites", "--no-continue", *result[1:]]
