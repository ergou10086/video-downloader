"""Source format, crash recovery, privacy and real subtitle library round trips."""
from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from video_downloader.core.validation import validate_config
from video_downloader.live.danmaku.bilibili import read_xml
from video_downloader.live.danmaku.dependencies import library
from video_downloader.live.danmaku.exporter_ass import export_ass
from video_downloader.live.danmaku.exporter_srt import export_srt, plain_text, wrap
from video_downloader.live.danmaku.models import CommentEvent
from video_downloader.live.danmaku.service import process_comments
from video_downloader.live.danmaku.store import CommentStore
from video_downloader.live.session import LiveSession


XML = '''<?xml version="1.0" encoding="utf-8"?><i>
<BililiveRecorderRecordInfo roomid="123" start_time="2026-10-25T00:00:00+08:00"/>
<d p="1.250,1,25,16711680,1792857600123,0,42,0" user="观众">你好 &amp; hello</d>
<d p="2.000,5,25,16777215,1792857601123,0,43,0" user="顶部">固定</d>
<d p="3.000,4,25,16777215,0,0,44,0" user="底部">下方</d>
<sc ts="4.000" uid="45" user="SC用户" price="30" time="60">谢谢</sc>
<gift ts="5.000" uid="46" user="礼物用户" giftname="花" giftcount="2"/>
<guard ts="6.000" uid="47" user="舰长用户" level="3" count="1"/>
</i>'''


class CommentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def event(self, ms=1000, text="hello", **kwargs):
        return CommentEvent("Bilibili", "123", "part-1", ms, text, **kwargs)

    def xml(self, value=XML):
        path = self.root / "recording.xml"
        path.write_text(value, encoding="utf-8")
        return path

    def test_native_xml_chat_gift_guard_sc_and_timestamp_units(self):
        stats = {}
        events = list(read_xml(self.xml(), "one", stats))
        self.assertEqual(len(events), 6)
        self.assertEqual(events[0].relative_ms, 1250)
        self.assertEqual(events[0].color, 0xFF0000)
        self.assertEqual(events[0].utc_ts, 1792857600.123)
        self.assertEqual(events[1].placement, "top")
        self.assertEqual(events[2].placement, "bottom")
        self.assertEqual(events[3].text, "[SC ¥30] 谢谢")
        self.assertEqual(events[4].text, "[礼物] 花 ×2")
        self.assertEqual(events[5].kind, "guard")
        self.assertIsNone(stats["anchor_error_ms"])
        self.assertFalse(events[0].message_id)

    def test_dtd_and_entities_are_rejected(self):
        dangerous = '<!DOCTYPE i [<!ENTITY x SYSTEM "file:///cookies.txt">]><i><d p="0,1,25,1,0,0,1,0">&x;</d></i>'
        with self.assertRaises(Exception):
            list(read_xml(self.xml(dangerous), "s", {}))

    def test_completed_elements_survive_truncated_xml(self):
        stats = {}
        events = list(read_xml(self.xml(XML.replace('</i>', '<d p="')), "s", stats))
        self.assertEqual(len(events), 6)
        self.assertTrue(stats["truncated"])

    def test_malformed_events_rejected_without_losing_good_events(self):
        stats = {}
        xml = XML.replace('</i>', '<d p="NaN">bad</d><d p="0,1">bad</d></i>')
        self.assertEqual(len(list(read_xml(self.xml(xml), "s", stats))), 6)
        self.assertEqual(stats["rejected_count"], 2)

    def test_nested_stylesheet_events_are_not_imported(self):
        stats = {}
        self.assertEqual(list(read_xml(self.xml('<i><x><d p="1,1,25,1,0,0,1,0">x</d></x></i>'), 's', stats)), [])
        with self.assertRaises(ValueError):
            list(read_xml(self.xml('<html/>'), 's', {}))

    def test_invalid_header_is_disclosed_as_unknown(self):
        stats = {}
        events = list(read_xml(self.xml(XML.replace('2026-10-25T00:00:00+08:00', 'bad')), 's', stats))
        self.assertIsNone(events[0].recv_ts)
        self.assertNotIn('record_start_time', stats)

    def test_event_validation_and_identity(self):
        first = self.event(user_id='1', utc_ts=10)
        self.assertEqual(first.identity, replace(first, segment_id='another').identity)
        self.assertNotEqual(self.event(1000).identity, self.event(2000).identity)
        for kwargs in [dict(text=''), dict(kind='x'), dict(placement='x'), dict(color=-1),
                       dict(relative_ms=1.5), dict(utc_ts=float('nan')), dict(relative_ms=10**15)]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                replace(first, **kwargs)

    def test_jsonl_dedup_recovery_rebuild_and_partial_line(self):
        with CommentStore(self.root) as store:
            self.assertTrue(store.append(self.event()))
            self.assertFalse(store.append(self.event()))
        with (self.root / 'events.jsonl').open('ab') as file:
            file.write(b'{"truncated":')
        (self.root / 'events.sqlite').unlink()
        with CommentStore(self.root) as store:
            self.assertEqual(len(store.events()), 1)
            self.assertFalse(store.append(self.event()))
            self.assertTrue(store.append(self.event(2000)))
        self.assertEqual(len((self.root / 'events.jsonl').read_text(encoding='utf-8').splitlines()), 2)
        self.assertFalse((self.root / 'events.sqlite-wal').exists())

    def test_anonymization_persists_and_does_not_leak_names(self):
        event = self.event(user_id='private-uid', user_name='private-name')
        with CommentStore(self.root, anonymize=True) as store:
            store.append(event)
            first = store.events()[0]
            self.assertNotEqual(first.user_name, event.user_name)
        with CommentStore(self.root, anonymize=True) as store:
            self.assertFalse(store.append(event))
            self.assertEqual(store.events()[0], first)
            store.append(replace(event, relative_ms=3000))
            self.assertEqual({e.user_name for e in store.events()}, {first.user_name})
        self.assertNotIn('private-', (self.root / 'events.jsonl').read_text(encoding='utf-8'))

    def test_srt_roundtrip_no_overlap_prestarter_and_cjk_wrapping(self):
        events = [self.event(-1), self.event(0, r'{\an8}<b>你好</b>\N注入'), self.event(1), self.event(7000), self.event(11000)]
        path = self.root / 'chat.srt'
        report = export_srt(events, path, duration_ms=10000)
        self.assertEqual(report, {'exported_count': 2, 'dropped_count': 3})
        self.assertTrue(path.read_bytes().startswith(b'\xef\xbb\xbf'))
        result = library('pysubs2').load(str(path), encoding='utf-8-sig')
        self.assertEqual(result[0].start, 0)
        self.assertLessEqual(result[0].end, result[1].start)
        self.assertIn('｛', result[0].text)
        self.assertNotIn('<b>', result[0].text)
        self.assertEqual(len(wrap('中' * 200).splitlines()), 2)
        self.assertNotIn('\x00', plain_text('\x00x'))

    def test_ass_native_library_roundtrip_and_exclusive_bands(self):
        events = [self.event(0), self.event(0, 'red', color=0xFF0000),
                  self.event(0, 'top', placement='top'), self.event(0, 'bottom', placement='bottom'), self.event(-1)]
        path = self.root / 'chat.ass'
        report = export_ass(events, path, width=320, height=180)
        # One lane per band at this small size: the second scrolling item drops.
        self.assertEqual(report['exported_count'], 3)
        result = library('pysubs2').load(str(path))
        self.assertEqual(result.info['PlayResX'], '320')
        self.assertIn(r'\move', result[0].text)
        self.assertIn(r'\pos', result[1].text)
        before = path.read_bytes()
        export_ass(events, path, width=320, height=180)
        self.assertEqual(before, path.read_bytes())
        export_ass([self.event(0, 'red', color=0xFF0000)], path)
        self.assertIn(r'\c&H0000FF&', path.read_text(encoding='utf-8'))

    def test_config_accepts_only_supported_formats_and_boolean_values(self):
        for values in [{'LIVE_DANMAKU_FORMATS':'vtt'}, {'LIVE_DANMAKU_ENABLED':2}, {'LIVE_DANMAKU_ANONYMIZE':-1}]:
            self.assertTrue(validate_config(values)[1])
        config, errors = validate_config({'LIVE_DANMAKU_ENABLED':1, 'LIVE_DANMAKU_FORMATS':'ass', 'LIVE_DANMAKU_ANONYMIZE':1})
        self.assertFalse(errors)
        self.assertEqual(config['LIVE_DANMAKU_FORMATS'], 'ass')

    def test_pipeline_per_media_subtitles_repeatable_and_failure_isolated(self):
        session = LiveSession(self.root, 'Bilibili', 'live_edge', 'url')
        directory, _ = session.part('bililive-recorder', [])
        media = directory / 'video.flv'
        media.write_bytes(b'fixture')
        media.with_suffix('.xml').write_text(XML, encoding='utf-8')
        report = {'files':[{'path':str(media),'duration':10,'streams':[{'codec_type':'video','width':320,'height':180}]}]}
        config = {'LIVE_DANMAKU_ENABLED':1}
        first = process_comments(session, report, config)
        self.assertEqual(first['status'], 'exported')
        before = media.with_suffix('.ass').read_bytes()
        again = process_comments(session, report, config)
        self.assertEqual(before, media.with_suffix('.ass').read_bytes())
        self.assertEqual(again['sources'][0]['duplicate_count'], 6)
        with patch('video_downloader.live.danmaku.service.export_ass', side_effect=RuntimeError('broken')):
            result = process_comments(session, report, config)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(media.read_bytes(), b'fixture')
        self.assertEqual(process_comments(session, report, {})['status'], 'disabled')

    def test_pipeline_reports_unavailable_and_missing_dependency(self):
        session = LiveSession(self.root, 'Twitch', 'live_edge', 'url')
        self.assertEqual(process_comments(session, {'files':[]}, {'LIVE_DANMAKU_ENABLED':1})['status'], 'unavailable')
        with patch('video_downloader.live.danmaku.service.CommentStore', side_effect=RuntimeError()):
            result = process_comments(session, {'files':[]}, {'LIVE_DANMAKU_ENABLED':1})
        self.assertEqual(result['status'], 'failed')
        with patch('video_downloader.live.danmaku.dependencies.importlib.import_module', side_effect=ImportError()):
            with self.assertRaisesRegex(RuntimeError, '依赖缺失'):
                library('pysubs2')


if __name__ == '__main__':
    unittest.main()
