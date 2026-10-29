"""Application policies for the public RPlay HLS adapter."""

import re
from urllib.parse import urlsplit, urlunsplit


def format_selector(config):
    """Keep the resolution ceiling in every fallback, including muxed HLS.

    The resolution label denotes the shorter edge, as in yt-dlp's resolution
    sorting. RPlay also publishes portrait videos (e.g. 720x1280).
    """
    if str(config.get('AUDIO_MODE', '0')) == '1':
        raise ValueError('Rplay HLS 暂不支持分离音画，请选择合并、同时输出音频或只输出音频')
    resolution = str(config['RESOLUTION'])
    bounds = [''] if resolution == 'best' else [f'[rplay_resolution<={resolution}]']
    codec = {'h264': "[vcodec~='avc1|h264']", 'av1': "[vcodec~='av01']", 'vp9': "[vcodec~='vp9']"}.get(config['CODEC'], '')
    audio = 'bestaudio' + (f"[abr<={config['AUDIO_QUALITY']}]" if config['AUDIO_QUALITY'] != 'best' else '')
    selectors = []
    for preference in ([codec, ''] if codec else ['']):
        selectors.extend(f'bestvideo{bound}{preference}+{audio}' for bound in bounds)
        selectors.extend(f'best{bound}{preference}' for bound in bounds)
    return '/'.join(selectors)


def sanitize_output(value):
    """Remove signed queries/headers before a subprocess line enters UI/logs."""
    def clean(match):
        try:
            parts = urlsplit(match.group())
            return urlunsplit((parts.scheme, parts.hostname or '', parts.path, '', ''))
        except ValueError:
            return '[播放地址已隐藏]'
    value = re.sub(r'https?://[^\s\'"<>]+', clean, value)
    value = re.sub(r'(?i)([\'\"]?(?:authorization|refresh[-_]?token|key2|token)[\'\"]?\s*[=:]\s*[\'\"]?)(?:Bearer\s+)?[^\s,;\'"<>]+', r'\1***', value)
    return re.sub(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '***', value)
