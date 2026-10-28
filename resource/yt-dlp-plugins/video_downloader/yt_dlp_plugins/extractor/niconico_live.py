"""Expose broadcast state hidden by upstream's unconditional is_live flag."""
import json
from html.parser import HTMLParser

from yt_dlp.extractor.niconico import NiconicoLiveIE as BaseNiconicoLiveIE


class ProgrammeData(HTMLParser):
    def __init__(self):
        super().__init__()
        self.status = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('id') == 'embedded-data':
            try:
                self.status = json.loads(attrs.get('data-props', '{}')).get('program', {}).get('status')
            except (ValueError, AttributeError):
                pass


class NiconicoLiveIE(BaseNiconicoLiveIE, plugin_name='video_downloader'):
    def _download_webpage_handle(self, *args, **kwargs):
        result = super()._download_webpage_handle(*args, **kwargs)
        if result and isinstance(result[0], str) and 'embedded-data' in result[0]:
            parser = ProgrammeData()
            parser.feed(result[0])
            if parser.status:
                self._broadcast_status = parser.status
        return result

    def _real_extract(self, url):
        self._broadcast_status = None
        info = super()._real_extract(url)
        status = self._broadcast_status
        if status == 'ENDED':
            info.update(is_live=False, live_status='was_live')
        elif status == 'ON_AIR':
            info.update(is_live=True, live_status='is_live')
        return info
