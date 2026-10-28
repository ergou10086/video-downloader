"""Release acceptance invariants shared by every generic WAIT platform."""
import base64
import json
import sqlite3
import threading
from unittest.mock import Mock, patch

import pytest

from video_downloader.live.wait import LiveWatchService, WatchJobStore, WatchStatus
from video_downloader.live.probe import LiveProbe, LiveStatus
from video_downloader.live.urls import TargetKind
from video_downloader.live.danmaku.nicochannel import normalize
from video_downloader.services.nicochannel_auth import NicochannelAuthService
from tests.helpers.download import create_executor

URLS = {
 'YouTube':'https://www.youtube.com/watch?v=abcdef12345',
 'Twitch':'https://www.twitch.tv/example',
 'Bilibili':'https://live.bilibili.com/1',
 'TwitCasting':'https://twitcasting.tv/example',
 'NicoChannel':'https://nicochannel.jp/example/live/smABC',
 'Niconico':'https://live.nicovideo.jp/watch/lv123',
 'Twitter':'https://x.com/i/spaces/1test',
}


@pytest.mark.parametrize('platform', URLS)
@pytest.mark.parametrize('scheduled', [970, 1000, 1030, 100000])
def test_wait_early_late_offline_retry_deleted_matrix(tmp_path, platform, scheduled):
    now=[1000.]
    probe=Mock()
    probe.probe.side_effect=[
      LiveProbe(platform,TargetKind.EVENT,'id',LiveStatus.UPCOMING,scheduled_start=scheduled),
      LiveProbe(platform,TargetKind.EVENT,'id',LiveStatus.OFFLINE),
      ConnectionError('https://secret?token=private'),
      LiveProbe(platform,TargetKind.EVENT,'id',LiveStatus.LIVE),
    ]
    called=[]
    store=WatchJobStore(tmp_path/'wait.sqlite')
    service=LiveWatchService(store=store,probe_service=probe,on_live=lambda *a:called.append(a) or {},
                             clock=lambda:now[0],jitter=lambda:1,start_thread=False)
    try:
        added=service.add(URLS[platform],platform)
        assert 'error' not in added, added
        id=added['job']['id']
        for expected in [WatchStatus.WAITING_NEAR,WatchStatus.WAITING,WatchStatus.WAITING,WatchStatus.TRIGGERED]:
            assert service.tick(wait=True)==1
            job=store.get(id)
            assert job.status is expected
            assert 'private' not in job.last_error
            if job.next_probe_at is not None:now[0]=job.next_probe_at
        assert len(called)==1 and service.tick(wait=True)==0
        # A deleted/permission-denied event never dispatches.
        probe.probe.side_effect=None
        probe.probe.return_value=LiveProbe(platform,TargetKind.EVENT,'id',LiveStatus.PRIVATE)
        other=service.add(URLS[platform],platform)
        service.tick(wait=True)
        assert store.get(other['job']['id']).status is WatchStatus.EXPIRED
        assert len(called)==1
    finally:service.stop()


def test_cancel_during_failed_probe_cannot_resurrect(tmp_path):
    entered,release=threading.Event(),threading.Event()
    def probe(*a,**kw):
        entered.set();assert release.wait(3);raise ConnectionError('secret')
    store=WatchJobStore(tmp_path/'wait.sqlite')
    service=LiveWatchService(store=store,probe_service=Mock(probe=probe),on_live=Mock(),
                             clock=lambda:1000,jitter=lambda:1,start_thread=False)
    try:
        id=service.add(URLS['Bilibili'])['job']['id']
        service.tick()
        assert entered.wait(3)
        assert service.cancel(id)['ok']
        release.set()
        service.stop()
        assert store.get(id).status is WatchStatus.CANCELLED
    finally:release.set();service.stop()


