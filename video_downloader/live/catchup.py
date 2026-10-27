"""Evidence-based catch-up planning; failed backfill cannot own the live tail."""
from __future__ import annotations

import json
import math
import re
import subprocess
import threading
import time
from dataclasses import asdict, dataclass

from . import process
from .engines.ytdlp import YtDlpEngine
from .session import redact_command


CONTEXT_PAIRS = {"--proxy", "--cookies", "--cookies-from-browser", "--username", "--password",
                 "--video-password", "--add-header", "--add-headers", "--extractor-args",
                 "--plugin-dirs", "--js-runtimes", "--remote-components", "--user-agent",
                 "--referer", "--geo-bypass-country", "--source-address", "--ffmpeg-location"}
CONTEXT_FLAGS = {"--force-ipv4", "--force-ipv6", "--no-check-certificates", "--legacy-server-connect"}


def format_arguments(command):
    result, index = [], 1
    while index < len(command):
        value = command[index]
        if value.split('=', 1)[0] in {'-f', '--format', '-S', '--format-sort'}:
            result.append(value)
            if '=' not in value and index + 1 < len(command):
                index += 1
                result.append(command[index])
        index += 1
    return result


def context_arguments(command):
    """Reuse authentication/routing, without output, archive or download side effects."""
    result, i = [], 1
    while i < len(command):
        value = command[i]
        option = value.split("=", 1)[0]
        if option in CONTEXT_PAIRS:
            result.append(value)
            if "=" not in value and i + 1 < len(command):
                i += 1
                result.append(command[i])
        elif option in CONTEXT_FLAGS:
            result.append(value)
        i += 1
    return result


def metadata_command(command, url, *, from_start=False):
    return [command[0], "--ignore-config", *context_arguments(command), *format_arguments(command), "--simulate", "--dump-single-json",
            "--no-warnings", "--no-playlist", "--socket-timeout", "8", "--retries", "0",
            "--live-from-start" if from_start else "--no-live-from-start", url]


@dataclass(frozen=True)
class CatchUpEvidence:
    available: bool
    reason: str
    strategy: str = "live_edge"
    archive_url: str = ""
    started_at: float | None = None
    observed_at: float = 0
    window_seconds: float | None = None
    backfill_format: str = ""

    def to_dict(self):
        return asdict(self)


def assess_youtube(info):
    live = info.get("live_status") == "is_live" or info.get("is_live") is True
    formats = info.get("formats") or []
    available = live and any(f.get("is_from_start") is True and
                             str(f.get("protocol", "")).startswith("http_dash_segments") for f in formats)
    return CatchUpEvidence(available, "yt-dlp 已返回可追播 DASH；只保证平台最早可用内容，不能确认完整 DVR 窗口" if available
                           else "未探测到可追播 DASH（DVR 关闭、鉴权不足或提取失败），只能从当前录制",
                           "single_from_start" if available else "live_edge", observed_at=time.time())


