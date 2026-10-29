"""RPlay public VOD and read-only live inspection.

Protocol observations and validation boundaries: docs/rplay-integration.md.
Use yt-dlp's own networking, proxy routing and HLS downloader; no account tokens
are accepted, generated or persisted by this adapter.
"""

import re
from urllib.parse import urlsplit

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import ExtractorError, float_or_none, parse_iso8601

__all__ = ['RplayVodIE', 'RplayLiveIE', 'RplayUnsupportedIE']

_OID = r'[0-9a-fA-F]{24}'
_SITE = r'https://(?:www\.)?rplay\.live(?::443)?'
_END = r'/?(?:[?#].*)?$'
_HEADERS = {'Origin': 'https://rplay.live', 'Referer': 'https://rplay.live/'}


def _media_url(value):
    """Only accept HTTPS playback endpoints belonging to RPlay."""
    if not isinstance(value, str):
        return None
    if any(character.isspace() or ord(character) < 32 for character in value):
        return None
    try:
        parts = urlsplit(value)
        host = (parts.hostname or '').lower()
        if (parts.scheme == 'https' and not parts.username and not parts.password
                and parts.port in (None, 443)
                and (host == 'rplay.live' or host.endswith('.rplay.live'))):
            return value
    except ValueError:
        pass
    return None


def _check_hls(document):
    if not isinstance(document, str) or not document.lstrip('\ufeff').startswith('#EXTM3U'):
        raise ExtractorError('Rplay 返回的播放清单无效', expected=True)
    for tag in re.findall(r'^#EXT-X-(?:SESSION-)?KEY:(.*)', document, re.M):
        attributes = dict(re.findall(r'([A-Z0-9-]+)=("[^"]*"|[^,\s]+)', tag))
        method = attributes.get('METHOD', '').strip('"')
        keyformat = attributes.get('KEYFORMAT', 'identity').strip('"')
        if method not in {'NONE', 'AES-128'} or keyformat != 'identity':
            raise ExtractorError('Rplay DRM 或非标准加密暂不支持', expected=True)


class _RplayBaseIE(InfoExtractor):
    def _json(self, path, resource_id, query):
        try:
            result = self._download_json(
                'https://api.rplay.live/' + path, resource_id,
                headers={**_HEADERS, 'Authorization': 'null'}, query=query,
                note='读取 Rplay 状态')
        except ExtractorError as exc:
            # Exception bodies and URLs can contain credential data. Only expose
            # the HTTP status; do not attach the original exception as a cause.
            status = getattr(exc.cause, 'status', None)
            message = {
                401: 'Rplay login required：需要登录',
                403: 'Rplay private：没有观看权限',
                404: 'Rplay 内容不存在或已删除',
                429: 'Rplay HTTP 429：请求过于频繁，请稍后重试',
            }.get(status, f'Rplay 请求失败（HTTP {status}）' if status else 'Rplay 网络请求失败')
            raise ExtractorError(message, expected=True) from None
        if not isinstance(result, dict):
            raise ExtractorError('Rplay 响应结构无效', expected=True)
        return result


