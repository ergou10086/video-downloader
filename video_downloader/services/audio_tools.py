"""Validated audio jobs shared by the toolbox's three HTTP entry points."""

from __future__ import annotations

import json
import math
import os
import subprocess
import threading
import uuid
from pathlib import Path

from video_downloader.services.download_manager import DownloadManager


AUDIO_EXTENSIONS = {'.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.opus',
                    '.wma', '.ac3', '.aiff', '.aif', '.wv', '.ape'}
# The server owns codecs and containers; never execute codec arguments from the UI.
FORMATS = {
    'mp3': ('mp3', 'libmp3lame', '320k'),
    'aac': ('m4a', 'aac', '256k'),
    'm4a': ('m4a', 'aac', '256k'),
    'wav': ('wav', 'pcm_s16le', None),
    'flac': ('flac', 'flac', None),
    'ogg': ('ogg', 'libvorbis', None),
    'opus': ('opus', 'libopus', '192k'),
    'wma': ('wma', 'wmav2', '192k'),
    'ac3': ('ac3', 'ac3', '448k'),
    'alac': ('m4a', 'alac', None),
    'aiff': ('aiff', 'pcm_s16be', None),
    'aif': ('aif', 'pcm_s16be', None),
    'wv': ('wv', 'wavpack', None),
}


def resolve_directory(value, app_dir: Path, *, must_exist=True) -> Path:
    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        text = text[1:-1].strip()
    if not text:
        raise ValueError('请输入或选择文件夹')
    path = Path(os.path.expandvars(text)).expanduser()
    path = (path if path.is_absolute() else app_dir / path).resolve()
    if path.exists() and not path.is_dir():
        raise ValueError(f'所选路径是文件，请选择文件夹: {path}')
    if must_exist and not path.is_dir():
        raise ValueError(f'目录不存在: {path}')
    return path


def bounded_number(value, low, high, label):
    if isinstance(value, bool):
        raise ValueError(f'{label}必须是数字')
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f'{label}范围: {low} ~ {high}')
    return number


def codec_args(fmt, *, bitrate=None, compression_level=None, quality=None):
    if fmt not in FORMATS:
        raise ValueError(f'不支持输出格式 {fmt}；APE 输入请改选 FLAC 等可编码格式')
    extension, codec, default_bitrate = FORMATS[fmt]
    args = ['-c:a', codec]
    if default_bitrate:
        raw = str(bitrate or default_bitrate).removesuffix('k')
        rate = bounded_number(raw, 16, 640, '码率')
        if not rate.is_integer():
            raise ValueError('码率必须是整数 kbps')
        if fmt == 'opus' and rate > 256:
            raise ValueError('Opus 码率范围: 16 ~ 256 kbps')
        args += ['-b:a', f'{int(rate)}k']
    elif fmt == 'flac':
        level = bounded_number(5 if compression_level is None else compression_level, 0, 12, '压缩等级')
        if not level.is_integer():
            raise ValueError('压缩等级必须是整数')
        args += ['-compression_level', str(int(level))]
    elif fmt == 'ogg':
        q = bounded_number(7 if quality is None else quality, -1, 10, 'Vorbis 质量')
        args += ['-q:a', str(q)]
    # Let FFmpeg preserve source channels/rate where the encoder supports them.
    # MP3/WMA have narrower layout support; do not downmix lossless formats.
    if fmt in {'mp3', 'wma'}:
        args += ['-ac', '2']
    return '.' + extension, args


