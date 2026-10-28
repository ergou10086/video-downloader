import zipfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from video_downloader.core.constants import DEFAULT_CONFIG
from video_downloader.core.validation import validate_config
from video_downloader.services.storage import StorageService
from video_downloader.state.app_state import AppState


class TwitCastingPasswordStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.storage = StorageService(
            self.root,
            AppState(),
            validate_config,
            Mock(),
            Mock(),
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_save_load_update_and_delete_password_table(self):
        url = "https://twitcasting.tv/user/movie/123?from=history"
        self.assertEqual(self.storage.get_twitcasting_password(url), None)
        self.assertEqual(self.storage.save_twitcasting_password(url, "first"), {"ok": True})
        self.assertEqual(self.storage.get_twitcasting_password(url), "first")

        password_file = self.root / "twitcasting_passwords.xlsx"
        rows, normalized = self.storage._read_tc_password_xlsx(password_file)
        self.assertTrue(normalized)
        self.assertEqual(rows[url]["password"], "first")
        with zipfile.ZipFile(password_file) as archive:
            sheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn('width="60"', sheet_xml)
        self.assertIn('width="15"', sheet_xml)
        self.assertIn('width="20"', sheet_xml)
        self.assertIn('mergeCell ref="A1:C1"', sheet_xml)
        self.assertIn('autoFilter ref="A2:C102"', sheet_xml)
        self.assertIn('tableParts count="1"', sheet_xml)
        with zipfile.ZipFile(password_file) as archive:
            table_xml = archive.read("xl/tables/table1.xml").decode("utf-8")
        self.assertIn('ref="A2:C102"', table_xml)
        self.assertIn('ySplit="2"', sheet_xml)

        self.assertEqual(self.storage.save_twitcasting_password(url, "second"), {"ok": True})
        self.assertEqual(self.storage.get_twitcasting_password(url), "second")
        rows, normalized = self.storage._read_tc_password_xlsx(password_file)
        self.assertTrue(normalized)
        self.assertEqual(rows[url]["password"], "second")

        self.assertEqual(self.storage.forget_twitcasting_password(url), {"ok": True})
        self.assertIsNone(self.storage.get_twitcasting_password(url))
        rows, normalized = self.storage._read_tc_password_xlsx(password_file)
        self.assertTrue(normalized)
        self.assertEqual(rows, {})

    def test_legacy_download_password_table_is_migrated_to_root(self):
        url = "https://twitcasting.tv/user/movie/456"
        legacy_file = self.root / "download" / "twitcasting_passwords.csv"
        legacy_file.parent.mkdir(parents=True, exist_ok=True)
        legacy_file.write_text(
            "链接,密码,时间\n"
            f"{url},legacy,2026-10-27 12:00:00\n",
            encoding="utf-8-sig",
        )

        self.assertEqual(self.storage.get_twitcasting_password(url), "legacy")
        self.assertFalse(legacy_file.exists())
        self.assertTrue((self.root / "twitcasting_passwords.xlsx").exists())
        self.assertFalse(legacy_file.exists())

    def test_legacy_encoded_password_table_is_read_and_normalized(self):
        url = "https://twitcasting.tv/user/movie/789"
        password_file = self.root / "twitcasting_passwords.csv"
        password_file.write_bytes(
            ("链接,密码,时间\n"
             f"{url},旧密码,2026/10/27 12:00\n").encode("gb18030")
        )

        self.assertEqual(self.storage.get_twitcasting_password(url), "旧密码")
        self.assertTrue((self.root / "twitcasting_passwords.xlsx").exists())
        rows, normalized = self.storage._read_tc_password_xlsx(self.root / "twitcasting_passwords.xlsx")
        self.assertTrue(normalized)
        self.assertEqual(rows[url]["password"], "旧密码")
        self.assertFalse(password_file.exists())

    def test_password_table_does_not_change_application_config(self):
        state = AppState()
        state.replace_config(DEFAULT_CONFIG)
        self.assertEqual(self.storage.save_twitcasting_password("https://twitcasting.tv/a/movie/1", "pw"), {"ok": True})
        self.assertEqual(state.config_snapshot(), DEFAULT_CONFIG)


class TwitCastingPasswordExecutorHooksTests(unittest.TestCase):
    def test_save_and_forget_hooks_are_platform_scoped(self):
        from video_downloader.services.download_executor import DownloadExecutor
        save = Mock()
        forget = Mock()
        executor = DownloadExecutor(
            Path(tempfile.gettempdir()), ".exe", Mock(), Mock(), Mock(),
            Mock(), Mock(), Mock(), Mock(), Mock(), Mock(), Mock(),
            save_twitcasting_password=save,
            forget_twitcasting_password=forget,
        )
        executor._tc_config = {"TC_REMEMBER_PASSWORD":1, "TC_SAVE_PASSWORD_XLSX":1}
        executor._remember_twitcasting_password(
            "https://twitcasting.tv/a/movie/1", "TwitCasting", ["yt-dlp", "--video-password", "pw"]
        )
        executor._forget_twitcasting_password("https://twitcasting.tv/a/movie/1", "TwitCasting")
        save.assert_called_once_with("https://twitcasting.tv/a/movie/1", "pw", persist=True)
        forget.assert_called_once_with("https://twitcasting.tv/a/movie/1", persist=True)


if __name__ == "__main__":
    unittest.main()
