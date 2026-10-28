import tempfile
import threading
import time
import unittest
from pathlib import Path
from queue import Queue
from unittest.mock import Mock, patch

from video_downloader.services.download_executor import DownloadExecutor
from video_downloader.services.download_manager import DownloadManager
from video_downloader.state.app_state import AppState


from tests.helpers.archive import ArchiveFixture


class ArchiveChoiceTests(ArchiveFixture, unittest.TestCase):
    def test_skip_is_not_success_and_preserves_archive(self):
        self.outputs([["[download] abc: has already been recorded in the archive"]])
        self.run_single()
        self.assertEqual(self.state.batch_stats["ok"], 0)
        self.assertEqual(self.state.batch_stats["skipped"], 1)
        self.assertEqual(self.callbacks["add_history"].call_args.args[3], "skipped")
        self.assertEqual(self.archive.read_text(), "youtube abc\nyoutube other\n")
        self.assertEqual(self.executor._spawn.call_count, 1)
        self.assertIsNone(self.state.archive_prompt)
        self.assertFalse(self.manager.snapshot()["running"])

    def test_redownload_only_forgets_selected_ids_and_reuses_output_path(self):
        self.choice = True
        self.outputs([
            ["[download] abc: has already been recorded in the archive"],
            [f"[download] Destination: {self.root / 'video.mp4'}", "[download] 100.0%"],
        ])
        self.run_single()
        retry = self.executor._spawn.call_args.args[0]
        self.assertIn("--force-overwrites", retry)
        self.assertIn("--no-continue", retry)
        self.assertEqual(retry[retry.index("-o") + 1], self.command[self.command.index("-o") + 1])
        self.assertEqual(self.archive.read_text(), "youtube other\n")
        self.assertEqual(self.state.batch_stats["ok"], 1)
        self.assertEqual(len(self.prompt_calls()), 1)

    def test_failed_redownload_does_not_mark_success_or_record_stale_archive_again(self):
        self.choice = True
        self.outputs([["[download] abc: has already been recorded in the archive"], ["ERROR: network failed"]], [0, 1])
        self.run_single()
        self.assertEqual(self.state.batch_stats["fail"], 1)
        self.assertEqual(self.state.batch_stats["ok"], 0)
        self.assertNotIn("youtube abc", self.archive.read_text())

    def test_mixed_playlist_does_not_prompt_again_for_other_already_downloaded_items(self):
        self.choice = True
        self.outputs([
            ["[download] abc: has already been recorded in the archive", f"[download] Destination: {self.root / 'other.mp4'}"],
            ["[download] other: has already been recorded in the archive", f"[download] Destination: {self.root / 'video.mp4'}"],
        ])
        self.run_single()
        self.assertEqual(len(self.prompt_calls()), 1)
        self.assertEqual(self.archive.read_text(), "youtube other\n")
        self.assertEqual(self.state.batch_stats["ok"], 1)

    def test_timeout_is_enforced_by_backend_without_any_client_response(self):
        self.assertEqual(self.executor.ARCHIVE_CHOICE_TIMEOUT, 20)
        self.executor.ARCHIVE_CHOICE_TIMEOUT = 0.03
        self.callbacks["emit_event"].side_effect = None
        handle = self.manager.begin("single")
        started = time.monotonic()
        self.assertFalse(self.executor._wait_for_archive_choice(handle, "url", "YouTube", {"abc"}))
        self.assertLess(time.monotonic() - started, 1)
        self.assertIsNone(self.state.archive_prompt)
        request_id = self.prompt_calls()[0].args[1]["request_id"]
        self.assertIn("error", self.executor.submit_archive_choice(request_id, True))

    def test_stopping_wait_releases_task_and_rejects_old_response(self):
        ready = threading.Event()
        self.callbacks["emit_event"].side_effect = lambda event, data: ready.set() if event == "archive_choice_required" else None
        handle = self.manager.begin("single")
        results = []
        worker = threading.Thread(target=lambda: results.append(self.executor._wait_for_archive_choice(handle, "url", "YouTube", {"abc"})))
        worker.start()
        try:
            self.assertTrue(ready.wait(1))
            request_id = self.state.archive_prompt["request_id"]
            self.assertTrue(self.executor.stop_download()["stopped"])
        finally:
            handle.cancel_event.set()
            worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results, [False])
        self.assertIsNone(self.state.archive_prompt)
        self.manager.begin("single")
        self.assertIn("error", self.executor.submit_archive_choice(request_id, True))

    def test_headless_archive_skip_never_waits_for_a_dialog(self):
        self.state.sse_clients.clear()
        handle = self.manager.begin("single")
        self.assertFalse(self.executor._wait_for_archive_choice(handle, "url", "YouTube", {"abc"}))
        self.assertEqual(len(self.prompt_calls()), 0)

    def test_batch_skip_continues_to_next_url_without_counting_success(self):
        self.outputs([
            ["[download] abc: has already been recorded in the archive"],
            [f"[download] Destination: {self.root / 'next.mp4'}"],
        ])
        handle = self.manager.begin("batch")
        self.state.batch_stats.update(total=2, current=0)
        self.executor._run_batch(handle, [self.command[-1], "https://youtube.com/watch?v=next"], self.state.config, self.state.batch_stats)
        self.assertEqual(self.state.batch_stats, {"ok": 1, "fail": 0, "total": 2, "current": 2, "skipped": 1})
        self.assertEqual(self.executor._spawn.call_count, 2)
        self.assertFalse(self.manager.snapshot()["running"])

    def test_batch_redownload_does_not_disable_archive_for_following_urls(self):
        self.choice = True
        self.outputs([
            ["[download] abc: has already been recorded in the archive"],
            [f"[download] Destination: {self.root / 'video.mp4'}"],
            [f"[download] Destination: {self.root / 'next.mp4'}"],
        ])
        handle = self.manager.begin("batch")
        self.state.batch_stats.update(total=2, current=0)
        self.executor._run_batch(handle, [self.command[-1], "https://youtube.com/watch?v=next"], self.state.config, self.state.batch_stats)
        commands = [call.args[0] for call in self.executor._spawn.call_args_list]
        self.assertIn("--force-overwrites", commands[1])
        self.assertNotIn("--force-overwrites", commands[2])
        self.assertTrue(all("--download-archive" in command for command in commands))
        self.assertEqual(self.state.batch_stats["ok"], 2)

    def test_explicit_audio_replacement_does_not_create_numbered_copy(self):
        video = self.root / "video.mp4"
        video.write_bytes(b"video")
        audio = self.root / "video.mp3"
        audio.write_bytes(b"old audio")
        process = Mock(returncode=0)
        process.poll.return_value = 0
        done = threading.Event()
        done.set()
        self.executor._start_reader = Mock(return_value=(Queue(), done))
        with patch("video_downloader.services.download_executor.subprocess.Popen", return_value=process) as popen:
            self.assertTrue(self.executor._extract_audio_from_video(str(video), "mp3", overwrite=True))
        self.assertEqual(popen.call_args.args[0][-1], str(audio))
        self.assertFalse((self.root / "video_1.mp3").exists())
