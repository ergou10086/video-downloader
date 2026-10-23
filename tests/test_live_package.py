import tempfile
import unittest
from pathlib import Path

from video_downloader.core.command import build_ytdlp_cmd
from video_downloader.core.constants import DEFAULT_CONFIG
from video_downloader.live import (
    LiveMode,
    LiveModeError,
    build_live_arguments,
    decide_live,
    resolve_mode,
)


class LiveModeTests(unittest.TestCase):
    def test_nicochannel_live_entries_are_classified_for_recording_and_priority(self):
        from video_downloader.live import is_live_url
        self.assertTrue(is_live_url("https://nicochannel.jp/channel/live/sm1"))
        self.assertFalse(is_live_url("https://nicochannel.jp/channel/video/sm1"))
    def test_auto_prefers_catch_up_only_for_youtube_and_twitch(self):
        self.assertEqual(resolve_mode("YouTube", "auto"), LiveMode.CATCH_UP)
        self.assertEqual(resolve_mode("Twitch", "auto"), LiveMode.CATCH_UP)
        self.assertEqual(resolve_mode("Bilibili", "auto"), LiveMode.LIVE_EDGE)
        self.assertEqual(resolve_mode("Niconico", "auto"), LiveMode.LIVE_EDGE)

    def test_explicit_catch_up_is_rejected_on_bilibili(self):
        with self.assertRaises(LiveModeError):
            resolve_mode("Bilibili", "catch_up")

    def test_conditional_platform_catch_up_needs_probe(self):
        for platform in ("Niconico", "NicoChannel", "TwitCasting", "Twitter"):
            with self.assertRaises(LiveModeError):
                resolve_mode(platform, "catch_up")

    def test_non_live_request_ignores_mode(self):
        decision = decide_live("Bilibili", "catch_up", is_live=False)
        self.assertFalse(decision.is_live)
        self.assertIsNone(decision.mode)

    def test_arguments_follow_effective_mode(self):
        self.assertEqual(build_live_arguments("YouTube", "auto", True), ("--live-from-start",))
        self.assertEqual(build_live_arguments("Bilibili", "auto", True), ("--no-live-from-start",))
        self.assertEqual(build_live_arguments("YouTube", "live_edge", True), ("--no-live-from-start",))
        self.assertEqual(build_live_arguments("Bilibili", "auto", False), ())

    def test_unknown_platform_defaults_to_live_edge(self):
        self.assertEqual(resolve_mode("Unknown", "auto"), LiveMode.LIVE_EDGE)


class LiveCommandArgumentTests(unittest.TestCase):
    def _command(self, url, platform, live_mode=None):
        with tempfile.TemporaryDirectory() as directory:
            return build_ytdlp_cmd(
                url,
                DEFAULT_CONFIG,
                Path(directory),
                is_live=True,
                live_mode=live_mode,
                platform_override=platform,
            )

    def test_bilibili_live_default_is_live_edge(self):
        cmd = self._command("https://live.bilibili.com/1", "Bilibili")
        self.assertIn("--no-live-from-start", cmd)
        self.assertNotIn("--live-from-start", cmd)
        self.assertIn("直播", cmd[cmd.index("-o") + 1])

    def test_bilibili_live_catch_up_is_rejected_before_command(self):
        with self.assertRaises(LiveModeError):
            self._command("https://live.bilibili.com/1", "Bilibili", "catch_up")

    def test_twitcasting_live_default_is_live_edge(self):
        cmd = self._command("https://twitcasting.tv/someuser", "TwitCasting")
        self.assertIn("--no-live-from-start", cmd)
        self.assertNotIn("--live-from-start", cmd)

    def test_youtube_live_edge_is_explicit(self):
        cmd = self._command("https://youtube.com/live/abc", "YouTube", "live_edge")
        self.assertIn("--no-live-from-start", cmd)
        self.assertNotIn("--live-from-start", cmd)

    def test_niconico_live_default_is_live_edge(self):
        cmd = self._command("https://live.nicovideo.jp/watch/lv1", "Niconico")
        self.assertIn("--no-live-from-start", cmd)
        self.assertNotIn("--live-from-start", cmd)


if __name__ == "__main__":
    unittest.main()