def test_claim_is_atomic_and_restart_does_not_repeat_dispatch(tmp_path):
    store=WatchJobStore(tmp_path/'wait.sqlite')
    service=LiveWatchService(store=store,probe_service=Mock(),on_live=Mock(),
                             clock=lambda:1000,start_thread=False)
    try:
        id=service.add(URLS['Bilibili'])['job']['id']
        assert store.claim(id,1000) and not store.claim(id,1000)
        job=store.get(id);job.status=WatchStatus.STARTING;store.update(job)
        store.recover_interrupted()
        assert store.get(id).status is WatchStatus.ERROR
        assert not store.due(1e12)
    finally:service.stop()


def jwt(exp):
    encode=lambda x:base64.urlsafe_b64encode(json.dumps(x).encode()).decode().rstrip('=')
    return encode({'alg':'none'})+'.'+encode({'exp':exp})+'.sig'


def test_latest_unexpired_nico_token_and_active_wal(tmp_path):
    service=NicochannelAuthService(log=Mock())
    import time
    tokens=[jwt(time.time()-1),jwt(time.time()+120),jwt(time.time()+300)]
    items={str(i):json.dumps({'body':{'access_token':token}}) for i,token in enumerate(tokens)}
    items['array']='["access_token"]'
    assert service._find_jwt(items)==tokens[-1]
    db=tmp_path/'storage/default/https+++nicochannel.jp/ls/data.sqlite'
    db.parent.mkdir(parents=True)
    con=sqlite3.connect(db)
    try:
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('CREATE TABLE data(key TEXT,conversion_type INT,compression_type INT,value BLOB)')
        con.commit()
        con.execute('INSERT INTO data VALUES(?,?,?,?)',('active',1,0,b'fresh'))
        con.commit()
        result=service._extract_localstorage(str(tmp_path),None,'https://nicochannel.jp',None,Mock(),Mock())
        assert result=={'active':'fresh'}
    finally:con.close()
    assert normalize({'message':'hi','playback_time':1.234},'sm1',2).relative_ms==1234
    assert normalize({'message':'hi','playback_time':1.234},'sm1',2).time_source=='source_relative'


def test_twitcasting_live_plugin_failure_falls_back_once(tmp_path):
    executor,_=create_executor(tmp_path)
    url=URLS['TwitCasting']
    executor._effective_live_mode='live_edge'
    executor._live_config={}
    failure={'status':'fail','output':'','report':'report','title':'live','error_lines':['KeyError: TwitCastingParallelHlsPP']}
    runner=Mock()
    runner.run.side_effect=[failure,dict(failure,error_lines=[])]
    handle=executor._download_manager.begin('single')
    with patch('video_downloader.services.download_executor.LiveRunner',return_value=runner):
        executor._run_live(handle,['yt-dlp','--enable-file-urls','--use-postprocessor',
                                   'TwitCastingParallelHls:when=before_dl',url],url,'TwitCasting')
    assert runner.run.call_count==2
    retry=runner.run.call_args.args[0]
    assert '--enable-file-urls' not in retry
    assert 'm3u8:ffmpeg' in retry
    assert executor._command_video_password(['app','--video-password=secret'])=='secret'

@pytest.mark.parametrize('status', ['stopped','timeout'])
def test_twitcasting_verified_stop_remembers_opt_in_password(tmp_path,status):
    executor,_=create_executor(tmp_path)
    output=tmp_path/'verified.mp4';output.write_bytes(b'verified-by-runner')
    executor._effective_live_mode='live_edge'
    executor._live_config={'TC_REMEMBER_PASSWORD':1,'TC_SAVE_PASSWORD_XLSX':0}
    save=executor._save_twitcasting_password_cb=Mock()
    runner=Mock()
    runner.run.return_value={'status':status,'conclusion':'complete','output':str(output),'title':'live','report':'report'}
    handle=executor._download_manager.begin('single')
    with patch('video_downloader.services.download_executor.LiveRunner',return_value=runner):
        executor._run_live(handle,['app','--video-password=pw',URLS['TwitCasting']],URLS['TwitCasting'],'TwitCasting')
    save.assert_called_once_with(URLS['TwitCasting'],'pw',persist=False)
