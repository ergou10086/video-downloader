"""HLS PDT clock evidence, tied to recorded AAC packets rather than file growth.

RFC 8216 maps PROGRAM-DATE-TIME to the first sample of a segment. Sampling is
bounded and independent of recording. Signed URLs/headers never enter reports.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from .danmaku.timeline import epoch
from .danmaku.transport import Transport
from .process import hidden_options
from .session import atomic_json


def attributes(value):
    return {m[1]: m[2] if m[2] is not None else m[3] for m in
            re.finditer(r'([A-Z0-9-]+)=(?:"([^"]*)"|([^,]*))', value)}


def playlist(text, url):
    segments, variants = [], []
    stamp, duration, sequence, discontinuity = None, None, 0, 0
    init, variant, encrypted, unsupported = None, None, False, False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('#EXT-X-STREAM-INF:'):
            variant = attributes(line.split(':', 1)[1])
        elif line.startswith('#EXT-X-MEDIA-SEQUENCE:'):
            sequence = int(line.split(':', 1)[1])
        elif line.startswith('#EXT-X-DISCONTINUITY-SEQUENCE:'):
            discontinuity = int(line.split(':', 1)[1])
        elif line == '#EXT-X-DISCONTINUITY':
            discontinuity += 1
            stamp = None  # Never extrapolate PDT through a timestamp reset.
        elif line.startswith('#EXT-X-PROGRAM-DATE-TIME:'):
            stamp = epoch(line.split(':', 1)[1])
        elif line.startswith('#EXT-X-MAP:'):
            values = attributes(line.split(':', 1)[1])
            init = urljoin(url, values['URI'])
            unsupported = 'BYTERANGE' in values
        elif line.startswith('#EXT-X-KEY:'):
            encrypted = attributes(line.split(':', 1)[1]).get('METHOD') != 'NONE'
        elif line.startswith('#EXT-X-BYTERANGE:'):
            unsupported = True
        elif line.startswith('#EXTINF:'):
            duration = float(line.split(':', 1)[1].split(',', 1)[0])
            if not math.isfinite(duration) or not 0 < duration <= 3600:
                raise ValueError('invalid_hls_segment_duration')
        elif line and not line.startswith('#'):
            if variant is not None:
                variants.append(dict(variant, url=urljoin(url, line)))
                variant = None
            elif duration is not None:
                segments.append({'url':urljoin(url, line), 'utc':stamp, 'duration':duration,
                                 'sequence':sequence, 'discontinuity':discontinuity,
                                 'init':init, 'supported':not (encrypted or unsupported)})
                if stamp is not None:
                    stamp += duration
                sequence += 1
                duration = None
    return variants, segments


def audio_packets(ffprobe, path, interval=None):
    command = [str(ffprobe), '-v', 'error', '-select_streams', 'a:0', '-show_packets',
               '-show_data', '-show_format', '-show_streams', '-show_entries',
               'packet=pts_time,duration_time,data:format=start_time:stream=codec_name,sample_rate', '-of', 'json']
    if interval:
        command += ['-read_intervals', interval]
    result = subprocess.run([*command, str(path)], capture_output=True, timeout=10, **hidden_options())
    if result.returncode or len(result.stdout) > 24 * 1024 * 1024:
        raise ValueError('clock_packet_probe_failed')
    data = json.loads(result.stdout)
    if not data.get('streams') or data['streams'][0].get('codec_name') != 'aac':
        raise ValueError('clock_audio_codec_unsupported')
    packets = []
    for packet in data.get('packets', []):
        raw = bytearray()
        for line in packet.get('data', '').splitlines():
            if re.match(r'^[0-9a-fA-F]{8}: ', line):
                raw.extend(bytes.fromhex(line[10:49].replace(' ', '')))
        # TS carries ADTS; MP4/Matroska carry the same AAC payload without it.
        if len(raw) > 7 and raw[0] == 255 and raw[1] & 0xF6 == 0xF0:
            raw = raw[7 if raw[1] & 1 else 9:]
        if raw and 'pts_time' in packet:
            pts = float(packet['pts_time'])
            if math.isfinite(pts):
                packets.append({'pts':pts, 'hash':hashlib.sha256(raw).hexdigest()})
    origin = float(data.get('format', {}).get('start_time', 0))
    return packets, origin


def match(sample, recorded, origin):
    reference = sample['packets']
    # A sequence of eight payloads rejects accidental/repeated silent frames.
    candidates = []
    for begin in range(0, max(0, len(reference) - 7), 8):
        window = reference[begin:begin + 8]
        hashes = [p['hash'] for p in window]
        if len(set(hashes)) < 4:
            continue
        hits = [i for i in range(len(recorded) - 7)
                if [p['hash'] for p in recorded[i:i + 8]] == hashes]
        if len(hits) != 1:
            continue
        points = [sample['utc'] + src['pts'] - sample['source_origin'] - (dst['pts'] - origin)
                  for src, dst in zip(window, recorded[hits[0]:hits[0] + 8])]
        if max(points) - min(points) < 0.05:
            candidates.append(statistics.median(points))
    if not candidates or max(candidates) - min(candidates) > 0.1:
        return None
    # The budget includes audio/video first-sample skew and container rounding;
    # it describes PDT-to-media mapping, not the platform's capture clock itself.
    return {'origin_utc':statistics.median(candidates), 'source_utc':sample['utc'], 'duration':sample['duration'],
            'discontinuity':sample['discontinuity'], 'sequence':sample['sequence'],
            'error_ms':500 + round((max(candidates) - min(candidates)) * 1000)}


class MediaClock:
    def __init__(self, directory, command, ffprobe):
        self.directory, self.command, self.ffprobe = Path(directory), list(command), ffprobe
        self.stop_event, self.thread = threading.Event(), None
        self.samples, self.errors = [], []
        self.total_bytes = 0
        self.transport = None

    def start(self, metadata):
        if self.thread:
            return
        if callable(metadata):
            self.thread = threading.Thread(target=self._resolve, args=(metadata,), name='live-clock-source', daemon=True)
            self.thread.start()
            return
        sources = metadata.get('requested_formats') or [metadata]
        selected = next((f for f in sources if str(f.get('protocol', '')).startswith('m3u8')
                         or '.m3u8' in str(f.get('url', '')).split('?')[0]), None)
        if not selected or not selected.get('url'):
            return
        self.thread = threading.Thread(target=self._observe, args=(dict(selected),), name='live-clock', daemon=True)
        self.thread.start()

    def _resolve(self, resolver):
        try:
            self._observe(resolver())
        except Exception as exc:
            self.errors.append(type(exc).__name__)

    def _observe(self, selected):
        for attempt in range(3):
            before = len(self.errors)
            self._observe_once(selected)
            if len(self.errors) == before or self.stop_event.wait(2 ** attempt):
                break

    def _observe_once(self, selected):
        transport = None
        try:
            transport = self.transport = Transport(self.command)
            # Keep routing/auth context in memory only. Cookies remain scoped by
            # httpx. Extractor's signed URLs already authorize media requests.
            supplied = selected.get('http_headers') or {}
            headers = {k:v for k,v in supplied.items() if k.lower() in {'user-agent', 'referer', 'origin'}}
            private_headers = {k:v for k,v in supplied.items() if k.lower() in {'cookie', 'authorization'}}
            source_host = urlsplit(selected['url']).netloc
            def fetch(address):
                scoped = dict(headers)
                if urlsplit(address).netloc == source_host:
                    scoped.update(private_headers)
                return transport.response(address, headers=scoped)
            url, last_sample, seen = selected['url'], 0, set()
            masters = set()
            while not self.stop_event.is_set():
                variants, segments = playlist(fetch(url).decode('utf-8-sig'), url)
                if variants:
                    if url in masters or len(masters) >= 8:
                        raise ValueError('cyclic_hls_master')
                    masters.add(url)
                    ceiling = selected.get('height') or 100000
                    eligible = [v for v in variants if int(v.get('RESOLUTION', '0x0').split('x')[-1]) <= ceiling]
                    url = max(eligible or variants, key=lambda v:int(v.get('BANDWIDTH', 0)))['url']
                    continue
                choices = [s for s in segments if s['utc'] is not None and s['supported']
                           and (s['discontinuity'], s['sequence']) not in seen]
                if choices and (not self.samples or time.monotonic() - last_sample >= 60):
                    chosen = choices[-min(3, len(choices))]
                    seen.add((chosen['discontinuity'], chosen['sequence']))
                    if len(self.samples) >= 64 or self.total_bytes >= 64 * 1024 * 1024:
                        self.errors.append('clock_sampling_budget_exhausted')
                        break
                    body = fetch(chosen['url'])
                    if chosen['init']:
                        body = fetch(chosen['init']) + body
                    self.total_bytes += len(body)
                    with tempfile.NamedTemporaryFile(suffix='.clock-sample', dir=self.directory, delete=False) as temporary:
                        sample_path = Path(temporary.name)
                        temporary.write(body)
                    try:
                        packets, origin = audio_packets(self.ffprobe, sample_path, '%+#96')
                        if self.stop_event.is_set():
                            break
                        self.samples.append({k:chosen[k] for k in ('utc', 'duration', 'sequence', 'discontinuity')} |
                                            {'packets':packets[:64], 'source_origin':origin, 'observed_at':time.time()})
                        atomic_json(self.directory / 'clock-samples.json', {'samples':self.samples})
                    finally:
                        sample_path.unlink(missing_ok=True)
                    last_sample = time.monotonic()
                if self.stop_event.wait(2):
                    break
        except Exception as exc:
            self.errors.append(type(exc).__name__)
        finally:
            if transport:
                transport.close()
            self.transport = None

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=12)
            if self.thread.is_alive():
                if self.transport:
                    self.transport.close()
                self.thread.join(timeout=12)
            if self.thread.is_alive():
                self.errors.append('clock_observer_stop_timeout')

    def annotate(self, report, part):
        for file in report['files']:
            if not Path(file['path']).is_relative_to(self.directory):
                continue
            anchors = []
            for sample in tuple(self.samples):
                rough = max(0, sample['observed_at'] - part.get('media_started_at', part['started_at']))
                try:
                    packets, origin = audio_packets(self.ffprobe, file['path'], f'{max(0, rough - 60):.3f}%+100')
                    anchor = match(sample, packets, origin)
                    if anchor:
                        anchors.append(anchor)
                except (ValueError, OSError, subprocess.TimeoutExpired):
                    continue
            ranges = []
            for anchor in sorted(anchors, key=lambda a:a['source_utc']):
                if (ranges and anchor['discontinuity'] == ranges[-1]['discontinuity']
                        and abs(anchor['origin_utc'] - ranges[-1]['origin_utc']) < 0.5):
                    ranges[-1]['utc_end'] = anchor['source_utc'] + anchor['duration']
                    ranges[-1]['error_ms'] = max(ranges[-1]['error_ms'], anchor['error_ms'])
                    ranges[-1]['anchors'] += 1
                else:
                    ranges.append({'utc_start':anchor['source_utc'], 'utc_end':anchor['source_utc'] + anchor['duration'],
                                   'origin_utc':anchor['origin_utc'], 'error_ms':anchor['error_ms'],
                                   'discontinuity':anchor['discontinuity'], 'anchors':1})
            file['comment_clock'] = {'source':'hls_pdt_aac_packet_match', 'ranges':ranges,
                                     'sample_count':len(self.samples), 'matched_count':len(anchors),
                                     'unverified_reason':('ambiguous_or_missing_aac_packets' if self.samples
                                                          else 'source_clock_unavailable') if not anchors else None,
                                     'errors':list(dict.fromkeys(self.errors)), 'scope':'media_clock_mapping'}
