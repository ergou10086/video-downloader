"""Conditional metadata, tail isolation and actual FFmpeg overlap reconciliation."""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from video_downloader.core.paths import AppPaths
from video_downloader.live import process
from video_downloader.live.catchup import (BackfillJob, CatchUpEvidence, CatchUpPlanner,
                                           assess_youtube, at_live_edge, metadata_command)
from video_downloader.live.inspect import LiveInspector
from video_downloader.live.integrity import IntegrityChecker
from video_downloader.live.probe import LiveProbe, LiveStatus, YtDlpProbe
from video_downloader.live.runner import LiveRunner
from video_downloader.live.session import LiveSession
from video_downloader.live.splice import overlap_boundary, packets, reconcile
from video_downloader.live.urls import TargetKind, classify_target

ROOT = Path(__file__).resolve().parents[1]


class CatchUpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def metadata(self, info):
        return SimpleNamespace(returncode=0, stdout=json.dumps(info))

    def runner(self):
        return LiveRunner(AppPaths(self.root), '.exe', log=Mock(), progress=Mock(),
                          publish_process=Mock(return_value=True), clear_process=Mock(),
                          force_kill=Mock(), emit_event=Mock())

    def test_probe_context_preserves_routing_and_auth_without_download_effects(self):
        command = ['yt-dlp','--proxy','','--cookies','private.txt','--extractor-args=youtube:player_client=default',
                   '-o','bad','--download-archive','archive','--exec','bad','--plugin-dirs','plugins','--force-ipv4','url']
        result = metadata_command(command, 'https://example.test/live', from_start=True)
        self.assertIn('private.txt', result)
        self.assertEqual(result[result.index('--proxy') + 1], '')
        self.assertIn('--extractor-args=youtube:player_client=default', result)
        self.assertNotIn('--download-archive', result)
        self.assertNotIn('--exec', result)
        self.assertNotIn('-o', result)
        self.assertIn('--simulate', result)
        self.assertIn('--live-from-start', result)
        self.assertEqual(at_live_edge(['app','--live-from-start','url'])[-1], '--no-live-from-start')

    def test_youtube_requires_live_and_from_start_dash_evidence(self):
        info = {'is_live':True,'formats':[{'protocol':'http_dash_segments_generator','is_from_start':True}]}
        self.assertTrue(assess_youtube(info).available)
        for bad in [{}, {'is_live':True,'formats':[{'protocol':'m3u8_native'}]},
                    {'is_live':False,'formats':info['formats']}]:
            self.assertFalse(assess_youtube(bad).available)
        planner = CatchUpPlanner(lambda *_: self.metadata(info))
        self.assertEqual(planner.probe(['app'],'url','YouTube').strategy,'single_from_start')

    def test_twitch_only_matches_current_broadcast_same_channel(self):
        edge = {'is_live':True,'timestamp':1000,'uploader_id':'Channel'}
        vod = {'id':'v123','timestamp':1001,'uploader_id':'channel','formats':[{'is_from_start':True}]}
        planner = CatchUpPlanner(Mock(side_effect=[self.metadata(edge),self.metadata(vod)]))
        evidence = planner.probe(['app'],'url','Twitch')
        self.assertTrue(evidence.available)
        self.assertEqual(evidence.archive_url, 'https://www.twitch.tv/videos/123')
        for override in [{'timestamp':500},{'uploader_id':'other'},{'id':'123'},{'formats':[]}, {'timestamp':float('nan')}]:
            planner = CatchUpPlanner(lambda *_: self.metadata(dict(vod, **override)))
            self.assertFalse(planner.probe(['app'],'url','Twitch',edge_info=edge).available)
        self.assertFalse(CatchUpPlanner().probe(['app'],'url','Bilibili').available)

    def test_probe_failure_downgrades_instead_of_raising(self):
        for runner in [Mock(side_effect=subprocess.TimeoutExpired('app',1)),
                       Mock(return_value=SimpleNamespace(returncode=1,stdout='')),
                       Mock(return_value=SimpleNamespace(returncode=0,stdout='[]')),
                       Mock(return_value=SimpleNamespace(returncode=0,stdout='invalid'))]:
            self.assertFalse(CatchUpPlanner(runner).probe(['app'],'url','YouTube').available)
        planner = CatchUpPlanner(lambda *_: self.metadata({'is_live':False}))
        self.assertFalse(planner.probe(['app'],'url','Twitch').available)

    def test_inspection_does_not_offer_unverified_catchup_and_explains_auto_fallback(self):
        probe = LiveProbe('YouTube',TargetKind.EVENT,'abc',LiveStatus.LIVE)
        service = SimpleNamespace(probe=lambda *_a, **_k:probe)
        result = LiveInspector(service).inspect('https://youtube.com/live/abc','auto')
        self.assertEqual(result['effective_mode'],'live_edge')
        self.assertTrue(result['downgraded'])
        self.assertFalse(result['modes'][0]['available'])
        probe = replace(probe,catch_up_available=True,catch_up_reason='verified')
        self.assertEqual(LiveInspector(service).inspect('https://youtube.com/live/abc')['effective_mode'],'catch_up')

    def test_ytdlp_probe_combines_live_status_with_catchup_and_config_context(self):
        edge = {'is_live':True,'id':'abc','timestamp':1000}
        vod = dict(edge,formats=[{'protocol':'http_dash_segments_generator','is_from_start':True}])
        runner = Mock(side_effect=[self.metadata(edge),self.metadata(vod)])
        provider = YtDlpProbe('app',runner=runner,command_context=lambda _:['app','--proxy','http://proxy:1'])
        result = provider.probe(classify_target('https://youtube.com/live/abc'))
        self.assertTrue(result.catch_up_available)
        self.assertTrue(result.to_dict()['catch_up_available'])
        for call in runner.call_args_list:
            self.assertIn('http://proxy:1',call.args[0])

    def test_runner_actual_downgrade_uses_edge_without_backfill(self):
        runner = self.runner()
        proc = SimpleNamespace(stdout=io.BytesIO(),poll=lambda:0,wait=lambda timeout:0,returncode=0)
        with patch('video_downloader.live.runner.CatchUpPlanner') as planner, patch.object(process,'spawn',return_value=proc) as spawn:
            planner.return_value.probe.return_value = CatchUpEvidence(False,'DVR disabled')
            result = runner.run(['app','--live-from-start','url'],url='url',platform='YouTube',mode='catch_up',
                                config={},cancel=threading.Event())
        self.assertIn('--no-live-from-start',spawn.call_args.args[0])
        self.assertNotIn('--live-from-start',spawn.call_args.args[0])
        session = json.loads((Path(result['report']).parent/'session.json').read_text(encoding='utf-8'))
        self.assertEqual(session['mode'],'live_edge')
        self.assertEqual(session['requested_mode'],'catch_up')

    def test_runtime_catchup_error_always_attempts_live_tail(self):
        runner = self.runner()
        cancel = threading.Event()
        cancel.wait = Mock(return_value=False)
        def spawned(*args,**kwargs):
            return SimpleNamespace(stdout=io.BytesIO(),poll=lambda:9,wait=lambda timeout:9,returncode=9)
        with patch('video_downloader.live.runner.CatchUpPlanner') as planner, patch.object(process,'spawn',side_effect=spawned) as spawn:
            planner.return_value.probe.return_value = CatchUpEvidence(True,'DASH','single_from_start')
            runner.run(['app','--live-from-start','url'],url='url',platform='YouTube',mode='catch_up',
                       config={'LIVE_MAX_RETRIES':0},cancel=cancel)
        self.assertEqual(spawn.call_count,2)
        self.assertIn('--no-live-from-start',spawn.call_args.args[0])

    def test_cancel_does_not_start_a_network_probe(self):
        cancel = threading.Event()
        cancel.set()
        with patch('video_downloader.live.runner.CatchUpPlanner') as planner:
            self.runner().run(['app'],url='url',platform='YouTube',mode='catch_up',config={},cancel=cancel)
        planner.assert_not_called()

    def test_metadata_process_can_be_cancelled_and_timed_out(self):
        import time
        command = [sys.executable,'-c','import time; time.sleep(30)']
        cancel=threading.Event()
        timer=threading.Timer(0.2,cancel.set)
        timer.start()
        try:
            started=time.monotonic()
            with self.assertRaisesRegex(OSError,'probe_cancelled'):
                CatchUpPlanner(cancel=cancel)._run(command,20)
            self.assertLess(time.monotonic()-started,5)
        finally:
            timer.cancel()
        with self.assertRaises(subprocess.TimeoutExpired):
            CatchUpPlanner()._run(command,0.2)
        result=CatchUpPlanner()._run([sys.executable,'-c','print(1)'],5)
        self.assertEqual(result.returncode,0)
        self.assertEqual(result.stdout.strip(),'1')

    def test_twitch_audio_preferences_downgrade_before_spawning_backfill(self):
        runner = self.runner()
        proc = SimpleNamespace(stdout=io.BytesIO(),poll=lambda:0,wait=lambda timeout:0,returncode=0)
        evidence = CatchUpEvidence(True,'VOD','tail_and_backfill','https://twitch.tv/videos/1',1000)
        with patch('video_downloader.live.runner.CatchUpPlanner') as planner, patch.object(process,'spawn',return_value=proc):
            planner.return_value.probe.return_value = evidence
            result = runner.run(['app','--live-from-start','url'],url='url',platform='Twitch',mode='catch_up',
                                config={'AUDIO_MODE':'3'},cancel=threading.Event())
        self.assertEqual(runner.session.data['mode'],'live_edge')
        self.assertIn('音频',runner.session.data['catch_up']['reason'])
        self.assertNotIn('backfill',json.loads(Path(result['report']).read_text(encoding='utf-8')))

    def test_twitch_insufficient_backfill_space_preserves_live_edge_budget(self):
        runner = self.runner()
        proc = SimpleNamespace(stdout=io.BytesIO(),poll=lambda:0,wait=lambda timeout:0,returncode=0)
        evidence = CatchUpEvidence(True,'VOD','tail_and_backfill','https://twitch.tv/videos/1',1000)
        with patch('video_downloader.live.runner.CatchUpPlanner') as planner, patch.object(process,'spawn',return_value=proc), \
                patch('video_downloader.live.runner.shutil.disk_usage',return_value=SimpleNamespace(free=2*1024**3)):
            planner.return_value.probe.return_value = evidence
            runner.run(['app','url'],url='url',platform='Twitch',mode='catch_up',config={},cancel=threading.Event())
        self.assertEqual(runner.session.data['mode'],'live_edge')
        self.assertIn('磁盘',runner.session.data['catch_up']['reason'])

    def test_backfill_failure_is_bounded_and_separate_from_primary_process(self):
        session = LiveSession(self.root,'Twitch','catch_up','url')
        evidence = CatchUpEvidence(True,'VOD','tail_and_backfill','https://twitch.tv/videos/1',1000)
        job = BackfillJob(['app','-f','best','--proxy','','url'],evidence,session,{},Mock())
        proc = Mock(returncode=1)
        proc.poll.return_value = 1
        with patch.object(process,'spawn',return_value=proc) as spawn:
            job.start()
            job.finish()
        self.assertEqual(job.exit_code,1)
        self.assertIn('--download-sections',spawn.call_args.args[0])
        self.assertNotIn('private', (session.root/'events.jsonl').read_text(encoding='utf-8'))
        self.assertFalse(job.thread.is_alive())

    def test_overlap_proof_needs_both_streams_consistent_unique_and_keyframe(self):
        tail = [{'codec_type':kind,'data_hash':kind+str(i),'dts':i/10,'flags':'K' if i==0 else ''}
                for kind in ('video','audio') for i in range(10)]
        back = [dict(p,dts=p['dts']+20) for p in tail]
        prefix = [{'codec_type':'video','data_hash':'prefix','dts':0,'flags':'K'}]
        self.assertEqual(overlap_boundary(iter(prefix+back),tail),20)
        for before, after in [(back,tail), (prefix+back+back,tail), (prefix+back,tail[1:]),
                              (prefix+back,[p for p in tail if p['codec_type']=='video'])]:
            with self.assertRaises(ValueError):
                overlap_boundary(before,after)
        wrong = [dict(p,dts=p['dts']+1) if p['codec_type']=='audio' else p for p in back]
        with self.assertRaisesRegex(ValueError,'anchor_disagree'):
            overlap_boundary(prefix+wrong,tail)


