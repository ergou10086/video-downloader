"""Lifecycle management for the local BgUtils YouTube PO Token provider."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from collections import deque
from urllib.request import ProxyHandler, build_opener

from video_downloader.core.paths import AppPaths


class PoTokenProviderService:
    """Start the bundled BgUtils HTTP provider on demand and stop owned processes."""

    HOST = "127.0.0.1"
    PORT = 4416
    START_TIMEOUT = 60.0
    PROGRESS_INTERVAL = 5.0

    def __init__(self, tool_dir, log):
        self._tool_dir = tool_dir
        self._paths = AppPaths(tool_dir)
        self._log = log
        self._lock = threading.RLock()
        self._shutdown = threading.Event()
        self._process = None
        self._output_tail = deque(maxlen=30)
        self._active_base_url = None

    @property
    def base_url(self):
        return self._active_base_url or f"http://{self.HOST}:{self.PORT}"

    @property
    def _candidate_base_urls(self):
        # Upstream currently binds to "::". Some Windows systems expose that socket
        # on IPv4 too, while others only accept ::1, so probe both loopback families.
        candidates = (
            f"http://{self.HOST}:{self.PORT}",
            f"http://[::1]:{self.PORT}",
        )
        if self._active_base_url in candidates:
            return (self._active_base_url, *(
                url for url in candidates if url != self._active_base_url
            ))
        return candidates

    def _ping(self, timeout=0.25):
        try:
            # Provider health checks must never inherit a system/user proxy.
            opener = build_opener(ProxyHandler({}))
            for base_url in self._candidate_base_urls:
                try:
                    with opener.open(f"{base_url}/ping", timeout=timeout) as response:
                        if response.status != 200:
                            continue
                        data = json.loads(response.read(4096).decode("utf-8"))
                    if (
                        isinstance(data, dict)
                        and isinstance(data.get("version"), str)
                        and data["version"]
                    ):
                        self._active_base_url = base_url
                        return data
                except Exception:
                    continue
            return None
        except Exception:
            return None

    @staticmethod
    def _windows_process_options():
        if os.name != "nt":
            return None, 0
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        return startupinfo, subprocess.CREATE_NO_WINDOW

    def _drain_output(self, process, output_tail):
        try:
            for line in iter(process.stdout.readline, ""):
                line = line.strip()
                if line:
                    output_tail.append(line)
        except Exception:
            pass
        finally:
            try:
                process.stdout.close()
            except Exception:
                pass

    def _dependency_error(self):
        deno = self._paths.executable("deno", ".exe" if os.name == "nt" else "")
        server_dir = self._paths.dependency("bgutil-ytdlp-pot-provider/server")
        node_modules = server_dir / "node_modules"
        main_script = server_dir / "src" / "main.ts"
        plugin = self._paths.dependency("yt-dlp-plugins/bgutil-ytdlp-pot-provider.zip")
        missing = []
        for path, label in (
            (deno, "dependency/deno.exe" if os.name == "nt" else "dependency/deno"),
            (main_script, "dependency/bgutil-ytdlp-pot-provider/server/src/main.ts"),
            (node_modules, "dependency/bgutil-ytdlp-pot-provider/server/node_modules"),
            (plugin, "dependency/yt-dlp-plugins/bgutil-ytdlp-pot-provider.zip"),
        ):
            if not path.exists():
                missing.append(label)
        if missing:
            return "PO Token Provider 缺少依赖: " + "、".join(missing)
        return None

    def ensure_running(self, cancel_event=None):
        """Ensure readiness within a deadline, without interactive dependency setup."""
        started = time.monotonic()
        deadline = started + self.START_TIMEOUT

        def cancelled():
            return self._shutdown.is_set() or (
                cancel_event is not None and cancel_event.is_set()
            )

        # Another task may still be cleaning up its cancelled cold start.
        # Waiting for that task must also be cancellable and bounded.
        while not self._lock.acquire(timeout=0.1):
            if cancelled():
                return {"cancelled": True}
            if time.monotonic() >= deadline:
                return {"error": "等待 PO Token Provider 启动锁超时，请重试"}
        try:
            if cancelled():
                return {"cancelled": True}
            self._log("[PO Token] 正在检查本地 Provider...", "info")
            ping = self._ping()
            if ping:
                if self._process is None:
                    self._log(
                        f"[PO Token] 已连接现有 Provider v{ping['version']} ({self.base_url})",
                        "success",
                    )
                return {
                    "ok": True,
                    "version": ping["version"],
                    "reused": True,
                    "base_url": self.base_url,
                }

            error = self._dependency_error()
            if error:
                return {"error": error}

            if self._process is not None and self._process.poll() is None:
                # A process exists but stopped answering; terminate it before restarting.
                self._stop_owned_process(self._process)
                self._process = None

            deno = self._paths.executable("deno", ".exe" if os.name == "nt" else "")
            node_modules = self._paths.dependency(
                "bgutil-ytdlp-pot-provider/server/node_modules"
            )
            command = [
                str(deno),
                "run",
                "--no-prompt",
                "--cached-only",
                "--node-modules-dir=manual",
                "--allow-env",
                "--allow-net",
                "--allow-sys",
                "--allow-ffi=.",
                "--allow-read=.",
                "../src/main.ts",
                "--port",
                str(self.PORT),
            ]
            startupinfo, creationflags = self._windows_process_options()
            self._output_tail = deque(maxlen=30)
            self._log(
                f"[PO Token] 正在启动 Provider，首次加载可能较慢（最多 {self.START_TIMEOUT:g} 秒，可停止）...",
                "info",
            )
            try:
                env = self._paths.subprocess_env()
                env["DENO_NO_UPDATE_CHECK"] = "1"
                process = subprocess.Popen(
                    command,
                    cwd=node_modules,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    startupinfo=startupinfo,
                    creationflags=creationflags,
                )
            except Exception as exc:
                return {"error": f"PO Token Provider 启动失败: {exc}"}

            self._process = process
            reader = threading.Thread(
                target=self._drain_output,
                args=(process, self._output_tail),
                daemon=True,
            )
            try:
                reader.start()
            except Exception as exc:
                self._stop_owned_process(process)
                self._process = None
                process.stdout.close()
                return {"error": f"PO Token Provider 日志线程启动失败: {exc}"}

            next_progress = time.monotonic() + self.PROGRESS_INTERVAL
            while time.monotonic() < deadline:
                if cancelled():
                    self._stop_owned_process(process)
                    self._process = None
                    reader.join(timeout=0.2)
                    return {"cancelled": True}
                ping = self._ping()
                if ping:
                    self._log(
                        f"[PO Token] Provider v{ping['version']} 已启动 ({self.base_url})",
                        "success",
                    )
                    return {
                        "ok": True,
                        "version": ping["version"],
                        "reused": False,
                        "base_url": self.base_url,
                    }
                if process.poll() is not None:
                    reader.join(timeout=0.2)
                    detail = self._failure_detail()
                    self._process = None
                    return {"error": f"PO Token Provider 启动后异常退出{detail}"}
                now = time.monotonic()
                if now >= next_progress:
                    self._log(f"[PO Token] 等待 Provider 就绪，已用 {now - started:.0f} 秒...", "info")
                    next_progress = now + self.PROGRESS_INTERVAL
                if cancel_event is not None:
                    cancel_event.wait(0.2)
                else:
                    self._shutdown.wait(0.2)

            self._stop_owned_process(process)
            self._process = None
            reader.join(timeout=0.2)
            detail = self._failure_detail()
            return {"error": f"PO Token Provider 启动超时，无法访问 {self.base_url}/ping{detail}"}
        finally:
            self._lock.release()

    def _failure_detail(self):
        if not self._output_tail:
            return ""
        output = "\n".join(tuple(self._output_tail))[:2000]
        return f"（{output}）"

    @staticmethod
    def _stop_owned_process(process):
        if process is None or process.poll() is not None:
            return
        if os.name == "nt":
            startupinfo, creationflags = PoTokenProviderService._windows_process_options()
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    capture_output=True,
                    timeout=2,
                    startupinfo=startupinfo,
                    creationflags=creationflags,
                )
            except Exception:
                pass
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=2)
            except Exception:
                try:
                    process.kill()
                    process.wait(timeout=2)
                except Exception:
                    pass

    def stop(self):
        """Stop only a provider process started by this application."""
        # Wake an in-flight startup before waiting for its lifecycle lock.
        self._shutdown.set()
        with self._lock:
            process = self._process
            self._process = None
            if process is None:
                return
            self._stop_owned_process(process)
            self._log("[PO Token] Provider 已停止", "info")
