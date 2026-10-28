"""Download executor factories and controlled process/thread doubles."""
import threading
from unittest.mock import Mock

from video_downloader.services.download_executor import DownloadExecutor
from video_downloader.services.download_manager import DownloadManager


class FakeAppState:
    def __init__(self):
        self.download_thread_context = threading.local()
        self.sse_clients = []
        self.batch_stats = {}

    def config_snapshot(self):
        return {
            "PLATFORM": "YouTube",
            "USE_COOKIES": 0,
            "COOKIE_MODE": 1,
            "BROWSER_NAME": "chrome",
            "BROWSER_PROFILE": "Default",
            "PROXY_ENABLED": 0,
            "PROXY_TYPE": "http",
            "PROXY_ADDR": "127.0.0.1",
            "PROXY_PORT": "7890",
        }

    def publish(self, event):
        for client in self.sse_clients:
            client.put_nowait(event)

    def has_sse_clients(self):
        return bool(self.sse_clients)


def create_executor(tool_dir, manager=None):
    callbacks = {
        "build_command": Mock(return_value=["yt-dlp"]),
        "log": Mock(),
        "update_progress": Mock(),
        "broadcast_download_state": Mock(),
        "add_history": Mock(),
        "cancel_idle_timer": Mock(),
        "start_idle_timer": Mock(),
        "emit_event": Mock(),
        "pick_withny_archive": Mock(return_value={"ok": True, "cancelled": True}),
        "pick_withny_live_config": Mock(return_value={"ok": True, "cancelled": True}),
        "ensure_po_token_provider": Mock(return_value={"ok": True}),
    }
    executor = DownloadExecutor(
        tool_dir=tool_dir,
        exe_suffix=".exe",
        app_state=FakeAppState(),
        download_manager=manager or DownloadManager(),
        **callbacks,
    )
    return executor, callbacks


class ImmediateThread:
    def __init__(self, target, args=(), daemon=None):
        self.target = target
        self.args = args

    def start(self):
        pass


class FailingThread(ImmediateThread):
    def start(self):
        raise RuntimeError("thread unavailable")


class DirectThread(ImmediateThread):
    def start(self):
        self.target(*self.args)


class FakeProcess:
    def __init__(self, running=True):
        self.pid = 42
        self.running = running
        self.stdout = Mock()
        self.kill = Mock(side_effect=self._kill)

    def _kill(self):
        self.running = False

    def poll(self):
        return None if self.running else 0

    def wait(self, timeout=None):
        if self.running:
            raise TimeoutError()
        return 0


class CompletedProcess:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.stdout = Mock()

    def poll(self):
        return self.returncode


class PlaylistProcess:
    def __init__(self, stdout="", stderr="", returncode=0, timeout=False):
        self.stdout_output = stdout
        self.stderr_output = stderr
        self.returncode = returncode
        self.timeout = timeout

    def communicate(self, timeout=None):
        if self.timeout:
            raise __import__("subprocess").TimeoutExpired("yt-dlp", timeout)
        return self.stdout_output, self.stderr_output
