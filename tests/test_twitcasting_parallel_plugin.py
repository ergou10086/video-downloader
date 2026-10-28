import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock


YTDLP_AVAILABLE = importlib.util.find_spec("yt_dlp") is not None
PLUGIN_PATH = (
    Path(__file__).parents[1]
    / "resource"
    / "yt-dlp-plugins"
    / "video_downloader"
    / "yt_dlp_plugins"
    / "postprocessor"
    / "twitcasting_parallel.py"
)


class FakeResponse(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


class FakeDownloader:
    def __init__(self, responses):
        self.responses = responses
        self.params = {
            "concurrent_fragment_downloads": 2,
            "fragment_retries": 0,
            "ratelimit": None,
        }
        self.messages = []

    def urlopen(self, request):
        value = self.responses[request.url]
        if isinstance(value, Exception):
            raise value
        return value() if callable(value) else FakeResponse(value)

    def to_screen(self, message, *args, **kwargs):
        self.messages.append(message)

    def report_warning(self, message, *args, **kwargs):
        self.messages.append(message)

    def to_console_title(self, *args, **kwargs):
        pass

    def evaluate_outtmpl(self, template, info):
        return ''


@unittest.skipUnless(YTDLP_AVAILABLE, "yt-dlp Python package is not installed")
class TwitCastingParallelPluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("twitcasting_parallel_test", PLUGIN_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.plugin_module = module
        cls.plugin_class = module.TwitCastingParallelHlsPP
        cls.module = module

    @staticmethod
    def _responses():
        return {
            'https://cdn.example/media.m3u8': b'''#EXTM3U
#EXT-X-MAP:URI="init.0.mp4"
#EXTINF:2.0,
media.0.mp4
#EXT-X-DISCONTINUITY
#EXT-X-MAP:URI="init.1.mp4"
#EXTINF:2.0,
media.1.mp4
#EXT-X-ENDLIST
''',
            'https://cdn.example/init.0.mp4': b'init-zero',
            'https://cdn.example/init.1.mp4': b'init-one',
            'https://cdn.example/media.0.mp4': b'media-zero',
            'https://cdn.example/media.1.mp4': b'media-one',
        }

    @staticmethod
    def _info(directory):
        return {'id': '123', '_filename': str(Path(directory) / 'video.mp4'),
                'extractor_key': 'TwitCasting', 'format_id': 'source',
                'url': 'https://cdn.example/media.m3u8', 'protocol': 'm3u8_native'}

    def test_run_plans_multi_map_on_the_first_attempt(self):
        downloader = FakeDownloader(self._responses())
        with tempfile.TemporaryDirectory() as directory:
            _, result = self.plugin_class(downloader).run(self._info(directory))
            self.assertTrue(result['url'].startswith('file:'))
            self.assertEqual(result['protocol'], 'm3u8')
            self.assertEqual(len(result['_tc_parallel_cache_dirs']), 1)

    def test_ffmpeg_local_url_preserves_spaces_and_unicode_in_filename(self):
        with tempfile.TemporaryDirectory(prefix='tc 空格 ') as directory:
            _, result = self.plugin_class(FakeDownloader(self._responses())).run(self._info(directory))
            self.assertIn('tc 空格 ', result['url'])
            self.assertNotIn('%20', result['url'])
            self.assertTrue(Path(result['url'][len('file:'):]).is_file())

    def test_skip_download_never_fetches_media_in_before_dl(self):
        for option in ('skip_download', 'simulate'):
            with self.subTest(option=option), tempfile.TemporaryDirectory() as directory:
                downloader = FakeDownloader({})
                downloader.params[option] = True
                _, result = self.plugin_class(downloader).run(self._info(directory))
                self.assertNotIn('_tc_parallel_cache_dirs', result)

    def test_single_map_reuses_fetched_playlist_for_native_hls(self):
        responses = {'https://cdn.example/media.m3u8': b'''#EXTM3U
#EXT-X-MAP:URI="init.mp4"
#EXTINF:2.0,
media.mp4
#EXT-X-ENDLIST
'''}
        with tempfile.TemporaryDirectory() as directory:
            _, result = self.plugin_class(FakeDownloader(responses)).run(self._info(directory))
            self.assertEqual(result['protocol'], 'm3u8_native')
            self.assertIn('#EXTINF:', result['hls_media_playlist_data'])
            self.assertNotIn('_tc_parallel_cache_dirs', result)

    def test_legacy_single_map_entry_also_uses_native_parallel_hls(self):
        responses = {'https://cdn.example/media.m3u8': b'#EXTM3U\n#EXTINF:2.0,\nmedia.mp4\n#EXT-X-ENDLIST\n'}
        with tempfile.TemporaryDirectory() as directory:
            info = dict(self._info(directory), protocol='m3u8')
            _, result = self.plugin_class(FakeDownloader(responses)).run(info)
            self.assertEqual(result['protocol'], 'm3u8_native')

    def test_redirected_playlist_resolves_assets_against_final_url(self):
        responses = self._responses()
        body = responses['https://cdn.example/media.m3u8']

        def redirected():
            response = FakeResponse(body)
            response.url = 'https://redirected.example/vod/media.m3u8'
            return response

        responses['https://cdn.example/media.m3u8'] = redirected
        responses.update({url.replace('https://cdn.example/', 'https://redirected.example/vod/'): value
                          for url, value in self._responses().items()})
        with tempfile.TemporaryDirectory() as directory:
            _, result = self.plugin_class(FakeDownloader(responses)).run(self._info(directory))
            self.assertTrue(result['url'].startswith('file:'))

    def test_master_playlist_fetches_only_one_selected_variant(self):
        responses = self._responses()
        responses['https://cdn.example/master.m3u8'] = b'''#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=100
unselected.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=200
media.m3u8
'''
        with tempfile.TemporaryDirectory() as directory:
            info = dict(self._info(directory), url='https://cdn.example/master.m3u8')
            _, result = self.plugin_class(FakeDownloader(responses)).run(info)
            self.assertTrue(result['url'].startswith('file:'))

    def test_download_failure_keeps_verified_cache_and_never_silently_restarts_serially(self):
        responses = self._responses()
        responses['https://cdn.example/media.1.mp4'] = OSError('connection lost')
        downloader = FakeDownloader(responses)
        downloader.params['concurrent_fragment_downloads'] = 1
        with tempfile.TemporaryDirectory() as directory:
            info = self._info(directory)
            with self.assertRaises(self.module.PostProcessingError):
                self.plugin_class(downloader).run(info)
            self.assertEqual(info['protocol'], 'm3u8_native')
            self.assertTrue(list(Path(directory).glob('.tc-hls-*/completed.jsonl')))
            self.assertFalse(any('回退到 FFmpeg 串行' in msg for msg in downloader.messages))
            resumed = FakeDownloader(self._responses())
            _, result = self.plugin_class(resumed).run(self._info(directory))
            self.assertTrue(result['url'].startswith('file:'))
            self.assertTrue(any('校验后复用' in msg for msg in resumed.messages))

    def test_truncated_response_is_not_committed_to_cache(self):
        responses = self._responses()
        responses['https://cdn.example/init.0.mp4'] = lambda: FakeResponse(b'truncated', {'Content-Length': '999'})
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(self.module.PostProcessingError):
                self.plugin_class(FakeDownloader(responses)).run(self._info(directory))
            self.assertFalse(list(Path(directory).glob('.tc-hls-*/init-0001.mp4')))

    def test_same_size_corrupted_cache_is_downloaded_again(self):
        with tempfile.TemporaryDirectory() as directory:
            responses = self._responses()
            info = self._info(directory)
            _, result = self.plugin_class(FakeDownloader(responses)).run(info)
            cached = Path(result['_tc_parallel_cache_dirs'][0]) / 'media-000001.mp4'
            cached.write_bytes(b'x' * cached.stat().st_size)
            downloader = FakeDownloader(responses)
            downloader.urlopen = mock.Mock(wraps=downloader.urlopen)
            self.plugin_class(downloader).run(self._info(directory))
            self.assertEqual(cached.read_bytes(), b'media-zero')
            self.assertEqual(downloader.urlopen.call_count, 2)  # manifest + corrupted asset

    def test_changed_playlist_does_not_reuse_old_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            responses = self._responses()
            _, first = self.plugin_class(FakeDownloader(responses)).run(self._info(directory))
            responses['https://cdn.example/media.m3u8'] = responses['https://cdn.example/media.m3u8'].replace(b'#EXTINF:2.0,', b'#EXTINF:3.0,')
            _, second = self.plugin_class(FakeDownloader(responses)).run(self._info(directory))
            self.assertNotEqual(first['_tc_parallel_cache_dirs'], second['_tc_parallel_cache_dirs'])

    def test_unsupported_byte_ranges_use_explicit_ffmpeg_compatibility(self):
        responses = self._responses()
        responses['https://cdn.example/media.m3u8'] = responses['https://cdn.example/media.m3u8'].replace(b'#EXTINF:2.0,', b'#EXTINF:2.0,\n#EXT-X-BYTERANGE:100@0')
        with tempfile.TemporaryDirectory() as directory:
            downloader = FakeDownloader(responses)
            _, result = self.plugin_class(downloader).run(self._info(directory))
            self.assertEqual(result['protocol'], 'm3u8')
            self.assertEqual(result['url'], 'https://cdn.example/media.m3u8')
            self.assertTrue(any('字节范围' in msg for msg in downloader.messages))

    def test_live_and_other_platforms_are_untouched(self):
        for extra in ({'is_live': True}, {'extractor_key': 'Twitch'}):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as directory:
                info = dict(self._info(directory), **extra)
                _, result = self.plugin_class(FakeDownloader({})).run(info)
                self.assertEqual(result, info)

    def test_expired_asset_refreshes_once_and_reuses_the_same_cookie_session(self):
        class Expired(Exception):
            status = 403

        responses = self._responses()
        responses['https://cdn.example/media.0.mp4'] = Expired('expired')
        refreshed_url = 'https://fresh.example/media.m3u8'
        responses.update({url.replace('cdn.example', 'fresh.example'): body
                          for url, body in self._responses().items()})
        downloader = FakeDownloader(responses)
        downloader.extract_info = mock.Mock(return_value={'formats': [{
            'format_id': 'source', 'url': refreshed_url, 'protocol': 'm3u8_native'}]})
        with tempfile.TemporaryDirectory() as directory:
            info = dict(self._info(directory), webpage_url='https://twitcasting.tv/user/movie/123')
            _, result = self.plugin_class(downloader).run(info)
            self.assertTrue(result['url'].startswith('file:'))
            downloader.extract_info.assert_called_once_with(info['webpage_url'], download=False)

    def test_cleanup_rejects_cache_outside_output_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / 'output'
            output_dir.mkdir()
            other = Path(directory) / '.tc-hls-other'
            other.mkdir()
            info = dict(self._info(output_dir), _tc_parallel_cache_dirs=[str(other)])
            self.plugin_class(FakeDownloader({}), cleanup='true').run(info)
            self.assertTrue(other.is_dir())

    def test_single_map_playlist_is_left_for_normal_downloader(self):
        plugin = self.plugin_class(FakeDownloader({}))
        playlist = """#EXTM3U
#EXT-X-MAP:URI="init.mp4"
#EXTINF:2.0,
media.0.mp4
#EXT-X-ENDLIST
"""
        self.assertIsNone(
            plugin._build_local_playlist("https://cdn.example/path/media.m3u8", playlist)
        )

    def test_multi_map_playlist_is_rewritten_to_local_assets(self):
        plugin = self.plugin_class(FakeDownloader({}))
        playlist = """#EXTM3U
#EXT-X-MAP:URI="init.0.mp4"
#EXTINF:2.0,
media.0.mp4
#EXT-X-DISCONTINUITY
#EXT-X-MAP:URI="init.1.mp4"
#EXTINF:2.0,
media.1.mp4
#EXT-X-ENDLIST
"""
        assets, rewritten, media_count, map_count = plugin._build_local_playlist(
            "https://cdn.example/path/media.m3u8", playlist
        )
        self.assertEqual(media_count, 2)
        self.assertEqual(map_count, 2)
        self.assertEqual(len(assets), 4)
        self.assertIn('URI="init-0001.mp4"', rewritten)
        self.assertIn('URI="init-0002.mp4"', rewritten)
        self.assertIn("media-000001.mp4", rewritten)
        self.assertIn("media-000002.mp4", rewritten)

    def test_windows_local_playlist_url_keeps_unicode_path_unescaped(self):
        path = Path("E:/视频下载工具/.tc-hls-video/local.m3u8")
        with mock.patch.object(self.plugin_module.Path, "resolve", return_value=path), \
                mock.patch.object(self.plugin_module.os, "name", "nt"):
            url = self.plugin_class._local_playlist_url(path)
        self.assertEqual(url, "file:E:/视频下载工具/.tc-hls-video/local.m3u8")
        self.assertNotIn("%", url)

    def test_prepare_downloads_assets_and_cleanup_removes_only_own_cache(self):
        manifest_url = "https://cdn.example/path/media.m3u8"
        playlist = b"""#EXTM3U
#EXT-X-MAP:URI="init.0.mp4"
#EXTINF:2.0,
media.0.mp4
#EXT-X-DISCONTINUITY
#EXT-X-MAP:URI="init.1.mp4"
#EXTINF:2.0,
media.1.mp4
#EXT-X-ENDLIST
"""
        responses = {
            manifest_url: playlist,
            "https://cdn.example/path/init.0.mp4": b"init-zero",
            "https://cdn.example/path/init.1.mp4": b"init-one",
            "https://cdn.example/path/media.0.mp4": b"media-zero",
            "https://cdn.example/path/media.1.mp4": b"media-one",
        }
        downloader = FakeDownloader(responses)
        plugin = self.plugin_class(downloader)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "video.mp4"
            info = {
                "id": "123",
                "_filename": str(output),
                "extractor_key": "TwitCasting",
            }
            format_info = {
                "url": manifest_url,
                "protocol": "m3u8_native",
                "format_id": "source",
                "vcodec": "h264",
                "acodec": "aac",
            }
            cache_dir = Path(plugin._prepare_format(info, format_info))

            self.assertTrue(cache_dir.is_dir())
            self.assertTrue((cache_dir / "local.m3u8").is_file())
            self.assertEqual(format_info["protocol"], "m3u8")
            self.assertTrue(format_info["url"].startswith("file:"))
            self.assertTrue(any("2 线程" in message for message in downloader.messages))

            # A refreshed signed manifest URL must reuse the completed fragments.
            refreshed_url = "https://refreshed.example/new-token/media.m3u8"
            resumed_plugin = self.plugin_class(FakeDownloader({refreshed_url: playlist}))
            resumed_format = {
                "url": refreshed_url,
                "protocol": "m3u8_native",
                "format_id": "source",
                "vcodec": "h264",
                "acodec": "aac",
            }
            resumed_cache = Path(resumed_plugin._prepare_format(info, resumed_format))
            self.assertEqual(resumed_cache, cache_dir)

            cleanup = self.plugin_class(downloader, cleanup="true")
            info["_tc_parallel_cache_dirs"] = [str(cache_dir)]
            cleanup._cleanup_cache(info)
            self.assertFalse(cache_dir.exists())


if __name__ == "__main__":
    unittest.main()
