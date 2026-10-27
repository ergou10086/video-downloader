"""Regression coverage for PR #15 features combined with live recording."""

import tempfile
import threading
import unittest
from pathlib import Path
from queue import Queue
from unittest.mock import Mock, patch

from tests import test_archive_choice as archive_helpers
from tests.test_download_executor import DirectThread, ImmediateThread, create_executor


LIVE_FROM_START_ERROR = (
    "ERROR: [BiliLive] 1963655121: --live-from-start is passed, "
    "but there are no formats that can be downloaded from the start. "
    "If you want to download from the current time, use --no-live-from-start"
)


class ProviderLiveIntegrationTests(unittest.TestCase):
    def test_provider_preparation_then_wait_and_record_keeps_access_options(self):
        for batch in (False, True):
            with self.subTest(batch=batch), tempfile.TemporaryDirectory() as directory:
                executor, callbacks = create_executor(Path(directory))
                executor._missing_dependency = Mock(return_value=None)
                config = dict(
                    executor._app_state.config_snapshot(),
                    YOUTUBE_PO_TOKEN_ENABLED=1,
                    LIVE_RECORD_MODE="wait",
                    LIVE_WATCH_INTERVAL=5,
                )
                executor._app_state.config_snapshot = Mock(return_value=config)
                url = "https://www.youtube.com/live/example"
                base_url = "http://[::1]:4416"
                extractor_args = f"youtubepot-bgutilhttp:base_url={base_url}"
                stages = []

                def prepare_provider(cancel_event):
                    stages.append("provider")
                    cancel_event.wait = Mock(return_value=False)
                    return {"ok": True, "base_url": base_url}

                def build_command(target, **kwargs):
                    command = ["yt-dlp"]
                    if kwargs.get("po_token_base_url"):
                        command += [
                            "--extractor-args",
                            "youtubepot-bgutilhttp:base_url=" + kwargs["po_token_base_url"],
                        ]
                    return command + [target]

                callbacks["ensure_po_token_provider"].side_effect = prepare_provider
                callbacks["build_command"].side_effect = build_command
                processes = []
                for status in ("is_upcoming", "is_live"):
                    process = Mock(returncode=0)
                    process.poll.return_value = 0
                    process.communicate.return_value = ('{"live_status":"' + status + '"}', "")
                    processes.append(process)
                recording = Mock(returncode=0)
                recording.poll.return_value = 0
                processes.append(recording)

                def spawn(command):
                    stages.append("probe" if "--dump-single-json" in command else "record")
                    return processes.pop(0)

                executor._spawn = Mock(side_effect=spawn)
                output = Queue()
                output.put(f"[download] Destination: {Path(directory) / 'recording.mp4'}")
                done = threading.Event()
                done.set()
                executor._start_reader = Mock(return_value=(output, done))
                executor._close_process = Mock()

                with patch.object(executor, "_probe_live_status", wraps=executor._probe_live_status) as probe:
                    with patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                        result = executor.batch_download([url]) if batch else executor.start_download(url)

                self.assertTrue(result["ok"])
                self.assertEqual(stages, ["provider", "probe", "probe", "record"])
                callbacks["ensure_po_token_provider"].assert_called_once()
                cancel_event = callbacks["ensure_po_token_provider"].call_args.kwargs["cancel_event"]
                self.assertTrue(all(call.args[2] is cancel_event for call in probe.call_args_list))
                cancel_event.wait.assert_called_once_with(5)
                self.assertFalse(cancel_event.is_set())
                self.assertEqual(executor._spawn.call_count, 3)
                for call in executor._spawn.call_args_list:
                    self.assertIn(extractor_args, call.args[0])
                    self.assertEqual(call.args[0][-1], url)
                self.assertTrue(all(
                    call.kwargs["po_token_base_url"] == base_url
                    for call in callbacks["build_command"].call_args_list
                ))
                self.assertEqual(executor._app_state.batch_stats["ok"], 1)
                self.assertEqual(executor._app_state.batch_stats["fail"], 0)
                self.assertFalse(executor._download_manager.snapshot()["running"])


