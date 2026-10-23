import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_downloader.services.download_archive import TaskArchiveSession, archived_video_id, forget_archived_videos, redownload_command


class DownloadArchiveTests(unittest.TestCase):
    def test_task_sessions_merge_concurrent_additions_and_scoped_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "archive.txt"
            archive.write_text("youtube remove\nyoutube retain\n")
            first, second = TaskArchiveSession(directory), TaskArchiveSession(directory)
            cmd = ["yt-dlp", "--download-archive", str(archive), "url"]
            one, two = first.prepare(cmd), second.prepare(cmd)
            self.assertNotEqual(one[2], two[2])
            self.assertEqual(first.prepare(cmd)[2], one[2])
            Path(one[2]).write_text("youtube retain\nyoutube first\n")
            Path(two[2]).write_text("youtube remove\nyoutube retain\nyoutube second\n")
            first.finish()
            second.finish()
            self.assertEqual(archive.read_text().splitlines(), ["youtube retain", "youtube first", "youtube second"])
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_task_session_merge_failure_preserves_archive_and_cleans_private_files(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "archive.txt"
            archive.write_text("youtube original\n")
            session = TaskArchiveSession(directory)
            command = session.prepare(["yt-dlp", "--download-archive=archive.txt", "url"])
            Path(command[1].split("=", 1)[1]).write_text("youtube original\nyoutube added\n")
            with patch("video_downloader.services.download_archive.os.replace", side_effect=OSError("locked")):
                with self.assertRaises(OSError):
                    session.finish()
            self.assertEqual(archive.read_text(), "youtube original\n")
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_only_archive_skip_messages_are_detected(self):
        self.assertEqual(archived_video_id("[download] 077e4JKDEiQ: has already been recorded in the archive"), "077e4JKDEiQ")
        self.assertEqual(archived_video_id("[download] abc: A title: with punctuation has already been recorded in the archive"), "abc")
        self.assertIsNone(archived_video_id("[download] video.mp4 has already been downloaded"))

    def test_forgetting_selected_ids_preserves_other_records_and_uses_effective_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "archive.txt"
            path.write_text("\ufeffyoutube abc\nyoutube xyz\n\nyoutube\txyz2\nyoutube abc\n", encoding="utf-8")
            command = ["yt-dlp", "--download-archive", "unused.txt", "--download-archive=archive.txt", "url"]
            forget_archived_videos(command, {"abc"}, directory)
            self.assertEqual(path.read_text(), "youtube xyz\n\nyoutube\txyz2\n")
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_failed_atomic_replace_keeps_original_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "archive.txt"
            path.write_text("youtube abc\nyoutube xyz\n")
            with patch("video_downloader.services.download_archive.os.replace", side_effect=OSError("locked")):
                with self.assertRaises(OSError):
                    forget_archived_videos(["yt-dlp", "--download-archive", str(path), "url"], {"abc"}, directory)
            self.assertEqual(path.read_text(), "youtube abc\nyoutube xyz\n")
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_missing_record_cannot_trigger_unscoped_archive_bypass(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "archive.txt"
            path.write_text("youtube other\n")
            with self.assertRaises(ValueError):
                forget_archived_videos(["yt-dlp", "--download-archive", str(path), "url"], {"abc"}, directory)
            with self.assertRaises(ValueError):
                forget_archived_videos(["yt-dlp", "--download-archive", str(path), "--no-download-archive", "url"], {"abc"}, directory)
            self.assertEqual(path.read_text(), "youtube other\n")

    def test_redownload_keeps_output_template_archive_and_authentication(self):
        command = ["yt-dlp", "--continue", "--no-overwrites", "--download-archive", "archive.txt", "-o", "same [%(id)s].%(ext)s", "--cookies", "cookies.txt", "url"]
        result = redownload_command(command)
        self.assertNotIn("--continue", result)
        self.assertNotIn("--no-overwrites", result)
        self.assertIn("--force-overwrites", result)
        self.assertIn("--no-continue", result)
        self.assertEqual(result[result.index("-o") + 1], command[command.index("-o") + 1])
        self.assertEqual(result[result.index("--download-archive") + 1], "archive.txt")
        self.assertIn("cookies.txt", result)
        self.assertEqual(result[-1], "url")

    def test_redownload_preserves_options_added_after_url_by_recovery(self):
        command = ["yt-dlp", "url", "--downloader", "m3u8:ffmpeg", "--extractor-args", "value"]
        result = redownload_command(command)
        self.assertEqual(result[result.index("--extractor-args") + 1], "value")
        self.assertEqual(result[result.index("--downloader") + 1], "m3u8:ffmpeg")