class CatchUpPlanner:
    def __init__(self, runner=None, *, cancel=None, force_kill=None):
        self.runner = runner or self._run
        self.cancel, self.force_kill = cancel, force_kill

    def _run(self, command, timeout):
        deadline = time.monotonic() + timeout
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, encoding="utf-8", errors="replace", **process.hidden_options()) as proc:
            try:
                while True:
                    if self.cancel and self.cancel.is_set():
                        raise OSError("probe_cancelled")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, timeout)
                    try:
                        stdout, stderr = proc.communicate(timeout=min(0.25, remaining))
                        return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)
                    except subprocess.TimeoutExpired:
                        continue
            finally:
                if proc.poll() is None:
                    try:
                        if self.force_kill:
                            self.force_kill(proc)
                    finally:
                        if proc.poll() is None:
                            proc.kill()
                        proc.communicate(timeout=5)

    def metadata(self, command, url, *, from_start=False, timeout=20):
        result = self.runner(metadata_command(command, url, from_start=from_start), timeout)
        if result.returncode:
            raise ValueError("metadata_unavailable")
        info = json.loads(result.stdout)
        if not isinstance(info, dict):
            raise ValueError("metadata_not_object")
        return info

    def probe(self, command, url, platform, *, edge_info=None):
        if platform not in {"YouTube", "Twitch"}:
            return CatchUpEvidence(False, "该平台的追播适配尚未验证，只能从当前录制")
        try:
            if platform == "YouTube":
                return assess_youtube(self.metadata(command, url, from_start=True))
            edge = edge_info if edge_info is not None else self.metadata(command, url)
            if not (edge.get("is_live") is True or edge.get("live_status") == "is_live"):
                raise ValueError("not_live")
            archive = self.metadata(command, url, from_start=True)
            started, published = float(edge.get("timestamp", 0)), float(archive.get("timestamp", 0))
            archive_id = str(archive.get("id", ""))
            channel = str(edge.get("uploader_id", "")).lower()
            # Never backfill yesterday's latest VOD. Both channel identity and
            # current broadcast start must agree, independently of titles.
            valid = (started > 0 and math.isfinite(started) and math.isfinite(published)
                     and abs(published - started) <= 120 and re.fullmatch(r"v[0-9]+", archive_id)
                     and channel and channel == str(archive.get("uploader_id", "")).lower()
                     and any(f.get("is_from_start") for f in archive.get("formats", [])))
            if not valid:
                raise ValueError("no_matching_vod")
            # Preserve the live rendition instead of independently picking the
            # archive's best stream. Packet identity still owns final joining.
            rendition = ""
            if edge.get('height'):
                candidates = [f for f in archive.get('formats', []) if f.get('is_from_start')
                              and f.get('height') == edge['height']
                              and (not edge.get('fps') or f.get('fps') == edge['fps'])]
                if not candidates:
                    raise ValueError('matching_archive_rendition_unavailable')
                rendition = str(candidates[-1].get('format_id') or '')
            return CatchUpEvidence(True, "发现本场可访问 VOD；先录实时尾部，独立回填，重叠须经包指纹验证",
                                   "tail_and_backfill", "https://www.twitch.tv/videos/" + archive_id[1:],
                                   started, time.time(), backfill_format=rendition)
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
            reason = ("未能验证该场直播的 DVR（探测失败、权限不足或直播已结束），只能从当前录制" if platform == "YouTube"
                      else "未确认本场可访问的 VOD（探测失败或 VOD 不匹配），只能从当前录制")
            return CatchUpEvidence(False, reason,
                                   observed_at=time.time())


def at_live_edge(command):
    return [v for v in command if v not in {"--live-from-start", "--no-live-from-start"}] + ["--no-live-from-start"]


class BackfillJob:
    """One bounded auxiliary process, never published as the task's main process."""
    def __init__(self, command, evidence, session, env, force_kill):
        self.command, self.evidence, self.session = command, evidence, session
        self.env, self.force_kill = env, force_kill
        self.proc, self.thread = None, None
        self.error, self.exit_code = "", None
        self.stop_event, self.ready = threading.Event(), threading.Event()
        self.directory = session.root / "backfill"
        self.directory.mkdir()

    def start(self):
        def run():
            try:
                # Capture enough overlap past the primary launch, not the entire
                # growing VOD forever. Download/auth/output stay independently scoped.
                seconds = max(15, time.time() - self.evidence.started_at + 15)
                command = [self.command[0], "--ignore-config", *context_arguments(self.command),
                           "--live-from-start", "--download-sections", f"*0-{seconds:.3f}",
                           "--no-write-subs", "--no-write-auto-subs", "--no-write-thumbnail",
                           "--retries", "2", self.evidence.archive_url]
                # Reuse the exact format/audio processing choices from the main
                # command when possible. Different bitstreams are safely kept separate.
                command[-1:-1] = (['-f', self.evidence.backfill_format] if self.evidence.backfill_format
                                   else format_arguments(self.command))
                for option in ("-r", "--limit-rate", "-N", "--concurrent-fragments",
                               "--fragment-retries", "--ffmpeg-location"):
                    if option in self.command:
                        index = self.command.index(option)
                        command[-1:-1] = [option, self.command[index + 1]]
                command = YtDlpEngine(command).command(self.directory)
                self.session.event("backfill_start", process_cmd=redact_command(command))
                self.proc = process.spawn(command, cwd=str(self.session.root), env=self.env)
                self.ready.set()
                # communicate drains both output and final stderr without storing
                # signed URLs. A separate monitor owns cancellation and watchdog.
                while True:
                    try:
                        self.proc.communicate(timeout=0.5)
                        break
                    except subprocess.TimeoutExpired:
                        if self.stop_event.is_set():
                            process.stop(self.proc, self.force_kill, timeout=5)
                self.exit_code = self.proc.returncode
            except Exception as exc:
                self.error = type(exc).__name__
            finally:
                self.ready.set()
        self.thread = threading.Thread(target=run, name="live-backfill", daemon=True)
        self.thread.start()

    def finish(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=15)
        if self.proc and self.proc.poll() is None:
            self.force_kill(self.proc)
            if self.thread:
                self.thread.join(timeout=3)
        return {"exit_code": self.exit_code, "error": self.error,
                "retained_directory": str(self.directory)}