@unittest.skipUnless((ROOT/'dependency/ffmpeg.exe').exists(),'FFmpeg not installed')
class ActualOverlapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ffmpeg, self.ffprobe = (str(ROOT/'dependency'/n) for n in ('ffmpeg.exe','ffprobe.exe'))
        self.checker = IntegrityChecker(self.ffprobe,self.ffmpeg)

    def run_ffmpeg(self, *args):
        subprocess.run([self.ffmpeg,'-v','error','-nostdin','-y',*map(str,args)],check=True,
                       capture_output=True,timeout=30,**process.hidden_options())

    def test_real_overlapping_mkv_clips_join_with_zero_duplicate_packets(self):
        source, tail = self.root/'source.mkv',self.root/'tail.mkv'
        self.run_ffmpeg('-f','lavfi','-i','testsrc=size=160x90:rate=10','-f','lavfi','-i',
                        'sine=frequency=537:sample_rate=48000','-t','12','-c:v','libx264','-bf','0',
                        '-preset','ultrafast','-g','20','-pix_fmt','yuv420p','-c:a','aac',source)
        self.run_ffmpeg('-ss','6','-i',source,'-c','copy',tail)
        session = LiveSession(self.root/'sessions','Twitch','catch_up','fixture')
        report = {'files':[self.checker.inspect(tail)]}
        result = reconcile(session,self.checker,[source],report)
        self.assertEqual(result['status'],'joined',result)
        self.assertEqual(result['duplicate_packets_in_output'],0)
        self.assertAlmostEqual(report['joined']['duration'],12,delta=0.25)
        original_video = [p['data_hash'] for p in packets(self.ffprobe,source) if p['codec_type']=='video']
        joined_video = [p['data_hash'] for p in packets(self.ffprobe,result['joined']) if p['codec_type']=='video']
        self.assertEqual(original_video,joined_video)
        self.assertTrue(source.exists())
        self.assertTrue(tail.exists())
        # Attached cover art is a still-image video stream, not recording video.
        cover, covered, prefix = self.root/'cover.jpg',self.root/'covered.mp4',self.root/'prefix.mp4'
        self.run_ffmpeg('-f','lavfi','-i','color=blue:size=160x90','-frames:v','1',cover)
        self.run_ffmpeg('-i',source,'-c','copy','-video_track_timescale','90000',prefix)
        self.run_ffmpeg('-i',tail,'-i',cover,'-map','0','-map','1','-c','copy','-disposition:v:1','attached_pic',
                        '-video_track_timescale','90000',covered)
        covered_info = self.checker.inspect(covered)
        self.assertTrue(any(s['attached_pic'] for s in covered_info['streams']))
        covered_report = {'files':[covered_info]}
        result = reconcile(session,self.checker,[prefix],covered_report)
        self.assertEqual(result['status'],'joined',result)
        audio_cover = self.root/'audio-cover.m4a'
        self.run_ffmpeg('-i',prefix,'-i',cover,'-map','0:a','-map','1:v','-c','copy',
                        '-disposition:v:0','attached_pic',audio_cover)
        self.assertIn('missing_track',self.checker.inspect(audio_cover)['errors'])
        separate = self.checker.report([audio_cover],reason='ended',exit_codes=[0],mode='live_edge',expected='separate')
        self.assertEqual(separate['conclusion'],'failed')

    def test_unverified_join_keeps_tail_and_originals(self):
        session = LiveSession(self.root,'Twitch','catch_up','fixture')
        report = {'files':[]}
        result = reconcile(session,self.checker,[],report)
        self.assertEqual(result['status'],'unverified')
        self.assertNotIn('joined',report)

    def test_b_frames_keep_initial_payloads_with_missing_matroska_dts(self):
        source, tail = self.root/'bframes.mkv', self.root/'bframes-tail.mkv'
        self.run_ffmpeg('-f','lavfi','-i','testsrc2=size=160x90:rate=30','-f','lavfi','-i',
                        'anoisesrc=seed=42:r=48000','-t','12','-c:v','libx264','-bf','2',
                        '-g','60','-c:a','aac',source)
        self.run_ffmpeg('-ss','6','-i',source,'-c','copy',tail)
        original=list(packets(self.ffprobe,source))
        video=[p for p in original if p['codec_type']=='video']
        self.assertIn('K',video[0]['flags'])
        self.assertTrue(video[0].get('dts_inferred'))
        self.assertEqual(len(video),360)
        session=LiveSession(self.root/'sessions','Twitch','catch_up','b-frame-fixture')
        report={'files':[self.checker.inspect(tail)]}
        result=reconcile(session,self.checker,[source],report)
        self.assertEqual(result['status'],'joined',result)
        joined=list(packets(self.ffprobe,result['joined']))
        for kind in ('video','audio'):
            self.assertEqual([p['data_hash'] for p in original if p['codec_type']==kind],
                             [p['data_hash'] for p in joined if p['codec_type']==kind])

    def test_backfill_start_failure_does_not_kill_real_primary_media(self):
        paths = AppPaths(self.root)
        paths.executable = lambda name,suffix:Path({'ffmpeg':self.ffmpeg,'ffprobe':self.ffprobe}[name])
        publish = Mock(return_value=True)
        runner = LiveRunner(paths,'.exe',log=Mock(),progress=Mock(),publish_process=publish,
                            clear_process=Mock(),force_kill=lambda p:p.kill(),emit_event=Mock())
        engine = Mock(name='fixture')
        engine.name, engine.events = 'fixture', None
        engine.command = lambda d:[self.ffmpeg,'-v','error','-nostdin','-y','-f','lavfi','-i','testsrc=size=160x90:rate=10',
                                   '-f','lavfi','-i','sine=frequency=600','-t','2','-c:v','libx264','-preset','ultrafast',
                                   '-pix_fmt','yuv420p','-c:a','aac',str(d/'recording.mkv')]
        import time
        evidence = CatchUpEvidence(True,'VOD','tail_and_backfill','https://twitch.tv/videos/1',time.time())
        def failed_backfill(*_):
            self.assertEqual(publish.call_count,1, 'The live tail must start before backfill')
            raise OSError('backfill unavailable')
        with patch.object(runner,'_engine',return_value=engine), \
                patch('video_downloader.live.runner.CatchUpPlanner') as planner, \
                patch('video_downloader.live.runner.BackfillJob',side_effect=failed_backfill):
            planner.return_value.probe.return_value = evidence
            result = runner.run(['app','url'],url='url',platform='Twitch',mode='catch_up',config={},cancel=threading.Event())
        report=json.loads(Path(result['report']).read_text(encoding='utf-8'))
        self.assertTrue(report['files'][0]['valid'])
        self.assertEqual(report['stop_reason'],'ended')
        self.assertEqual(report['conclusion'],'gaps')
        self.assertTrue(Path(result['output']).exists())


if __name__ == '__main__':
    unittest.main()
