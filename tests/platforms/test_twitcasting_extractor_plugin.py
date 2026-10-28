from tests.helpers import PROJECT_ROOT
import importlib.util
import io
import unittest
from pathlib import Path
from unittest import mock


YTDLP_AVAILABLE = importlib.util.find_spec('yt_dlp') is not None
PLUGIN_PATH = (PROJECT_ROOT / 'resource/yt-dlp-plugins/video_downloader'
               / 'yt_dlp_plugins/extractor/twitcasting.py')


@unittest.skipUnless(YTDLP_AVAILABLE, 'yt-dlp Python package is not installed')
class TwitCastingExtractorPluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from yt_dlp.extractor.common import InfoExtractor
        from yt_dlp.utils import ExtractorError
        from yt_dlp.networking.exceptions import HTTPError
        from yt_dlp.networking.common import Response

        cls.ExtractorError = ExtractorError
        cls.HTTPError = HTTPError
        cls.Response = Response
        spec = importlib.util.spec_from_file_location('twitcasting_extractor_test', PLUGIN_PATH)
        module = importlib.util.module_from_spec(spec)
        # Import the override without registering it globally in the test process.
        with mock.patch.object(InfoExtractor, '__init_subclass__', return_value=None):
            spec.loader.exec_module(module)
        cls.module = module

    def _http_error(self, status, message='Failed to download m3u8 information'):
        response = self.Response(io.BytesIO(b''), 'https://cdn.example/master.m3u8', {}, status)
        return self.ExtractorError(message, cause=self.HTTPError(response))

    def test_m3u8_400_refreshes_once_in_existing_extractor(self):
        ie = self.module.TwitCastingIE()
        ie.report_warning = mock.Mock()
        with mock.patch.object(self.module.BaseTwitCastingIE, '_real_extract',
                               side_effect=[self._http_error(400), {'id': '123'}]) as extract:
            result = ie._real_extract('https://twitcasting.tv/user/movie/123')
        self.assertEqual(result, {'id': '123'})
        self.assertEqual(extract.call_count, 2)
        ie.report_warning.assert_called_once()

    def test_repeated_400_is_bounded(self):
        ie = self.module.TwitCastingIE()
        ie.report_warning = mock.Mock()
        with mock.patch.object(self.module.BaseTwitCastingIE, '_real_extract',
                               side_effect=self._http_error(400)) as extract:
            with self.assertRaises(self.ExtractorError):
                ie._real_extract('https://twitcasting.tv/user/movie/123')
        self.assertEqual(extract.call_count, 2)

    def test_password_errors_and_non_manifest_errors_are_not_retried(self):
        for error in (self._http_error(403), self._http_error(400, 'Downloading webpage'),
                      self.ExtractorError('use the --video-password option', expected=True)):
            with self.subTest(error=error):
                ie = self.module.TwitCastingIE()
                with mock.patch.object(self.module.BaseTwitCastingIE, '_real_extract', side_effect=error) as extract:
                    with self.assertRaises(self.ExtractorError):
                        ie._real_extract('https://twitcasting.tv/user/movie/123')
                extract.assert_called_once()

    def test_html_escaped_manifest_query_is_decoded_before_request(self):
        ie = self.module.TwitCastingIE()
        with mock.patch.object(self.module.BaseTwitCastingIE, '_extract_m3u8_formats', return_value=[]) as extract:
            ie._extract_m3u8_formats('https://cdn.example/master.m3u8?k=token&amp;spm=value', '123', 'mp4')
        extract.assert_called_once_with('https://cdn.example/master.m3u8?k=token&spm=value', '123', 'mp4')
