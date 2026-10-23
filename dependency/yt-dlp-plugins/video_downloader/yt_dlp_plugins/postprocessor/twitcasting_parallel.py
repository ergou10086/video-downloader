"""Plan TwitCasting VOD downloads before selecting the HLS downloader.

Single-map VODs retain native HLS. Multi-map VODs use resumable, bounded
parallel transfers followed by local FFmpeg muxing. Network failures keep the
verified cache and fail explicitly rather than silently restarting serially.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from yt_dlp.networking import Request
from yt_dlp.postprocessor.common import PostProcessor
from yt_dlp.utils import PostProcessingError, parse_m3u8_attributes


_URI_ATTRIBUTE_RE = re.compile(r'(?P<prefix>\bURI=)(?P<quote>["\']?)(?P<uri>.*?)(?P=quote)(?=,|$)')
_SAFE_COMPONENT_RE = re.compile(r'[^A-Za-z0-9_.-]+')
_MEDIA_EXTENSIONS = {'.aac', '.m4a', '.m4s', '.mp4', '.ts'}
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_MAX_ASSETS = 50_000


class _UnsupportedPlaylist(ValueError):
    """A valid playlist whose semantics must be handled by FFmpeg remotely."""


class _DownloadLimiter:
    """Best-effort aggregate limiter matching yt-dlp's --limit-rate setting."""

    def __init__(self, bytes_per_second):
        self._rate = int(bytes_per_second or 0)
        self._started = time.monotonic()
        self._reserved = 0
        self._lock = threading.Lock()

    def wait(self, size, stopped=None):
        if self._rate <= 0 or size <= 0:
            return
        with self._lock:
            self._reserved += size
            target = self._started + self._reserved / self._rate
        delay = target - time.monotonic()
        if delay > 0:
            if stopped is not None:
                if stopped.wait(delay):
                    raise InterruptedError('下载已停止')
            else:
                time.sleep(delay)


