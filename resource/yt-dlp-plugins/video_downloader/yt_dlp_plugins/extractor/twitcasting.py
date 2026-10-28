"""Refresh rejected TwitCasting VOD manifests within the existing session."""

import html

from yt_dlp.extractor.twitcasting import TwitCastingIE as BaseTwitCastingIE
from yt_dlp.utils import ExtractorError


class TwitCastingIE(BaseTwitCastingIE, plugin_name='video_downloader'):
    def _extract_m3u8_formats(self, m3u8_url, *args, **kwargs):
        # Sources embedded in HTML attributes may contain escaped query separators.
        return super()._extract_m3u8_formats(html.unescape(m3u8_url), *args, **kwargs)

    def _real_extract(self, url):
        for attempt in range(2):
            try:
                return super()._real_extract(url)
            except ExtractorError as error:
                if (attempt or getattr(error.cause, 'status', None) != 400
                        or 'm3u8' not in error.orig_msg.lower()):
                    raise
                error.cause.response.close()
                self.report_warning(
                    'm3u8 返回 400，使用当前会话重新取得播放地址一次')