class RplayVodIE(_RplayBaseIE):
    IE_NAME = 'rplay:vod'
    _VALID_URL = _SITE + r'/play/(?P<id>' + _OID + ')' + _END

    def _real_extract(self, url):
        video_id = self._match_id(url).lower()
        info = self._json('content', video_id, {
            'contentOid': video_id, 'status': 'published',
            'requestCanView': 'true', 'lang': 'en',
        })
        if info.get('_id') != video_id:
            raise ExtractorError('Rplay 点播身份与请求不一致', expected=True)
        if info.get('drm') is not False:
            raise ExtractorError('Rplay DRM 或未知加密类型暂不支持', expected=True)
        if info.get('deleted') is True:
            raise ExtractorError('Rplay 内容已删除', expected=True)
        if info.get('waitingEncoding') is True:
            raise ExtractorError('Rplay 点播仍在转码，请稍后重试', expected=True)
        access = info.get('canView')
        if not isinstance(access, dict) or access.get('canView') is not True:
            # A URL may be a preview even when the full resource is inaccessible.
            raise ExtractorError('Rplay login required：此内容需要登录或订阅，尚未接入账号授权', expected=True)
        media_url = _media_url(access.get('url'))
        if not media_url:
            raise ExtractorError('Rplay 没有有效的授权播放地址', expected=True)
        if access.get('mediaType') != 'video/mp4' or 'hlsstream' not in urlsplit(media_url).path:
            raise ExtractorError('Rplay 当前仅支持已验证的 HLS 点播', expected=True)
        try:
            document = self._download_webpage(media_url, video_id, headers=_HEADERS,
                                              note='读取 Rplay HLS 清单')
            _check_hls(document)
            formats, _ = self._parse_m3u8_formats_and_subtitles(
                document, media_url, ext='mp4', m3u8_id='hls',
                entry_protocol='m3u8_native', headers=_HEADERS, video_id=video_id)
        except ExtractorError:
            # Keep signed query strings out of the caller's logs/SSE/history.
            raise ExtractorError('Rplay HLS 清单不可用或包含不支持的加密', expected=True) from None
        formats = [item for item in formats if not item.get('has_drm') and _media_url(item.get('url'))]
        if not formats:
            raise ExtractorError('Rplay 没有可下载的普通 HLS 格式', expected=True)
        for item in formats:
            dimensions = [float_or_none(item.get(axis)) for axis in ('width', 'height')]
            if all(value is not None and value > 0 for value in dimensions):
                item['rplay_resolution'] = min(dimensions)
        creator = info.get('creatorInfo')
        creator = creator if isinstance(creator, dict) else {}
        return {
            'id': video_id,
            'title': info.get('title') or video_id,
            'description': info.get('introText'),
            'uploader': creator.get('nickname') or info.get('creatorNickname'),
            'uploader_id': info.get('creatorOid'),
            'timestamp': parse_iso8601(info.get('createdAt')),
            'release_timestamp': parse_iso8601(info.get('publishedAt')),
            'duration': float_or_none(info.get('length')),
            'thumbnail': f'https://pb.rplay.live/thumbnail/{video_id}',
            'age_limit': 18 if info.get('isAdultContent') or info.get('hideContent') else 0,
            'formats': formats,
            'subtitles': {},
            'http_headers': dict(_HEADERS),
            'webpage_url': f'https://rplay.live/play/{video_id}',
        }


class RplayLiveIE(_RplayBaseIE):
    IE_NAME = 'rplay:live'
    _VALID_URL = _SITE + r'/(?:live|creatorhome)/(?P<id>' + _OID + ')' + _END

    def _real_extract(self, url):
        if self._configuration_arg('inspect', default=['0']) != ['1']:
            raise ExtractorError('Rplay 直播录制尚未完成真实验收', expected=True)
        creator_id = self._match_id(url).lower()
        info = self._json('live/play', creator_id, {'creatorOid': creator_id, 'lang': 'en'})
        if info.get('creatorOid') != creator_id:
            raise ExtractorError('Rplay 直播身份与请求不一致', expected=True)
        state = info.get('streamState')
        if state not in {'offline', 'live'}:
            raise ExtractorError('Rplay 转播或未知直播状态尚未接入', expected=True)
        if state == 'live' and (info.get('allowAnonymous') is not True or info.get('accessible') is not True):
            raise ExtractorError('Rplay private：直播需要登录或没有观看权限', expected=True)
        started = parse_iso8601(info.get('streamStartTime')) if state == 'live' else None
        if state == 'live' and started is None:
            raise ExtractorError('Rplay 直播缺少有效的场次时间', expected=True)
        creator = info.get('creatorMetadata')
        creator = creator if isinstance(creator, dict) else {}
        return {
            'id': creator_id,
            'title': info.get('title') or creator_id,
            'uploader': creator.get('nickname'),
            'timestamp': started,
            'live_status': 'is_live' if state == 'live' else 'not_live',
            'formats': [],
            'webpage_url': f'https://rplay.live/live/{creator_id}',
        }


class RplayUnsupportedIE(InfoExtractor):
    IE_NAME = 'rplay:unsupported'
    _VALID_URL = _SITE + r'(?:/.*)?$'

    @classmethod
    def suitable(cls, url):
        return not (RplayVodIE.suitable(url) or RplayLiveIE.suitable(url)) and super().suitable(url)

    def _real_extract(self, url):
        raise ExtractorError('Rplay 暂不支持此链接，请使用单个 /play/ 点播链接', expected=True)
