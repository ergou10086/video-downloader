import os
import tempfile
import unittest
from pathlib import Path

from video_downloader.core.paths import AppPaths


class AppPathsTests(unittest.TestCase):
    def test_runtime_directories_use_clean_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = AppPaths(directory)
            paths.ensure_runtime_dirs()
            self.assertTrue(paths.dependency_dir.is_dir())
            self.assertTrue(paths.archive_dir.is_dir())
            self.assertTrue(paths.log_dir.is_dir())
            self.assertTrue((paths.download_dir / "YouTube").is_dir())
            self.assertTrue((paths.download_dir / "NicoChannel").is_dir())
            self.assertTrue((paths.download_dir / "Withny").is_dir())

    def test_canonical_dependency_wins_over_legacy_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = AppPaths(root)
            paths.dependency_dir.mkdir()
            canonical = paths.dependency_dir / "yt-dlp.exe"
            legacy = root / "yt-dlp.exe"
            canonical.touch()
            legacy.touch()
            self.assertEqual(paths.executable("yt-dlp", ".exe"), canonical)

    def test_legacy_dependency_is_used_when_canonical_copy_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "ffmpeg.exe"
            legacy.touch()
            self.assertEqual(AppPaths(root).executable("ffmpeg", ".exe"), legacy)

    def test_subprocess_path_starts_with_dependency_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = AppPaths(directory)
            env = paths.subprocess_env({"PATH": "existing"})
            self.assertEqual(env["PATH"].split(os.pathsep)[0], str(paths.dependency_dir))
            self.assertTrue(env["PATH"].endswith("existing"))


if __name__ == "__main__":
    unittest.main()
