"""Regression tests for fork/upstream integration and opt-in credential storage."""
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
from threading import Event
from unittest.mock import Mock, patch

import pytest

from video_downloader.core.constants import DEFAULT_CONFIG
from video_downloader.core.validation import validate_config
from video_downloader.live.classifier import is_live_url
from video_downloader.live.urls import classify_target, TargetKind
from video_downloader.services.storage import StorageService
from video_downloader.state.app_state import AppState
from tests.helpers.download import create_executor, ImmediateThread


@pytest.fixture
def storage(tmp_path):
    return StorageService(tmp_path, AppState(), validate_config, Mock(), Mock())


def test_password_defaults_and_boolean_validation():
    assert DEFAULT_CONFIG['TC_REMEMBER_PASSWORD'] == DEFAULT_CONFIG['TC_SAVE_PASSWORD_XLSX'] == 0
    config, errors = validate_config({'TC_REMEMBER_PASSWORD': 2, 'TC_SAVE_PASSWORD_XLSX': 'bad'})
    assert len(errors) == 2
    assert config['TC_REMEMBER_PASSWORD'] == config['TC_SAVE_PASSWORD_XLSX'] == 0


def test_memory_only_never_reads_or_migrates_existing_workbook(storage):
    url = 'https://twitcasting.tv/user/movie/123'
    workbook = storage._tc_password_file
    workbook.write_bytes(b'untouched workbook')
    storage._load_tc_password_rows = Mock(side_effect=AssertionError('disk read'))
    assert storage.get_twitcasting_password(url, persist=False) is None
    assert storage.save_twitcasting_password(url, 'pw', persist=False)['ok']
    assert storage.get_twitcasting_password(url, persist=False) == 'pw'
    assert storage.forget_twitcasting_password(url, persist=False)['ok']
    assert storage.get_twitcasting_password(url, persist=False) is None
    assert workbook.read_bytes() == b'untouched workbook'


def test_disk_option_survives_restart_but_memory_option_does_not(storage, tmp_path):
    url = 'https://twitcasting.tv/user/movie/123'
    storage.save_twitcasting_password(url, 'pw', persist=True)
    restarted = StorageService(tmp_path, AppState(), validate_config, Mock(), Mock())
    assert restarted.get_twitcasting_password(url, persist=False) is None
    assert restarted.get_twitcasting_password(url, persist=True) == 'pw'
    restarted.forget_twitcasting_password(url, persist=True)
    again = StorageService(tmp_path, AppState(), validate_config, Mock(), Mock())
    assert again.get_twitcasting_password(url, persist=True) is None


@pytest.mark.parametrize('remember,disk', [(0, 0), (0, 1), (1, 0), (1, 1)])
def test_single_success_only_remembers_with_selected_policy(tmp_path, remember, disk):
    executor, _ = create_executor(tmp_path)
    executor._tc_config = {'TC_REMEMBER_PASSWORD': remember, 'TC_SAVE_PASSWORD_XLSX': disk}
    save = executor._save_twitcasting_password_cb = Mock()
    target = tmp_path / 'out.mp4'
    target.touch()
    Path(str(target) + '.ytdl').touch()
    process = Mock(returncode=0)
    process.poll.return_value = 0
    executor._spawn = Mock(return_value=process)
    lines, done = Queue(), Event()
    lines.put('[download] Destination: ' + str(target))
    done.set()
    executor._start_reader = Mock(return_value=(lines, done))
    handle = executor._download_manager.begin('single')
    url = 'https://twitcasting.tv/user/movie/123'
    executor._run_single(handle, ['yt-dlp', '--video-password', 'pw', url], url, 'TwitCasting', False)
    if remember:
        save.assert_called_once_with(url, 'pw', persist=bool(disk))
    else:
        save.assert_not_called()
    assert not Path(str(target) + '.ytdl').exists()


@pytest.mark.parametrize('remember,disk', [(0, 0), (0, 1), (1, 0), (1, 1)])
def test_saved_password_lookup_and_forget_obey_both_switches(tmp_path, remember, disk):
    executor, _ = create_executor(tmp_path)
    config = {'TC_REMEMBER_PASSWORD': remember, 'TC_SAVE_PASSWORD_XLSX': disk}
    get = executor._get_twitcasting_password_cb = Mock(return_value='pw')
    forget = executor._forget_twitcasting_password_cb = Mock()
    executor._tc_config = config
    assert executor._saved_twitcasting_password('url', 'TwitCasting', config) == ('pw' if remember else None)
    executor._forget_twitcasting_password('url', 'TwitCasting')
    executor._saved_twitcasting_password('url', 'YouTube', config)
    executor._forget_twitcasting_password('url', 'YouTube')
    if remember:
        get.assert_called_once_with('url', persist=bool(disk))
        forget.assert_called_once_with('url', persist=bool(disk))
    else:
        get.assert_not_called()
        forget.assert_not_called()


