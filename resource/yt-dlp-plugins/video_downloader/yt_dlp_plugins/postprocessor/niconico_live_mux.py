"""Keep upstream Niconico seat heartbeat while muxing live A/V concurrently.

yt-dlp normally downloads different niconico_live formats sequentially.
For an unbounded live stream, the second (audio) download never starts.
"""
from functools import wraps

from yt_dlp.downloader.niconico import NiconicoLiveFD
from yt_dlp.postprocessor.common import PostProcessor


def install_mux_adapter():
    original = NiconicoLiveFD.real_download
    if getattr(original, '_video_downloader_mux', False):
        return

    @wraps(original)
    def download(self, filename, info):
        formats = info.get('_video_downloader_niconico_formats')
        if formats:
            # The upstream downloader owns WebSocket keepSeat/reconnection and
            # delegates both HLS inputs to its own FFmpegFD in one invocation.
            info = dict(info, requested_formats=[dict(f, protocol='m3u8') for f in formats])
        return original(self, filename, info)

    download._video_downloader_mux = True
    NiconicoLiveFD.real_download = download


class NiconicoLiveMuxPP(PostProcessor):
    def run(self, info):
        formats = info.get('requested_formats') or []
        if (not info.get('is_live') or len(formats) < 2
                or any(f.get('protocol') != 'niconico_live' for f in formats)):
            return [], info
        if self.get_param('simulate') or self.get_param('skip_download'):
            return [], info
        install_mux_adapter()
        # A single native downloader owns the combined output; suppress yt-dlp's
        # sequential multi-format path and its separate-file merger.
        info['_video_downloader_niconico_formats'] = info.pop('requested_formats')
        info['protocol'] = 'niconico_live'
        info['url'] = formats[0]['url']
        return [], info