class ArchiveLiveIntegrationTests(unittest.TestCase):
    # Reuse the archive fixture and its scripted-process helper without inheriting
    # its test class, so unittest only runs the integration cases defined here.
    setUp = archive_helpers.ArchiveChoiceTests.setUp
    answer_prompt = archive_helpers.ArchiveChoiceTests.answer_prompt
    outputs = archive_helpers.ArchiveChoiceTests.outputs
    prompt_calls = archive_helpers.ArchiveChoiceTests.prompt_calls

    def _assert_redownload_survives_live_fallback(self, *, batch):
        self.choice = True
        url = "https://live.bilibili.com/1963655121"
        target = self.root / "video.mp4"
        target.touch()
        self.archive.write_text("bilibili 1963655121\nbilibili other\n", encoding="utf-8")
        self.command = [
            "yt-dlp", "--continue", "--no-overwrites", "--live-from-start",
            "--download-archive", str(self.archive), "-o", str(target), url,
        ]
        self.outputs([
            ["[download] 1963655121: has already been recorded in the archive"],
            [LIVE_FROM_START_ERROR],
            [
                "[download] other: has already been recorded in the archive",
                f"[download] Destination: {target}",
                "[download] 100.0%",
            ],
        ], [0, 1, 0])
        self.executor._extract_audio_from_video = Mock()
        handle = self.manager.begin("batch" if batch else "single")
        if batch:
            self.executor._run_batch(
                handle, [url], {"PLATFORM": "Bilibili", "LIVE_RECORD_MODE": "from_start"},
                self.state.batch_stats, audio_mode="2",
            )
        else:
            self.executor._run_single(
                handle, self.command, url, "Bilibili", True, audio_mode="2",
            )

        self.assertEqual(self.executor._spawn.call_count, 3)
        retry_commands = [call.args[0] for call in self.executor._spawn.call_args_list[1:]]
        self.assertIn("--live-from-start", retry_commands[0])
        self.assertNotIn("--live-from-start", retry_commands[1])
        for command in retry_commands:
            self.assertIn("--force-overwrites", command)
            self.assertIn("--no-continue", command)
            self.assertNotIn("--no-overwrites", command)
            self.assertNotIn("--continue", command)
            self.assertEqual(command[command.index("-o") + 1], str(target))
        self.assertEqual(len(self.prompt_calls()), 1)
        self.assertEqual(self.archive.read_text(encoding="utf-8"), "bilibili other\n")
        self.executor._extract_audio_from_video.assert_called_once()
        self.assertTrue(self.executor._extract_audio_from_video.call_args.kwargs["overwrite"])
        self.assertEqual(self.state.batch_stats["ok"], 1)
        self.assertEqual(self.state.batch_stats["fail"], 0)
        self.assertEqual(self.state.batch_stats.get("skipped", 0), 0)
        self.assertEqual(self.callbacks["add_history"].call_args.args[3], "success")
        self.assertIsNone(self.state.archive_prompt)
        self.assertFalse(self.manager.snapshot()["running"])

    def test_single_archive_redownload_keeps_overwrite_after_live_fallback(self):
        self._assert_redownload_survives_live_fallback(batch=False)

    def test_batch_archive_redownload_keeps_overwrite_after_live_fallback(self):
        self._assert_redownload_survives_live_fallback(batch=True)

    def _assert_new_task_resets_skipped(self, *, batch):
        self.outputs([["[download] abc: has already been recorded in the archive"]])
        handle = self.manager.begin("single")
        self.executor._run_single(handle, self.command, self.command[-1], "YouTube", False)
        self.assertEqual(self.state.batch_stats.get("skipped", 0), 1)
        self.assertFalse(self.manager.snapshot()["running"])

        with patch("video_downloader.services.download_executor.threading.Thread", ImmediateThread):
            result = (
                self.executor.batch_download(["https://www.twitch.tv/videos/123"])
                if batch else self.executor.start_download("https://www.twitch.tv/videos/123")
            )

        self.assertTrue(result["ok"])
        self.assertEqual(self.state.batch_stats.get("skipped", 0), 0)
        self.assertEqual(self.state.batch_stats["ok"], 0)
        self.assertEqual(self.state.batch_stats["fail"], 0)
        self.assertEqual(self.state.batch_stats["total"], 1)
        events = []
        client = self.state.sse_clients[0]
        while not client.empty():
            events.append(client.get_nowait())
        stats_events = [event["data"] for event in events if event["type"] == "stats"]
        self.assertTrue(stats_events)
        self.assertEqual(stats_events[-1].get("skipped", 0), 0)

    def test_new_single_task_clears_previous_archive_skip(self):
        self._assert_new_task_resets_skipped(batch=False)

    def test_new_batch_task_clears_previous_archive_skip(self):
        self._assert_new_task_resets_skipped(batch=True)


if __name__ == "__main__":
    unittest.main()
