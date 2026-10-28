"""Clock proofs use encoded packets, including real TS-to-MP4 remuxes."""
from tests.helpers import PROJECT_ROOT
from pathlib import Path
from unittest.mock import patch
import subprocess

import pytest

from video_downloader.live.clock import MediaClock, audio_packets, attributes, match, playlist
from video_downloader.live.danmaku.timeline import project
from video_downloader.live.danmaku.models import CommentEvent

ROOT = PROJECT_ROOT


def test_hls_clock_discontinuities_encryption_and_variant():
    assert attributes('BANDWIDTH=1200,NAME="a,b"')['NAME'] == 'a,b'
    variants, _ = playlist('#EXT-X-STREAM-INF:BANDWIDTH=12,RESOLUTION=320x180\nlow.m3u8', 'https://host/a/')
    assert variants[0]['url'] == 'https://host/a/low.m3u8'
    text = '''#EXT-X-MEDIA-SEQUENCE:70
#EXT-X-PROGRAM-DATE-TIME:2026-10-27T00:00:00Z
#EXTINF:2,
a.ts
#EXTINF:2,
b.ts
#EXT-X-DISCONTINUITY
#EXTINF:2,
c.ts
#EXT-X-PROGRAM-DATE-TIME:2026-10-27T00:00:06Z
#EXT-X-KEY:METHOD=AES-128,URI="secret"
#EXTINF:2,
d.ts
'''
    _, segments = playlist(text, 'https://host/')
    assert segments[1]['utc'] - segments[0]['utc'] == 2
    assert segments[2]['utc'] is None and segments[2]['discontinuity'] == 1
    assert not segments[3]['supported'] and segments[3]['sequence'] == 73


@pytest.fixture
def media(tmp_path):
    ffmpeg, ffprobe = ROOT/'dependency/ffmpeg.exe', ROOT/'dependency/ffprobe.exe'
    if not ffmpeg.is_file() or not ffprobe.is_file():
        pytest.skip('requires managed FFmpeg')
    def run(args):
        subprocess.run([str(ffmpeg),'-hide_banner','-loglevel','error','-nostdin','-y',*map(str,args)],
                       check=True,capture_output=True,timeout=40)
    run(['-f','lavfi','-i','testsrc2=size=160x90:rate=25','-f','lavfi','-i','anoisesrc=seed=42:r=48000',
         '-t','8','-c:v','libx264','-g','50','-bf','2','-c:a','aac','-f','hls','-hls_time','2',
         '-hls_list_size','0','-hls_flags','program_date_time',tmp_path/'source.m3u8'])
    run(['-i',tmp_path/'source.m3u8','-c','copy',tmp_path/'recording.mp4'])
    return ffprobe,tmp_path


def test_real_aac_payload_proves_pdt_container_mapping(media):
    ffprobe, root = media
    _, segments = playlist((root/'source.m3u8').read_text(), root.as_uri()+'/')
    segment = segments[1]
    packets, origin = audio_packets(ffprobe, root/'source1.ts')
    recorded, dest_origin = audio_packets(ffprobe, root/'recording.mp4')
    sample = dict(segment, packets=packets[:64], source_origin=origin)
    result = match(sample, recorded, dest_origin)
    assert result and result['error_ms'] < 2000
    src = packets[0]
    target = next(p for p in recorded if p['hash'] == src['hash'])
    expected = segment['utc'] + src['pts']-origin-(target['pts']-dest_origin)
    assert abs(result['origin_utc']-expected) < .002
    assert match(sample, [], dest_origin) is None
    assert match(sample, recorded+recorded, dest_origin) is None
    silent = dict(sample,packets=[{'hash':'silent','pts':i/48} for i in range(64)])
    assert match(silent, silent['packets'], 0) is None
    clock=MediaClock(root, ['app'], ffprobe)
    clock.samples=[dict(sample,observed_at=1001)]
    report={'files':[{'path':str(root/'recording.mp4')}]}
    clock.annotate(report, {'started_at':1000})
    evidence=report['files'][0]['comment_clock']
    assert evidence['matched_count']==1 and evidence['ranges'][0]['error_ms'] < 2000


