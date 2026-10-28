"""Shared archive prompt fixture, without inheriting or collecting test cases."""
import tempfile
import threading
from pathlib import Path
from queue import Queue
from unittest.mock import Mock

from video_downloader.services.download_executor import DownloadExecutor
from video_downloader.services.download_manager import DownloadManager
from video_downloader.state.app_state import AppState


class ArchiveFixture:
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.archive = self.root / "archive.txt"
        self.archive.write_text("youtube abc\nyoutube other\n")
        self.command = ["yt-dlp", "--download-archive", str(self.archive), "-o", str(self.root / "video.mp4"), "https://youtube.com/watch?v=abc"]
        self.manager = DownloadManager()
        self.state = AppState(config={"PLATFORM": "YouTube"})
        self.state.sse_clients.append(Queue())
        self.choice = False
        self.callbacks = {name: Mock() for name in (
            "log", "update_progress", "broadcast_download_state", "add_history",
            "cancel_idle_timer", "start_idle_timer", "emit_event",
        )}
        self.callbacks["emit_event"].side_effect = self.answer_prompt
        self.executor = DownloadExecutor(
            self.root, ".exe", self.state, self.manager,
            build_command=Mock(side_effect=lambda url, **kwargs: [*self.command[:-1], url]),
            **self.callbacks,
        )
        self.executor._missing_dependency = Mock(return_value=None)
        self.state.batch_stats.update(ok=0, fail=0, total=1, current=1)

    def answer_prompt(self, event, data):
        if event == "archive_choice_required":
            result = self.executor.submit_archive_choice(data["request_id"], self.choice)
            self.assertTrue(result["ok"])

    def outputs(self, scripts, returncodes=None):
        codes = returncodes or [0] * len(scripts)
        processes = []
        readers = []
        for lines, code in zip(scripts, codes):
            process = Mock(returncode=code)
            process.poll.return_value = code
            processes.append(process)
            queue = Queue()
            for line in lines:
                queue.put(line)
            done = threading.Event()
            done.set()
            readers.append((queue, done))
        self.executor._spawn = Mock(side_effect=processes)
        self.executor._start_reader = Mock(side_effect=readers)

    def run_single(self):
        handle = self.manager.begin("single")
        self.executor._run_single(handle, self.command, self.command[-1], "YouTube", False)

    def prompt_calls(self):
        return [call for call in self.callbacks["emit_event"].call_args_list if call.args[0] == "archive_choice_required"]