def test_batch_reads_and_saves_password_using_task_snapshot(tmp_path):
    executor, callbacks = create_executor(tmp_path)
    url = 'https://twitcasting.tv/user/movie/123'
    get = executor._get_twitcasting_password_cb = Mock(return_value='pw')
    save = executor._save_twitcasting_password_cb = Mock()
    callbacks['build_command'].side_effect = lambda url, **kw: ['yt-dlp', '--video-password', kw['config_override']['TC_PASSWORD'], url]
    target = tmp_path / 'out.mp4'
    target.touch()
    process = Mock(returncode=0)
    process.poll.return_value = 0
    executor._spawn = Mock(return_value=process)
    lines, done = Queue(), Event()
    lines.put('[download] Destination: ' + str(target))
    done.set()
    executor._start_reader = Mock(return_value=(lines, done))
    handle = executor._download_manager.begin('batch')
    config = {'PLATFORM': 'TwitCasting', 'TC_REMEMBER_PASSWORD': 1, 'TC_SAVE_PASSWORD_XLSX': 0}
    executor._run_batch(handle, [url], config, {'ok': 0, 'fail': 0, 'total': 1})
    get.assert_called_once_with(url, persist=False)
    save.assert_called_once_with(url, 'pw', persist=False)


@pytest.mark.parametrize('enabled', [0, 1])
def test_live_success_uses_existing_runner_and_opt_in_storage(tmp_path, enabled):
    executor, _ = create_executor(tmp_path)
    url = 'https://twitcasting.tv/user'
    target = tmp_path / 'live.mp4'
    target.touch()
    save = executor._save_twitcasting_password_cb = Mock()
    executor._effective_live_mode = 'live_edge'
    executor._live_config = {'TC_REMEMBER_PASSWORD': enabled, 'TC_SAVE_PASSWORD_XLSX': 1}
    runner = Mock()
    runner.run.return_value = {'status': 'success', 'output': str(target), 'title': 'live', 'report': 'report.json'}
    handle = executor._download_manager.begin('single')
    with patch('video_downloader.services.download_executor.LiveRunner', return_value=runner):
        executor._run_live(handle, ['yt-dlp', '--video-password', 'pw', url], url, 'TwitCasting')
    assert runner.run.call_args.kwargs['mode'] == 'live_edge'
    if enabled:
        save.assert_called_once_with(url, 'pw', persist=True)
    else:
        save.assert_not_called()


def test_task_and_legacy_executors_share_the_password_store(tmp_path):
    from video_downloader import container
    task_manager = container.TaskManager
    with patch.object(container, 'TaskManager', wraps=task_manager) as factory:
        app = container.AppContainer(tmp_path, '.exe').wire()
    try:
        make = factory.call_args.kwargs['executor_factory']
        callbacks = SimpleNamespace(**{name: Mock() for name in ('log', 'update_progress', 'broadcast_download_state', 'add_history', 'cancel_idle_timer', 'start_idle_timer', 'emit_event')})
        executor = make(SimpleNamespace(selection={}), AppState(), Mock(), callbacks, Mock())
        store = executor._save_twitcasting_password_cb.__self__
        assert executor._get_twitcasting_password_cb.__self__ is store
        assert executor._forget_twitcasting_password_cb.__self__ is store
        executor._tc_config = {'TC_REMEMBER_PASSWORD': 1, 'TC_SAVE_PASSWORD_XLSX': 0}
        executor._remember_twitcasting_password('url', 'TwitCasting', ['yt-dlp', '--video-password', 'pw'])
        assert store.get_twitcasting_password('url', persist=False) == 'pw'
        assert not store._tc_password_file.exists()
    finally:
        app.request_exit()


def test_sidecar_survives_until_output_exists(tmp_path):
    executor, _ = create_executor(tmp_path)
    target = tmp_path / 'missing.mp4'
    sidecar = Path(str(target) + '.ytdl')
    sidecar.touch()
    assert not executor._remove_ytdl_sidecar(target)
    assert sidecar.exists()


def test_failed_plugin_fallback_keeps_subtitles_and_forces_ffmpeg(tmp_path):
    executor, _ = create_executor(tmp_path)
    cmd = ['yt-dlp', '--enable-file-urls', '--use-postprocessor', 'TwitCastingParallelHls:when=before_dl', '--skip-download', '--write-subs', 'url']
    result = executor._without_twitcasting_parallel(cmd)
    assert result[result.index('--downloader') + 1] == 'm3u8:ffmpeg'
    assert '--write-subs' in result and '--skip-download' in result
    assert not executor._has_twitcasting_parallel(result)
    assert executor._without_twitcasting_parallel(result) == result


def test_imported_config_and_niconico_targets_remain_consistent(storage):
    storage._config_file.write_text('[settings]\nlive_record_mode=current\n', encoding='utf-8')
    assert storage.load_config()['LIVE_MODE'] == 'live_edge'
    storage._config_file.write_text('[settings]\nlive_record_mode=from_start\nlive_mode=live_edge\n', encoding='utf-8')
    assert storage.load_config()['LIVE_MODE'] == 'live_edge'
    for host in ['nicovideo.jp', 'www.nicovideo.jp', 'm.nicovideo.jp']:
        url = 'https://' + host + '/watch/lv123'
        assert is_live_url(url, 'Niconico')
        target = classify_target(url, 'Niconico')
        assert target.kind is TargetKind.EVENT and target.stable_id == 'lv123'
    assert not is_live_url('https://www.nicovideo.jp/watch/sm123', 'Niconico')
