"""Managed Withny watch configuration; original credentials/config remain untouched."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ..danmaku.dependencies import library
from ..danmaku.timeline import epoch
from ..session import media_files
from . import EngineFeatures


class WithnyEngine:
    name = "withny-dl"
    features = EngineFeatures(managed_outputs=True, per_file_tracks=True, annotate_report=True,
                              original_working_directory=True, concatenate=False)

    def __init__(self, command, session, config_path, comments):
        self.original, self.session = list(command), session
        self.config_path = Path(config_path)
        self.cwd = self.config_path.parent
        self.comments = comments
        self.private = session.root / "withny.private.yaml"
        self.audio_channels = set()

    def command(self, directory):
        if self.config_path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("withny_config_too_large")
        yaml = library("ruamel.yaml").YAML(typ="safe", pure=True)
        data = yaml.load(self.config_path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or not isinstance(data.get("channels"), dict) or not data["channels"]:
            raise ValueError("withny_channels_required")
        if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", str(key)) for key in data["channels"]):
            raise ValueError("invalid_withny_channel")
        defaults = data.get("defaultParams") or {}
        if not isinstance(defaults, dict):
            raise ValueError("invalid_withny_defaults")
        common = {"writeChat":self.comments, "writeMetaDataJson":True, "concat":False,
                  "keepIntermediates":True, "deleteCorrupted":False, "scanDirectory":str(directory),
                  "outFormat":str(directory / "{{ .ChannelID }}" / "{{ .MetaData.Stream.UUID }}.{{ .Ext }}")}
        data["defaultParams"] = dict(defaults, **common)
        for channel, params in data["channels"].items():
            if params is not None and not isinstance(params, dict):
                raise ValueError("invalid_withny_channel_params")
            params = params or {}
            quality = params.get("qualityConstraint", defaults.get("qualityConstraint", {})) or {}
            if quality.get("audioOnly"):
                self.audio_channels.add(str(channel))
            data["channels"][channel] = dict(params, **common)
        with self.private.open("w", encoding="utf-8", newline="\n") as output:
            yaml.dump(data, output)
        os.chmod(self.private, 0o600)
        command = list(self.original)
        index = command.index("--config")
        command[index + 1] = str(self.private)
        return command

    def output_files(self, root):
        preferred = {}
        for path in media_files(root):
            audio = path.suffix.lower() in {".m4a", ".mp3", ".aac", ".wav"}
            key = (str(path.with_suffix("")), audio)
            rank = {".mkv":4, ".mp4":3, ".m4a":3, ".ts":1}.get(path.suffix.lower(), 0)
            if key not in preferred or rank > preferred[key][0]:
                preferred[key] = (rank, path)
        return sorted(pair[1] for pair in preferred.values())

    def expected_tracks(self, path):
        path = Path(path)
        return "a" if path.suffix.lower() in {".m4a", ".mp3", ".aac", ".wav"} or any(
            part in self.audio_channels for part in path.parts) else "av"

    def annotate(self, report):
        for file in report["files"]:
            path = Path(file["path"]).with_suffix(".info.json")
            try:
                if path.stat().st_size > 2 * 1024 * 1024:
                    continue
                info = json.loads(path.read_text(encoding="utf-8"))
                stream = info.get("Stream") or info.get("stream") or {}
                stamp = epoch(stream.get("StartedAt") or stream.get("startedAt"))
                if stamp is not None:
                    file["programme_started_at"] = stamp
                # StartedAt is programme start, not the start of a recording
                # that joined mid-stream. Metadata is written immediately
                # before media recording by the native engine.
                file["anchor_utc"] = path.stat().st_mtime
                file["anchor_source"] = "withny_metadata_write_estimate"
            except (OSError, ValueError, TypeError):
                pass

    def stop_recording(self):
        return

    def close(self):
        self.private.unlink(missing_ok=True)