class TwitCastingParallelHlsPP(PostProcessor):
    """Choose native HLS or verified parallel cache + local FFmpeg for VODs."""

    def __init__(self, downloader=None, cleanup='false', **kwargs):
        super().__init__(downloader)
        self._cleanup = str(cleanup).strip().lower() in {'1', 'true', 'yes', 'on'}

    @staticmethod
    def _is_twitcasting(info):
        extractor = str(info.get('extractor_key') or info.get('extractor') or '').lower()
        webpage_url = str(info.get('webpage_url') or info.get('original_url') or '').lower()
        return 'twitcasting' in extractor or 'twitcasting.tv/' in webpage_url

    @staticmethod
    def _safe_component(value, fallback):
        cleaned = _SAFE_COMPONENT_RE.sub('_', str(value or '')).strip('._')
        return (cleaned or fallback)[:80]

    @staticmethod
    def _format_rate(value):
        value = float(value or 0)
        for suffix in ('B/s', 'KiB/s', 'MiB/s', 'GiB/s'):
            if value < 1024 or suffix == 'GiB/s':
                return f'{value:.2f}{suffix}'
            value /= 1024

    @staticmethod
    def _format_eta(seconds):
        seconds = max(0, int(seconds or 0))
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f'{hours}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes:02d}:{seconds:02d}'

    @staticmethod
    def _safe_error(error):
        message = re.sub(r'https?://\S+', '<url>', str(error))
        return message[:300]

    def _request_bytes(self, url, headers, *, maximum=None, limiter=None, return_url=False):
        request = Request(url, headers=headers)
        with self._downloader.urlopen(request) as response:
            chunks = []
            total = 0
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if maximum is not None and total > maximum:
                    raise ValueError('播放列表体积异常')
                if limiter is not None:
                    limiter.wait(len(chunk))
                chunks.append(chunk)
        data = b''.join(chunks)
        return (data, getattr(response, 'url', url)) if return_url else data

    def _media_playlist(self, format_info, headers):
        url = format_info['url']
        visited = set()
        for _ in range(5):
            if url in visited:
                raise ValueError('HLS 主播放列表循环引用')
            visited.add(url)
            data, url = self._request_bytes(url, headers, maximum=_MAX_MANIFEST_BYTES, return_url=True)
            text = data.decode('utf-8-sig')
            if not text.startswith('#EXTM3U'):
                raise ValueError('服务器返回的内容不是 HLS 播放列表')
            if '#EXT-X-STREAM-INF:' not in text:
                return url, text
            variants = []
            attributes = None
            for line in text.splitlines():
                line = line.strip()
                if line.startswith('#EXT-X-STREAM-INF:'):
                    attributes = parse_m3u8_attributes(line.partition(':')[2])
                elif line and not line.startswith('#') and attributes is not None:
                    variants.append((int(attributes.get('BANDWIDTH') or 0), urljoin(url, line)))
                    attributes = None
            if not variants:
                raise ValueError('HLS 主播放列表没有媒体地址')
            # Normally yt-dlp has selected a media URL already. Legacy multi_video
            # entries can contain a master instead; select one variant, never all.
            url = max(variants, key=lambda item: item[0])[1]
            if urlsplit(url).scheme not in {'http', 'https'}:
                raise ValueError('播放列表包含非 HTTP(S) 地址')
        raise ValueError('HLS 播放列表嵌套过深')

    @staticmethod
    def _replace_uri(line, replacement):
        match = _URI_ATTRIBUTE_RE.search(line)
        if not match:
            raise ValueError('HLS URI 属性无法解析')
        escaped = replacement.replace('"', '%22')
        return f'{line[:match.start()]}URI="{escaped}"{line[match.end():]}'

    def _build_local_playlist(self, manifest_url, manifest_text):
        if '#EXT-X-STREAM-INF' in manifest_text:
            raise ValueError('预期媒体播放列表，但收到主播放列表')
        if '#EXT-X-ENDLIST' not in manifest_text:
            raise _UnsupportedPlaylist('播放列表尚未结束，需由 FFmpeg 持续读取')
        if '#EXT-X-BYTERANGE:' in manifest_text or re.search(r'#EXT-X-MAP:.*\bBYTERANGE=', manifest_text):
            raise _UnsupportedPlaylist('字节范围播放列表需由 FFmpeg 读取')

        assets = {}
        rewritten = []
        map_count = 0
        media_count = 0
        key_count = 0

        def register(source, kind, ordinal):
            absolute = urljoin(manifest_url, source)
            if urlsplit(absolute).scheme not in {'http', 'https'}:
                raise ValueError('播放列表包含非 HTTP(S) 资源')
            if absolute in assets:
                return assets[absolute]
            suffix = Path(urlsplit(absolute).path).suffix.lower()
            if kind == 'media':
                suffix = suffix if suffix in _MEDIA_EXTENSIONS else '.mp4'
                name = f'media-{ordinal:06d}{suffix}'
            elif kind == 'map':
                suffix = suffix if suffix in _MEDIA_EXTENSIONS else '.mp4'
                name = f'init-{ordinal:04d}{suffix}'
            else:
                name = f'key-{ordinal:04d}.bin'
            assets[absolute] = name
            return name

        for raw_line in manifest_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith('#EXT-X-MAP:'):
                match = _URI_ATTRIBUTE_RE.search(line)
                if not match:
                    raise ValueError('EXT-X-MAP 缺少 URI')
                map_count += 1
                rewritten.append(self._replace_uri(
                    line, register(match.group('uri'), 'map', map_count)))
            elif line.startswith('#EXT-X-KEY:') and 'METHOD=NONE' not in line.upper():
                attributes = parse_m3u8_attributes(line.partition(':')[2])
                if attributes.get('METHOD') != 'AES-128' or attributes.get('KEYFORMAT', 'identity') != 'identity':
                    raise _UnsupportedPlaylist('该加密方式不支持本地分片缓存')
                match = _URI_ATTRIBUTE_RE.search(line)
                if not match:
                    raise ValueError('加密播放列表的 EXT-X-KEY 缺少 URI')
                key_count += 1
                rewritten.append(self._replace_uri(
                    line, register(match.group('uri'), 'key', key_count)))
            elif line.startswith('#'):
                rewritten.append(line)
            else:
                media_count += 1
                rewritten.append(register(line, 'media', media_count))

        if map_count < 2:
            return None
        if not media_count:
            raise ValueError('播放列表中没有媒体分片')
        if len(assets) > _MAX_ASSETS:
            raise ValueError(f'播放列表资源过多（{len(assets)}）')
        return assets, '\n'.join(rewritten) + '\n', media_count, map_count

    def _cache_dir(self, info, format_info):
        output = Path(info.get('_filename') or info.get('filename') or 'twitcasting.mp4')
        video_id = self._safe_component(info.get('id'), 'video')
        format_identity = '-'.join(str(value or '') for value in (
            format_info.get('format_id'),
            f'{format_info.get("width") or 0}x{format_info.get("height") or 0}',
            format_info.get('vcodec'),
            format_info.get('acodec'),
        ))
        format_id = self._safe_component(format_identity, 'default')
        # Do not include the signed manifest URL: TwitCasting can refresh it between
        # runs, while the immutable VOD id + selected format remain a stable cache key.
        return output.parent / f'.tc-hls-{video_id}-{format_id}'

    def _download_asset(self, url, destination, headers, limiter, retries, stopped):
        partial = destination.with_suffix(destination.suffix + '.part')
        last_error = None
        for attempt in range(retries + 1):
            if stopped.is_set():
                raise InterruptedError('下载已停止')
            try:
                request = Request(url, headers=headers)
                request.headers['Accept-Encoding'] = 'identity'
                with self._downloader.urlopen(request) as response, open(partial, 'wb') as output:
                    downloaded = 0
                    digest = hashlib.sha256()
                    content_length = response.headers.get('Content-Length')
                    while True:
                        if stopped.is_set():
                            raise InterruptedError('下载已停止')
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        limiter.wait(len(chunk), stopped)
                        output.write(chunk)
                        digest.update(chunk)
                        downloaded += len(chunk)
                if downloaded <= 0:
                    raise OSError('服务器返回空分片')
                if content_length and not response.headers.get('Content-Encoding') and downloaded != int(content_length):
                    raise OSError('分片长度不完整')
                os.replace(partial, destination)
                return downloaded, digest.hexdigest()
            except Exception as error:
                last_error = error
                response = getattr(error, 'response', None)
                if response is not None:
                    response.close()
                try:
                    partial.unlink()
                except FileNotFoundError:
                    pass
                # Expired credentials cannot be repaired by repeating the same URL.
                if getattr(error, 'status', None) in {400, 401, 403, 404, 410} or stopped.is_set():
                    raise
                if attempt < retries and stopped.wait(min(4, 0.5 * (2 ** attempt))):
                    raise InterruptedError('下载已停止') from error
        raise last_error

    @staticmethod
    def _verified_cache(cache_dir):
        completed = {}
        journal = cache_dir / 'completed.jsonl'
        if not journal.is_file():
            return completed
        for line in journal.read_text(encoding='utf-8').splitlines():
            try:
                record = json.loads(line)
                name, size, digest = record['name'], record['size'], record['sha256']
                if not isinstance(name, str) or Path(name).name != name:
                    continue
                path = cache_dir / name
                if not path.is_file() or path.stat().st_size != size or size <= 0:
                    continue
                with path.open('rb') as source:
                    hasher = hashlib.sha256()
                    for chunk in iter(lambda: source.read(256 * 1024), b''):
                        hasher.update(chunk)
                    if hasher.hexdigest() == digest:
                        completed[name] = size
            except (ValueError, KeyError, TypeError, OSError):
                continue
        return completed

    def _transfer_assets(self, assets, cache_dir, headers, threads, retries, limiter, format_info):
        verified = self._verified_cache(cache_dir)
        remaining = iter((url, name) for url, name in assets.items() if name not in verified)
        completed = sum(name in verified for name in assets.values())
        resumed = completed
        if completed:
            self.to_screen(f'[TwitCastingParallel] 校验后复用 {completed}/{len(assets)} 个完整分片')
        started = time.monotonic()
        last_report = 0.0
        downloaded_bytes = 0
        stopped = threading.Event()
        # A rolling window bounds memory and prevents thousands of queued tasks
        # continuing to fetch obsolete signed URLs after the first fatal error.
        with (concurrent.futures.ThreadPoolExecutor(max_workers=threads) as pool,
              (cache_dir / 'completed.jsonl').open('a', encoding='utf-8') as journal):
            # Separate any incomplete journal line left by a forced process stop.
            journal.write('\n')
            journal.flush()
            pending = {}

            def submit_next():
                item = next(remaining, None)
                if item is not None:
                    url, name = item
                    future = pool.submit(self._download_asset, url, cache_dir / name,
                                         headers, limiter, retries, stopped)
                    pending[future] = name

            for _ in range(threads * 2):
                submit_next()
            try:
                while pending:
                    ready, _ = concurrent.futures.wait(pending, return_when=concurrent.futures.FIRST_COMPLETED)
                    for future in ready:
                        name = pending.pop(future)
                        size, digest = future.result()
                        journal.write(json.dumps({'name': name, 'size': size, 'sha256': digest}) + '\n')
                        journal.flush()
                        completed += 1
                        downloaded_bytes += size
                        submit_next()
                    now = time.monotonic()
                    if completed < len(assets) and now - last_report < 0.25:
                        continue
                    last_report = now
                    elapsed = max(now - started, 0.001)
                    speed = downloaded_bytes / elapsed
                    transferred = completed - resumed
                    eta = elapsed / max(transferred, 1) * (len(assets) - completed)
                    codecs = f'{format_info.get("vcodec") or "unknown"}|{format_info.get("acodec") or "unknown"}'
                    self.to_screen(
                        f'[TwitCastingParallel] {completed / len(assets) * 100:.1f}% of '
                        f'{completed}/{len(assets)} fragments at {self._format_rate(speed)} '
                        f'ETA {self._format_eta(eta)} __VD_STAGE__{codecs}')
            finally:
                stopped.set()
                for future in pending:
                    future.cancel()

    def _prepare_format(self, info, format_info):
        manifest_url = str(format_info.get('url') or '')
        protocol = str(format_info.get('protocol') or '')
        if protocol not in {'m3u8', 'm3u8_native'} or not manifest_url.startswith(('http://', 'https://')):
            return None

        headers = {**(info.get('http_headers') or {}), **(format_info.get('http_headers') or {})}
        manifest_url, manifest_text = self._media_playlist(format_info, headers)
        try:
            plan = self._build_local_playlist(manifest_url, manifest_text)
        except _UnsupportedPlaylist as error:
            self.report_warning(f'[TwitCastingParallel] {error}，使用远程 FFmpeg 兼容下载')
            format_info['protocol'] = 'm3u8'
            return None
        if plan is None:
            # Native HLS accepts this field, avoiding another request for the
            # exact same media playlist and preserving the selected CDN URL.
            format_info['url'] = manifest_url
            format_info['protocol'] = 'm3u8_native'
            format_info['hls_media_playlist_data'] = manifest_text
            return None
        assets, local_manifest, media_count, map_count = plan

        # Do not trust files solely because they are nonempty. Separate plans
        # and journal only complete, hashed assets, without persisting signed URLs.
        identity = json.dumps([local_manifest, [Path(urlsplit(url).path).name for url in assets]], ensure_ascii=True)
        fingerprint = hashlib.sha256(identity.encode()).hexdigest()[:16]
        base = self._cache_dir(info, format_info)
        cache_dir = base.with_name(f'{base.name}-{fingerprint}')
        cache_dir.mkdir(parents=True, exist_ok=True)
        threads = max(1, min(32, int(
            self._downloader.params.get('concurrent_fragment_downloads') or 1)))
        retries_value = self._downloader.params.get('fragment_retries', 3)
        retries = 3 if retries_value in (None, 'inf', 'infinite') else max(0, min(10, int(retries_value)))
        limiter = _DownloadLimiter(self._downloader.params.get('ratelimit'))

        self.to_screen(
            f'[TwitCastingParallel] 检测到 {media_count} 个媒体分片和 {map_count} 个初始化段，'
            f'使用 {threads} 线程并发下载')
        self._transfer_assets(assets, cache_dir, headers, threads, retries, limiter, format_info)

        playlist_path = cache_dir / 'local.m3u8'
        partial_playlist = cache_dir / 'local.m3u8.part'
        with open(partial_playlist, 'w', encoding='utf-8', newline='\n') as output:
            output.write(local_manifest)
        os.replace(partial_playlist, playlist_path)
        # FFmpeg's file protocol does not URL-decode %20 (or UTF-8 escapes).
        # Pass the native absolute filename after file:, preserving spaces and
        # non-ASCII characters. yt-dlp passes this argument directly to FFmpeg.
        format_info['url'] = 'file:' + playlist_path.resolve().as_posix()
        format_info['protocol'] = 'm3u8'
        format_info.pop('hls_media_playlist_data', None)
        self.to_screen('[TwitCastingParallel] 并发分片准备完成，正在由 FFmpeg 本地封装')
        return str(cache_dir)

    def _prepare_with_refresh(self, info, format_info):
        try:
            return self._prepare_format(info, format_info)
        except Exception as error:
            if getattr(error, 'status', None) not in {400, 401, 403, 410}:
                raise
            webpage_url = info.get('webpage_url') or info.get('original_url')
            if not webpage_url:
                raise
            response = getattr(error, 'response', None)
            if response is not None:
                response.close()
            self.to_screen(f'[TwitCastingParallel] 播放请求返回 {error.status}，使用当前登录状态刷新播放地址一次')
            refreshed = self._downloader.extract_info(webpage_url, download=False)
            candidates = refreshed.get('formats') or [refreshed]
            selected = next((item for item in candidates
                             if item.get('format_id') == format_info.get('format_id')), None)
            if not selected or not selected.get('url'):
                raise ValueError('刷新后未找到原先选择的清晰度') from error
            for key in ('url', 'protocol', 'http_headers'):
                if key in selected:
                    format_info[key] = selected[key]
            return self._prepare_format(info, format_info)

    def _cleanup_cache(self, info):
        output = Path(info.get('_filename') or info.get('filename') or '').resolve()
        for raw_path in info.pop('_tc_parallel_cache_dirs', []) or []:
            cache_dir = Path(raw_path).resolve()
            # Only remove the exact cache directories created beside this output.
            if cache_dir.parent != output.parent or not cache_dir.name.startswith('.tc-hls-'):
                self.report_warning('[TwitCastingParallel] 忽略了异常的缓存清理路径')
                continue
            shutil.rmtree(cache_dir, ignore_errors=True)

    def run(self, info):
        if self._cleanup:
            self._cleanup_cache(info)
            return [], info
        if not self._is_twitcasting(info) or info.get('is_live'):
            return [], info
        if self._downloader.params.get('skip_download') or self._downloader.params.get('simulate'):
            return [], info
        if Path(info.get('_filename') or info.get('filename') or '').is_file():
            return [], info

        targets = info.get('requested_formats') or [info]
        cache_dirs = []
        original_targets = [
            (format_info, format_info.get('url'), format_info.get('protocol'))
            for format_info in targets
        ]
        try:
            for format_info in targets:
                cache_dir = self._prepare_with_refresh(info, format_info)
                if cache_dir:
                    cache_dirs.append(cache_dir)
        except Exception as error:
            for format_info, url, protocol in original_targets:
                format_info['url'] = url
                format_info['protocol'] = protocol
            raise PostProcessingError(
                '[TwitCastingParallel] 并发下载失败，已保留通过校验的分片；重试将续传: '
                f'{self._safe_error(error)}') from error

        if cache_dirs:
            info['_tc_parallel_cache_dirs'] = cache_dirs
            if info.get('requested_formats'):
                info['protocol'] = '+'.join(
                    str(item.get('protocol') or '') for item in info['requested_formats'])
        return [], info
