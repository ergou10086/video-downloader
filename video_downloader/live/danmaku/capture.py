"""Parent-side supervisor. Comment children never own the media process slot."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .. import process
from ..session import atomic_json
from .preferences import enabled
from .sources import SOURCES


class CommentCapture:
    def __init__(self, session, command, config, *, force_kill, url=None):
        self.session, self.command, self.config = session, list(command), config
        self.force_kill = force_kill
        self.url = url or session.data["url"]
        self.root = session.root / "danmaku"
        self.proc = None
        self.active = enabled(config, session.data["platform"]) and session.data["platform"] in SOURCES

    def start(self):
        if not self.active:
            return
        self.root.mkdir(exist_ok=True)
        command = list(self.command)
        # yt-dlp writes its cookie jar on exit. Give the comment process its own
        # copy so it cannot race or overwrite the media engine's cookie file.
        for i, value in enumerate(command[:-1]):
            if value == "--cookies":
                cookie = self.root / "cookies.private"
                shutil.copyfile(command[i+1], cookie)
                os.chmod(cookie, 0o600)
                command[i+1] = str(cookie)
        request = self.root / "request.json"
        atomic_json(request, {"root":str(self.root), "url":self.url,
                              "platform":self.session.data["platform"], "command":command,
                              "owner_pid":os.getpid(),
                              "anonymize":bool(self.config.get("LIVE_DANMAKU_ANONYMIZE", 0))})
        os.chmod(request, 0o600)
        if getattr(sys, "frozen", False):
            args = [sys.executable, "--live-comment-worker", str(request)]
        else:
            args = [sys.executable, "-m", "video_downloader.live.danmaku.worker", str(request)]
        env = dict(os.environ)
        env["PYTHONUTF8"] = "1"
        self.proc = subprocess.Popen(args, cwd=str(Path(__file__).resolve().parents[3]) if not getattr(sys,"frozen",False) else str(Path(sys.executable).parent),
                                     env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     **process.hidden_options())

    def finish(self):
        if not self.active:
            return None
        result = {"status":"unavailable", "errors":[]}
        try:
            if self.root.exists():
                (self.root / "stop").touch()
            if self.proc and self.proc.poll() is None:
                try:
                    self.proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    self.force_kill(self.proc)
                    self.proc.wait(timeout=3)
                    result["forced_stop"] = True
            try:
                result.update(json.loads((self.root / "capture-status.json").read_text(encoding="utf-8")))
            except (OSError, ValueError):
                result.update(status="failed", errors=[{"type":"comment_worker_unavailable"}])
            if result.get("forced_stop"):
                result["status"] = "partial"
            elif result.get("status") == "running":
                result.update(status="partial", interrupted=True)
        except Exception as exc:
            result.update(status="failed", errors=[{"type":type(exc).__name__}])
        finally:
            for name in ("request.json", "cookies.private", "stop"):
                (self.root / name).unlink(missing_ok=True)
            raw = self.root / ".source"
            if raw.exists() and raw.resolve().is_relative_to(self.session.root.resolve()) and not raw.is_symlink():
                shutil.rmtree(raw)
        return result