class AudioToolService:
    def __init__(self, paths, exe_suffix, manager, log, broadcast, cancel_idle,
                 start_idle, publish=None):
        self.paths = paths
        self.exe_suffix = exe_suffix
        self.manager = manager or DownloadManager()
        self.log = log
        self.broadcast = broadcast
        self.cancel_idle = cancel_idle
        self.start_idle = start_idle
        self.publish = publish or (lambda event: None)

    def start(self, kind, directory, recursive=False, output_format='same',
              output_dir='', delete_source=False, **options):
        labels = {'convert': '音频转换', 'loudnorm': '响度统一', 'volume': '音量调整'}
        try:
            label = labels[kind]
            target = resolve_directory(directory, self.paths.app_dir)
            for binary in ('ffmpeg', 'ffprobe'):
                if not self.paths.executable(binary, self.exe_suffix).is_file():
                    raise ValueError(f'未找到 {binary}{self.exe_suffix}，请检查 dependency 目录')
            fmt = output_format or 'same'
            if fmt != 'same':
                codec_args(fmt, **{k: v for k, v in options.items()
                                   if k in ('bitrate', 'compression_level', 'quality')})
            if kind == 'volume':
                options['gain_db'] = bounded_number(options.get('gain_db', 0), -30, 30, '增益 dB')
                if options['gain_db'] == 0:
                    raise ValueError('增益为 0 dB，无需处理')
            if kind == 'loudnorm':
                if options.get('mode', 'single') not in ('single', 'double'):
                    raise ValueError('响度模式必须是 single 或 double')
                for key, low, high, name, default in (
                    ('i_target', -70, -5, '目标响度 I', -24),
                    ('lra_target', 1, 20, '响度范围 LRA', 7),
                    ('tp_target', -9, 0, '真峰值 TP', -2),
                ):
                    options[key] = bounded_number(options.get(key, default), low, high, name)
            out = (resolve_directory(output_dir, self.paths.app_dir, must_exist=False)
                   if output_dir.strip() else target if kind == 'convert'
                   else target / f'{kind}_output')
            # Re-running recursive jobs must not consume previous generated outputs.
            excluded = {target / 'loudnorm_output', target / 'volume_output'}
            if out != target and out.is_relative_to(target):
                excluded.add(out)
            files = sorted(p for p in target.glob('**/*' if recursive else '*')
                           if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
                           and not p.name.startswith('.audio-')
                           and not any(p.resolve().is_relative_to(e.resolve()) for e in excluded))
            if options.get('wav_only'):
                files = [p for p in files if p.suffix.lower() == '.wav']
            if not files:
                raise ValueError('目录中未找到支持的音频文件')
            # Validate every source format before launching or creating any output.
            jobs = []
            for src in files:
                source_fmt = src.suffix[1:].lower()
                chosen = source_fmt if fmt == 'same' else fmt
                ext, args = codec_args(chosen, **{k: v for k, v in options.items()
                                                if k in ('bitrate', 'compression_level', 'quality')})
                if fmt == 'same' and source_fmt == 'aac':
                    ext = '.aac'  # ADTS, whereas the converter's AAC choice is M4A.
                suffix = {'convert': '', 'loudnorm': '_norm', 'volume': '_vol'}[kind]
                dst = out / src.relative_to(target).parent / (src.stem + suffix + ext)
                jobs.append((src, dst, args))
            out.mkdir(parents=True, exist_ok=True)
        except (ValueError, TypeError, OSError) as exc:
            return {'error': str(exc)}

        handle = self.manager.begin('audio_' + kind)
        if handle is None:
            return {'error': '已有下载或工具任务正在运行，请完成或停止后重试'}
        self.cancel_idle()
        self.broadcast()

        def run():
            success = skipped = failed = 0
            try:
                self.log(f'[{label}] 找到 {len(jobs)} 个音频文件', 'info')
                for index, (src, dst, args) in enumerate(jobs, 1):
                    if self.manager.is_cancelled(handle):
                        break
                    self.log(f'[{index}/{len(jobs)}] {src.relative_to(target)}', 'info')
                    if dst.exists():
                        skipped += 1
                        self.log('  → 输出已存在，跳过（保留源文件）', 'warn')
                        continue
                    temporary = dst.with_name(f'.audio-{uuid.uuid4().hex}{dst.suffix}')
                    try:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        filters = self._filters(handle, kind, src, options)
                        cmd = self._ffmpeg() + ['-i', str(src), '-map', '0:a:0', '-vn']
                        if filters:
                            cmd += ['-af', filters]
                        if kind == 'loudnorm':
                            # The dynamic filter upsamples to 192 kHz; choose an
                            # explicit encoder-compatible output rate (FFmpeg docs).
                            cmd += ['-ar', '48000']
                        self._execute(handle, cmd + args + [str(temporary)])
                        self._verify(handle, temporary)
                        if self.manager.is_cancelled(handle):
                            break
                        # Publish without overwriting a file created while encoding.
                        if os.name == 'nt':
                            temporary.rename(dst)  # Windows rename refuses existing destinations, including FAT/exFAT.
                        else:
                            os.link(temporary, dst)
                        success += 1
                        self.log(f'  → 已保存: {dst}', 'success')
                        if delete_source:
                            src.unlink()
                    except Exception as exc:
                        if not self.manager.is_cancelled(handle):
                            failed += 1
                            self.log(f'  → 失败，保留源文件: {str(exc)[-600:]}', 'error')
                    finally:
                        try:
                            temporary.unlink(missing_ok=True)
                        except OSError as exc:
                            self.log(f'  → 临时文件清理失败: {exc}', 'warn')
                stopped = self.manager.is_cancelled(handle)
                message = f'[{label}] {"已停止" if stopped else "完成"}: 成功{success} 跳过{skipped} 失败{failed}'
                level = 'warn' if stopped or skipped or failed else 'success'
                self.log(message, level)
                self.publish({'type': 'audio_tool_result', 'data': {'message': message, 'level': level}})
            finally:
                self.manager.finish(handle)
                self.broadcast()
                self.start_idle()
        try:
            threading.Thread(target=run, daemon=True).start()
        except Exception as exc:
            self.manager.finish(handle)
            self.broadcast()
            self.start_idle()
            return {'error': f'工具启动失败: {exc}'}
        return {'ok': True, 'total': len(jobs), 'output_dir': str(out),
                'message': f'{label}已启动，共 {len(jobs)} 个文件；完成结果见工具日志'}

    def stop(self):
        ticket = self.manager.request_stop(kind_prefix='audio_')
        if not ticket.active:
            return {'error': '当前没有音频工具任务'}
        if ticket.process is not None:
            try:
                ticket.process.kill()
            except OSError:
                pass
        self.broadcast()
        return {'ok': True, 'message': '正在停止音频工具，源文件会保留'}

    def _ffmpeg(self):
        return [str(self.paths.executable('ffmpeg', self.exe_suffix)), '-hide_banner',
                '-nostdin', '-nostats', '-y']

    def _execute(self, handle, command):
        if self.manager.is_cancelled(handle):
            raise RuntimeError('任务已停止')
        proc = subprocess.Popen(command, cwd=self.paths.app_dir, env=self.paths.subprocess_env(),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding='utf-8', errors='replace',
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            if not self.manager.publish_process(handle, proc):
                proc.kill()
            try:
                stdout, stderr = proc.communicate(timeout=3600)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                raise RuntimeError('处理超时，保留源文件') from None
            if proc.returncode or self.manager.is_cancelled(handle):
                raise RuntimeError((stderr or '处理已停止')[-600:])
            return stdout, stderr
        finally:
            self.manager.clear_process(handle, proc)

    def _verify(self, handle, file):
        if not file.is_file() or file.stat().st_size == 0:
            raise RuntimeError('没有生成有效音频文件')
        command = [str(self.paths.executable('ffprobe', self.exe_suffix)), '-v', 'error',
                   '-show_entries', 'stream=codec_type', '-of', 'json', str(file)]
        stdout, _ = self._execute(handle, command)
        if not any(s.get('codec_type') == 'audio' for s in json.loads(stdout).get('streams', [])):
            raise RuntimeError('输出文件没有音轨')
        self._execute(handle, self._ffmpeg() + ['-v', 'error', '-xerror', '-i', str(file),
                                              '-map', '0:a:0', '-f', 'null', '-'])

    def _filters(self, handle, kind, source, options):
        if kind == 'convert':
            return ''
        if kind == 'volume':
            gain = options['gain_db']
            filters = f'volume={gain}dB'
            if gain > 0 and options.get('limiter_enabled', True):
                # Disable automatic gain make-up: the limiter must not undo the ceiling.
                filters += ',alimiter=limit=0.988553:level=false:latency=true'
            return filters
        base = f'loudnorm=I={options["i_target"]}:LRA={options["lra_target"]}:TP={options["tp_target"]}'
        if options.get('mode', 'single') == 'single':
            return base
        _, stderr = self._execute(handle, self._ffmpeg() + ['-i', str(source), '-map', '0:a:0',
                                      '-af', base + ':print_format=json', '-f', 'null', '-'])
        decoder = json.JSONDecoder()
        for pos, char in enumerate(stderr):
            if char != '{':
                continue
            try:
                measured, _ = decoder.raw_decode(stderr[pos:])
                values = [float(measured[k]) for k in ('input_i', 'input_lra', 'input_tp', 'input_thresh', 'target_offset')]
            except (ValueError, TypeError, KeyError):
                continue
            if all(math.isfinite(v) for v in values):
                keys = ('measured_I', 'measured_LRA', 'measured_TP', 'measured_thresh', 'offset')
                return base + ''.join(f':{k}={v}' for k, v in zip(keys, values)) + ':linear=true'
        self.log('  → 分析结果非有限值（例如静音），使用单次动态处理', 'warn')
        return base
