from tests.helpers import PROJECT_ROOT
import base64
import json
import math
import os
import struct
import subprocess
import time
import wave
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from video_downloader.core.paths import AppPaths
from video_downloader.services.audio_tools import AudioToolService, codec_args
from video_downloader.services.download_manager import DownloadManager
from tests.helpers.tools import create_service


ROOT = PROJECT_ROOT


def write_wave(path, seconds=4, silence=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as output:
        output.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        output.writeframes(b''.join(struct.pack('<h', 0 if silence else int(
            5000 * math.sin(2 * math.pi * 440 * i / 48000))) for i in range(int(seconds * 48000))))


@pytest.fixture
def audio(tmp_path):
    suffix = '.exe' if os.name == 'nt' else ''
    paths = AppPaths(tmp_path)
    real = AppPaths(ROOT)
    if not all(real.executable(name, suffix).is_file() for name in ('ffmpeg', 'ffprobe')):
        pytest.skip('真实音频测试需要本地 ffmpeg 和 ffprobe')
    paths.executable = real.executable
    logs, events = [], []
    manager = DownloadManager()
    service = AudioToolService(paths, suffix, manager,
                               lambda message, level: logs.append((message, level)),
                               lambda: None, lambda: None, lambda: None, events.append)
    service.logs, service.events = logs, events
    return service


def wait_finished(service, timeout=25):
    deadline = time.monotonic() + timeout
    while service.manager.snapshot()['running'] and time.monotonic() < deadline:
        time.sleep(.02)
    assert not service.manager.snapshot()['running']
    assert service.events, service.logs
    return service.events[-1]['data']['message']


@pytest.mark.parametrize('fmt,ext,codec', [
    ('mp3', 'mp3', 'mp3'), ('aac', 'm4a', 'aac'), ('wav', 'wav', 'pcm_s16le'),
    ('flac', 'flac', 'flac'), ('ogg', 'ogg', 'vorbis'), ('opus', 'opus', 'opus'),
    ('wma', 'wma', 'wmav2'), ('ac3', 'ac3', 'ac3'), ('alac', 'm4a', 'alac'),
])
def test_real_converter_all_ui_formats(audio, tmp_path, fmt, ext, codec):
    source = tmp_path / '中文 空格' / '音轨.WAV'
    write_wave(source, seconds=.5)
    result = audio.start('convert', '"中文 空格"', output_format=fmt,
                         output_dir='转换结果', compression_level=12)
    assert result.get('ok'), result
    assert '成功1' in wait_finished(audio), audio.logs
    output = tmp_path / '转换结果' / f'音轨.{ext}'
    metadata = subprocess.check_output([
        str(audio.paths.executable('ffprobe', audio.exe_suffix)), '-v', 'error',
        '-show_entries', 'stream=codec_name', '-of', 'json', str(output)], encoding='utf-8')
    assert json.loads(metadata)['streams'][0]['codec_name'] == codec
    assert source.exists()
    assert not list(tmp_path.rglob('.audio-*'))


def test_real_recursive_preserves_names_excludes_outputs_and_does_not_overwrite(audio, tmp_path):
    for relative in ('a/同名.wav', 'b/同名.wav'):
        write_wave(tmp_path / relative, seconds=.4)
    result = audio.start('volume', str(tmp_path), True, 'flac', gain_db=-6)
    assert result.get('total') == 2
    assert '成功2' in wait_finished(audio)
    outputs = list((tmp_path / 'volume_output').rglob('*.flac'))
    assert len(outputs) == 2
    original = [p.read_bytes() for p in outputs]
    assert audio.start('volume', str(tmp_path), True, 'flac', gain_db=-6)['total'] == 2
    assert '跳过2' in wait_finished(audio)
    assert [p.read_bytes() for p in outputs] == original


@pytest.mark.parametrize('ext,codec', [('aiff', 'pcm_s16be'), ('wma', 'wmav2'), ('wv', 'wavpack')])
def test_real_keep_source_format_uses_correct_encoder(audio, tmp_path, ext, codec):
    source = tmp_path / f'原声.{ext}'
    subprocess.run(audio._ffmpeg() + ['-f', 'lavfi', '-i', 'sine=duration=0.5',
                                    '-c:a', codec, str(source)], check=True, capture_output=True)
    assert audio.start('volume', str(tmp_path), gain_db=-3).get('ok')
    assert '成功1' in wait_finished(audio), audio.logs
    assert (tmp_path / 'volume_output' / f'原声_vol.{ext}').is_file()


@pytest.mark.parametrize('silence', [False, True])
def test_real_double_loudnorm_including_silence(audio, tmp_path, silence):
    write_wave(tmp_path / 'source.wav', silence=silence)
    assert audio.start('loudnorm', str(tmp_path), output_format='wav', mode='double',
                       i_target=-18).get('ok')
    assert '成功1' in wait_finished(audio), audio.logs
    output = tmp_path / 'loudnorm_output/source_norm.wav'
    if silence:
        assert any('非有限值' in msg for msg, _ in audio.logs)
    else:
        data = subprocess.run(audio._ffmpeg() + ['-i', str(output), '-af',
                              'loudnorm=print_format=json', '-f', 'null', '-'],
                              capture_output=True, encoding='utf-8', check=True).stderr
        measured, _ = json.JSONDecoder().raw_decode(data[data.rfind('{'):])
        assert abs(float(measured['input_i']) - (-18)) < .5


def test_real_failed_input_and_existing_output_never_delete_source(audio, tmp_path):
    corrupt = tmp_path / '坏文件.wav'
    corrupt.write_text('not audio', encoding='utf-8')
    assert audio.start('convert', str(tmp_path), output_format='mp3', delete_source=True).get('ok')
    assert '失败1' in wait_finished(audio)
    assert corrupt.exists() and not list(tmp_path.glob('*.mp3'))
    assert not list(tmp_path.glob('.audio-*'))
    write_wave(corrupt, seconds=.5)
    destination = tmp_path / '坏文件.mp3'
    destination.write_bytes(b'existing user data')
    assert audio.start('convert', str(tmp_path), output_format='mp3', delete_source=True).get('ok')
    assert '跳过' in wait_finished(audio)
    assert corrupt.exists() and destination.read_bytes() == b'existing user data'


def test_real_verified_conversion_can_delete_source(audio, tmp_path):
    source = tmp_path / 'delete.wav'
    write_wave(source, seconds=.5)
    assert audio.start('convert', str(tmp_path), output_format='flac', delete_source=True).get('ok')
    assert '成功1' in wait_finished(audio)
    assert not source.exists() and (tmp_path / 'delete.flac').exists()


def test_cancel_real_process_cleans_partial_retains_source_and_releases_slot(audio, tmp_path):
    write_wave(tmp_path / 'source.wav')
    original = audio._ffmpeg
    audio._ffmpeg = lambda: original() + ['-re']
    assert audio.start('convert', str(tmp_path), output_format='flac', delete_source=True).get('ok')
    deadline = time.monotonic() + 5
    while audio.manager.snapshot()['process'] is None and time.monotonic() < deadline:
        time.sleep(.01)
    assert 'error' in audio.start('volume', str(tmp_path), gain_db=-3)
    assert audio.stop()['ok']
    assert '已停止' in wait_finished(audio)
    assert (tmp_path / 'source.wav').exists()
    assert not (tmp_path / 'source.flac').exists()
    assert not list(tmp_path.glob('.audio-*'))
    assert 'error' in audio.stop()


@pytest.mark.parametrize('kwargs', [
    {'gain_db': float('nan')}, {'gain_db': float('inf')}, {'gain_db': 31},
    {'gain_db': True}, {'gain_db': 0}, {'output_format': 'injected', 'gain_db': 1},
])
def test_bad_audio_parameters_are_reported_before_start(audio, tmp_path, kwargs):
    write_wave(tmp_path / 'source.wav', seconds=.1)
    assert 'error' in audio.start('volume', str(tmp_path), **kwargs)
    assert not audio.manager.snapshot()['running']


def test_missing_wrong_path_and_unsupported_ape_have_clear_errors(audio, tmp_path):
    assert 'error' in audio.start('convert', '')
    assert '目录不存在' in audio.start('convert', 'missing')['error']
    (tmp_path / 'file.wav').touch()
    assert '文件夹' in audio.start('convert', 'file.wav')['error']
    (tmp_path / 'file.wav').unlink()
    (tmp_path / 'file.ape').touch()
    assert 'APE' in audio.start('volume', str(tmp_path), gain_db=-1)['error']
    assert 'error' in audio.start('loudnorm', str(tmp_path), mode='unknown')


def test_tool_cleanup_keeps_live_recovery_and_utf8_bom_urls(tmp_path):
    live = tmp_path / 'download/.live-jobs/job/media/stream.mp4.part'
    live.parent.mkdir(parents=True)
    live.write_bytes(b'recoverable recording')
    service = create_service(str(tmp_path))
    assert service.clean_temp() == {'ok': True, 'count': 0}
    assert live.read_bytes() == b'recoverable recording'
    (tmp_path / 'urls.txt').write_text('https://example.com/a\n', encoding='utf-8-sig')
    assert service.read_urls_file() == (['https://example.com/a'], None)
    with patch('video_downloader.services.tools.os.startfile', create=True) as opened:
        assert service.open_folder('"中文 目录"')['ok']
        opened.assert_called_once_with(str(tmp_path / '中文 目录'))


def test_folder_dialog_fallback_returns_utf8_path_and_checks_failure(tmp_path):
    folder = tmp_path / '中文 空格'
    folder.mkdir()
    service = create_service(tmp_path)
    with patch.dict('sys.modules', {'tkinter': None}), patch(
        'video_downloader.services.tools.subprocess.run') as run:
        run.return_value = subprocess.CompletedProcess([], 0, base64.b64encode(
            str(folder).encode('utf-8')).decode('ascii'), '')
        assert service.browse_folder()['path'] == str(folder)
        assert '-STA' in run.call_args.args[0]
        run.return_value = subprocess.CompletedProcess([], 1, '', 'dialog failure')
        assert 'dialog failure' in service.browse_folder()['error']


def test_codec_and_loudness_parameter_bounds():
    for kwargs in ({'bitrate': 'oops'}, {'bitrate': 5}, {'bitrate': 128.5}):
        with pytest.raises(ValueError):
            codec_args('mp3', **kwargs)
    with pytest.raises(ValueError):
        codec_args('flac', compression_level=2.5)
    with pytest.raises(ValueError):
        codec_args('opus', bitrate='320k')


def test_tool_stop_cannot_cancel_unrelated_download(audio):
    handle = audio.manager.begin('video')
    assert 'error' in audio.stop()
    assert not handle.cancel_event.is_set()
    audio.manager.finish(handle)


def test_analysis_timeout_and_thread_launch_failure_release_slot(audio, tmp_path):
    write_wave(tmp_path / 'source.wav', seconds=.1)
    with patch('video_downloader.services.audio_tools.threading.Thread') as thread:
        thread.return_value.start.side_effect = RuntimeError('cannot start')
        assert 'error' in audio.start('convert', str(tmp_path), output_format='flac')
    assert not audio.manager.snapshot()['running']
    proc = type('Process', (), {})()
    proc.communicate = Mock(
        side_effect=[subprocess.TimeoutExpired('ffmpeg', 3600), ('', '')])
    proc.kill = lambda: None
    with patch('video_downloader.services.audio_tools.subprocess.Popen', return_value=proc):
        handle = audio.manager.begin('audio_loudnorm')
        with pytest.raises(RuntimeError, match='处理超时'):
            audio._execute(handle, ['ffmpeg'])
        assert audio.manager.snapshot()['process'] is None
        audio.manager.finish(handle)


def test_missing_dependencies_and_new_audio_preferences(tmp_path):
    service = create_service(tmp_path)
    assert 'ffmpeg' in service.audio_convert(str(tmp_path))['error']
    from video_downloader.core.validation import validate_config
    config, errors = validate_config({'AUDIO_OUTPUT_FORMAT': 'alac', 'AUDIO_RECURSIVE': 1})
    assert not errors and config['AUDIO_OUTPUT_FORMAT'] == 'alac'
    _, errors = validate_config({'AUDIO_OUTPUT_FORMAT': 'unknown', 'AUDIO_RECURSIVE': 2})
    assert len(errors) == 2
