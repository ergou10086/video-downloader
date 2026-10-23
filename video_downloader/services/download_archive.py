"""Scoped archive invalidation for an explicitly requested re-download."""

from __future__ import annotations

import os
import re
import tempfile
import threading
from pathlib import Path


_TASK_ARCHIVE_LOCK = threading.RLock()


class TaskArchiveSession:
    """Give concurrent yt-dlp processes private archives, then merge their deltas.

    This also isolates explicit re-download invalidation: replacing the shared
    archive while another process appends to it can otherwise lose records.
    Legacy execution is excluded while task sessions are active by the container.
    """

    def __init__(self, tool_dir):
        self._tool_dir = Path(tool_dir)
        self._archives = {}

    def prepare(self, command):
        result = list(command)
        archive = None
        position = None
        inline = False
        for index, value in enumerate(result):
            if value == "--no-download-archive":
                archive = position = None
            elif value == "--download-archive" and index + 1 < len(result):
                archive, position, inline = result[index + 1], index + 1, False
            elif value.startswith("--download-archive="):
                archive, position, inline = value.split("=", 1)[1], index, True
        if archive is None:
            return result
        shared = Path(archive)
        if not shared.is_absolute():
            shared = self._tool_dir / shared
        shared = shared.resolve()
        with _TASK_ARCHIVE_LOCK:
            if shared not in self._archives:
                shared.parent.mkdir(parents=True, exist_ok=True)
                original = shared.read_text(encoding="utf-8-sig").splitlines() if shared.exists() else []
                descriptor, name = tempfile.mkstemp(prefix=".task-archive-", suffix=".tmp", dir=shared.parent)
                with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                    output.write("".join(line + "\n" for line in original))
                self._archives[shared] = (Path(name), set(original))
            private, _ = self._archives[shared]
        result[position] = "--download-archive=" + str(private) if inline else str(private)
        return result

    def finish(self):
        try:
            with _TASK_ARCHIVE_LOCK:
                for shared, (private, original) in self._archives.items():
                    final = private.read_text(encoding="utf-8-sig").splitlines()
                    added, removed = set(final) - original, original - set(final)
                    if not added and not removed:
                        continue
                    current = shared.read_text(encoding="utf-8-sig").splitlines() if shared.exists() else []
                    merged = [line for line in current if line not in removed]
                    existing = set(merged)
                    merged.extend(line for line in dict.fromkeys(final) if line in added and line not in existing)
                    descriptor, name = tempfile.mkstemp(prefix=".archive-merge-", suffix=".tmp", dir=shared.parent)
                    try:
                        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                            output.write("".join(line + "\n" for line in merged))
                            output.flush()
                            os.fsync(output.fileno())
                        os.replace(name, shared)
                    finally:
                        Path(name).unlink(missing_ok=True)
        finally:
            for private, _ in self._archives.values():
                private.unlink(missing_ok=True)
            self._archives.clear()


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