def test_clock_projection_never_certifies_receive_time_or_uncovered_events():
    def event(stamp, source='server'):
        return CommentEvent('Twitch','r','s',0,'hi',utc_ts=stamp,time_source=source)
    ranges=[{'utc_start':1001,'utc_end':1003,'origin_utc':1000,'error_ms':500}]
    stats={}
    result=list(project([event(1002),event(1004),event(1002,'receive')],segment='p',
                        anchor_utc=999,mode='live_edge',platform='Twitch',clock_ranges=ranges,stats=stats))
    assert [e.relative_ms for e in result] == [2000,5000,3000]
    assert stats['clock_verified_count']==1 and stats['clock_estimated_count']==2
    assert stats['anchor_error_ms'] is None


def test_clock_observer_failure_is_independent_and_redacted(tmp_path):
    clock=MediaClock(tmp_path,['app'],'ffprobe')
    with patch('video_downloader.live.clock.Transport', side_effect=ValueError('https://private?token=secret')):
        clock._observe_once({'url':'https://private?token=secret'})
    assert clock.errors == ['ValueError']
    clock.stop()

def test_observer_captures_scopes_credentials_and_cleans_sample(media):
    from unittest.mock import Mock
    ffprobe, root = media
    playlist_text=(root/'source.m3u8').read_bytes()
    clock=MediaClock(root, ['app'], ffprobe)
    transport=Mock()
    fetched=[]
    def response(url, **kw):
        fetched.append((url,kw.get('headers',{})))
        if url=='https://media.test/master':
            return b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100,RESOLUTION=160x90\nhttps://cdn.test/source.m3u8'
        if url.endswith('.m3u8'):return playlist_text
        return (root/Path(url).name).read_bytes()
    transport.response.side_effect=response
    clock.stop_event.wait=lambda _:True
    with patch('video_downloader.live.clock.Transport',return_value=transport):
        clock._observe_once({'url':'https://media.test/master','height':90,
                             'http_headers':{'Authorization':'secret','Referer':'https://origin.test'}})
    assert len(clock.samples)==1
    assert fetched[0][1]['Authorization']=='secret'
    assert all('Authorization' not in headers for _,headers in fetched[1:])
    assert not list(root.glob('*.clock-sample'))
    assert 'secret' not in (root/'clock-samples.json').read_text()
    assert transport.close.called


def test_observer_budgets_cycle_and_unsupported_formats(tmp_path):
    from unittest.mock import Mock
    transport=Mock()
    transport.response.return_value=b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nmaster'
    clock=MediaClock(tmp_path,['app'],'probe')
    with patch('video_downloader.live.clock.Transport',return_value=transport):
        clock._observe_once({'url':'https://host/master'})
    assert clock.errors==['ValueError']
    clock=MediaClock(tmp_path,['app'],'probe')
    text=b'#EXTM3U\n#EXT-X-PROGRAM-DATE-TIME:2026-10-27T00:00:00Z\n#EXTINF:2,\na.ts'
    transport.response.return_value=text
    clock.samples=[{}]*64
    with patch('video_downloader.live.clock.Transport',return_value=transport):
        clock._observe_once({'url':'https://host/a.m3u8'})
    assert 'clock_sampling_budget_exhausted' in clock.errors
    clock=MediaClock(tmp_path,['app'],'probe')
    clock.start({'url':'https://host/video.mp4','protocol':'https'})
    assert clock.thread is None
    with pytest.raises(ValueError):playlist('#EXTINF:NaN,\na.ts','https://host')
    with patch('video_downloader.live.clock.subprocess.run',return_value=Mock(returncode=0,stdout=b'{"streams":[{"codec_name":"opus"}]}')):
        with pytest.raises(ValueError,match='unsupported'):audio_packets('probe','file')


def test_annotator_rejects_non_matching_media_and_reports_stop_timeout(tmp_path):
    from unittest.mock import Mock
    clock=MediaClock(tmp_path,['app'],'probe')
    clock.thread=Mock()
    clock.thread.is_alive.return_value=True
    clock.transport=Mock()
    clock.stop()
    assert clock.transport.close.called and 'clock_observer_stop_timeout' in clock.errors
    clock.samples=[{'observed_at':2}]
    report={'files':[{'path':str(tmp_path/'file.mp4')},{'path':str(tmp_path.parent/'outside.mp4')}]}
    with patch('video_downloader.live.clock.audio_packets',side_effect=ValueError):
        clock.annotate(report,{'started_at':1})
    assert report['files'][0]['comment_clock']['matched_count']==0
    assert 'comment_clock' not in report['files'][1]
