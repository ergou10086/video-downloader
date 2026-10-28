"""Regression coverage for PR #15 features combined with live recording."""

import tempfile
import threading
import unittest
from pathlib import Path
from queue import Queue
from unittest.mock import Mock, patch

from tests.helpers.archive import ArchiveFixture
from tests.helpers.download import DirectThread, ImmediateThread, create_executor


LIVE_FROM_START_ERROR = (
    "ERROR: [BiliLive] 1963655121: --live-from-start is passed, "
    "but there are no formats that can be downloaded from the start. "
    "If you want to download from the current time, use --no-live-from-start"
)


class ProviderLiveIntegrationTests(unittest.TestCase):
    def test_provider_preparation_hands_auth_to_existing_live_runner(self):
        for batch in (False, True):
            with self.subTest(batch=batch), tempfile.TemporaryDirectory() as directory:
                executor, callbacks = create_executor(Path(directory))
                executor._missing_dependency = Mock(return_value=None)
                config = dict(executor._app_state.config_snapshot(), YOUTUBE_PO_TOKEN_ENABLED=1, LIVE_MODE="live_edge")
                executor._app_state.config_snapshot = Mock(return_value=config)
                base = "http://[::1]:4416"
                callbacks["ensure_po_token_provider"].return_value = {"ok":True, "base_url":base}
                callbacks["build_command"].side_effect = lambda url, **kwargs: ["yt-dlp", "--extractor-args", "youtubepot-bgutilhttp:base_url="+kwargs["po_token_base_url"], url]
                executor._run_live = Mock()
                with patch("video_downloader.services.download_executor.threading.Thread", DirectThread):
                    result = executor.batch_download(["https://youtube.com/live/example"]) if batch else executor.start_download("https://youtube.com/live/example")
                self.assertTrue(result["ok"])
                callbacks["ensure_po_token_provider"].assert_called_once()
                executor._run_live.assert_called_once()
                self.assertIn("youtubepot-bgutilhttp:base_url="+base, executor._run_live.call_args.args[1])
                self.assertEqual(executor._effective_live_mode, "live_edge")
                self.assertFalse(executor._download_manager.snapshot()["running"])


class ArchiveLiveIntegrationTests(ArchiveFixture, unittest.TestCase):
    def _assert_redownload_survives_live_fallback(self, *, batch):
        self.choice = True
        url = "https://twitcasting.tv/user/movie/123"
        target = self.root / "video.mp4"
        target.touch()
        self.archive.write_text("twitcasting 123\ntwitcasting other\n", encoding="utf-8")
        self.command = ["yt-dlp", "--continue", "--no-overwrites", "--use-postprocessor", "TwitCastingParallelHls:when=before_dl",
                        "--download-archive", str(self.archive), "-o", str(target), url]
        self.outputs([
            ["[download] 123: has already been recorded in the archive"],
            ["KeyError: TwitCastingParallelHlsPP"],
            [f"[download] Destination: {target}", "[download] 100.0%"],
        ], [0, 1, 0])
        self.executor._extract_audio_from_video = Mock()
        handle = self.manager.begin("batch" if batch else "single")
        if batch:
            self.executor._run_batch(handle, [url], {"PLATFORM":"TwitCasting"}, self.state.batch_stats, audio_mode="2")
        else:
            self.executor._run_single(handle, self.command, url, "TwitCasting", False, audio_mode="2")
        self.assertEqual(self.executor._spawn.call_count, 3)
        for call in self.executor._spawn.call_args_list[1:]:
            command = call.args[0]
            self.assertIn("--force-overwrites", command)
            self.assertIn("--no-continue", command)
            self.assertNotIn("--no-overwrites", command)
        last = self.executor._spawn.call_args.args[0]
        self.assertNotIn("TwitCastingParallelHls:when=before_dl", last)
        self.assertEqual(last[last.index("--downloader")+1], "m3u8:ffmpeg")
        self.assertEqual(len(self.prompt_calls()), 1)
        self.assertEqual(self.archive.read_text(), "twitcasting other\n")
        self.executor._extract_audio_from_video.assert_called_once()
        self.assertTrue(self.executor._extract_audio_from_video.call_args.kwargs["overwrite"])
        self.assertEqual(self.state.batch_stats["ok"], 1)
        self.assertEqual(self.state.batch_stats["fail"], 0)
        self.assertFalse(self.manager.snapshot()["running"])

    def test_single_archive_redownload_keeps_overwrite_after_twitcasting_plugin_fallback(self):
        self._assert_redownload_survives_live_fallback(batch=False)

    def test_batch_archive_redownload_keeps_overwrite_after_twitcasting_plugin_fallback(self):
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
