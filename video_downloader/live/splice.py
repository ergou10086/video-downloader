"""Join overlapping copies only after video AND audio packet identity agrees.

Wall clocks, titles, VOD durations and HLS sequence numbers from different
playlists are not sufficient evidence. If a source has ads/transcodes or a
different codec, retain both originals and report the unverified join.
"""
from __future__ import annotations

import hashlib
import math
from collections import deque
import subprocess
import tempfile
from pathlib import Path

from .process import hidden_options


def packets(ffprobe, path, *, interval=None, ignore_streams=()):
    ignored = {str(s) for s in ignore_streams}
    command = [str(ffprobe), "-v", "error", "-show_packets", "-show_data_hash", "sha256",
               "-show_entries", "packet=stream_index,codec_type,dts_time,pts_time,duration_time,flags,data_hash", "-of", "compact=p=0"]
    if interval:
        command += ["-read_intervals", interval]
    # Stream a bounded hash index to disk; no packet payload enters memory.
    with tempfile.TemporaryFile() as output:
        result = subprocess.run([*command, str(path)], stdout=output, stderr=subprocess.PIPE,
                                timeout=120, **hidden_options())
        if result.returncode:
            raise ValueError("packet_hash_scan_failed")
        output.seek(0)
        pending = {}
        for line in output:
            values = dict(item.split("=", 1) for item in line.decode().strip().split("|") if "=" in item)
            if (values.get("codec_type") in {"audio", "video"} and "data_hash" in values
                    and values.get("stream_index") not in ignored):
                try:
                    stream = values['stream_index']
                    if values.get('dts_time') in (None, 'N/A'):
                        pending.setdefault(stream, []).append(values)
                        if len(pending[stream]) > 64:
                            raise ValueError('packet_decode_time_unavailable')
                        continue
                    values['dts'] = float(values['dts_time'])
                    if not math.isfinite(values['dts']):
                        raise ValueError('invalid_packet_decode_time')
                    queued = pending.pop(stream, [])
                    # Matroska often omits initial DTS for reordered video.
                    # Retain those payloads and recover decode times backwards
                    # from the first explicit DTS and per-packet durations.
                    stamp = values['dts']
                    for item in reversed(queued):
                        duration = float(item.get('duration_time', 0))
                        if not math.isfinite(duration) or duration <= 0:
                            raise ValueError('packet_decode_time_unavailable')
                        stamp -= duration
                        item.update(dts=stamp, dts_inferred=True)
                    yield from queued
                    yield values
                except ValueError:
                    raise ValueError('packet_decode_time_unavailable') from None
        if pending:
            raise ValueError('packet_decode_time_unavailable')


def overlap_boundary(backfill_packets, tail_packets):
    tail = {kind: [p for p in tail_packets if p["codec_type"] == kind] for kind in ("video", "audio")}
    if not tail["video"] or "K" not in tail["video"][0]["flags"]:
        raise ValueError("tail_does_not_start_at_keyframe")
    buffers = {kind: deque(maxlen=9) for kind in tail}
    matches = {kind: [] for kind in tail}
    cut_windows = {kind: [] for kind in tail}
    for kind in ("video", "audio"):
        if len(tail[kind]) < 8:
            raise ValueError("insufficient_overlap_evidence")
    first = None
    for packet in backfill_packets:
        first = packet["dts"] if first is None else min(first, packet["dts"])
        kind = packet["codec_type"]
        buffer = buffers[kind]
        buffer.append(packet)
        sample = tail[kind][:8]
        window = list(buffer)[-8:]
        if [p["data_hash"] for p in window] == [p["data_hash"] for p in sample]:
            deltas = [b["dts"] - t["dts"] for b, t in zip(window, sample)]
            if max(deltas) - min(deltas) < 0.005:
                matches[kind].append(sum(deltas) / len(deltas))
                cut_windows[kind].append((buffer[0]['dts'] if len(buffer) == 9 else float('-inf'),
                                          window[0]['dts']))
                if len(matches[kind]) > 1:
                    raise ValueError("ambiguous_or_missing_packet_overlap")
    offsets = []
    for kind in ("video", "audio"):
        if len(matches[kind]) != 1:
            raise ValueError("ambiguous_or_missing_packet_overlap")
        offsets.extend(matches[kind])
    if max(offsets) - min(offsets) > 0.05:
        raise ValueError("audio_video_anchor_disagree")
    # Rounding the mean A/V offset can put the cut just after a keyframe,
    # duplicating it. A valid cut must keep each preceding packet and exclude
    # each track's first matched packet, independently.
    lower = max(cut_windows[kind][0][0] for kind in tail)
    boundary = min(cut_windows[kind][0][1] for kind in tail)
    if boundary <= lower:
        raise ValueError('audio_video_cut_window_disagree')
    if first is None or boundary <= first:
        raise ValueError("no_backfill_prefix")
    return boundary


def reconcile(session, checker, backfill, report):
    result = {"status": "unverified", "deduplication": "video_and_audio_sha256", "originals_retained": True}
    try:
        if len(backfill) != 1 or len(report["files"]) != 1:
            raise ValueError("multiple_parts_require_separate_playback")
        before, after = backfill[0], report["files"][0]
        inspected = checker.inspect(before)
        if not inspected["valid"] or not after["valid"]:
            raise ValueError("source_integrity_failed")
        signatures = lambda file: [{k: s.get(k) for k in ("codec_type", "codec_name", "width", "height", "sample_rate", "channels",
                                                        "time_base", "extradata_hash")}
                                   for s in file["streams"] if not s.get("attached_pic")]
        if signatures(inspected) != signatures(after):
            raise ValueError("incompatible_streams")
        ignored_before = [s["index"] for s in inspected["streams"] if s.get("attached_pic")]
        ignored_after = [s["index"] for s in after["streams"] if s.get("attached_pic")]
        tail_packets = list(packets(checker.ffprobe, after["path"], interval="%+5", ignore_streams=ignored_after))
        # Streaming eight-packet windows keep memory bounded for long VODs.
        boundary = overlap_boundary(packets(checker.ffprobe, before, ignore_streams=ignored_before), tail_packets)
        listing, joined = session.root / "catchup.ffconcat", session.root / "catchup.mkv"
        def quoted(path):
            return Path(path).resolve().as_posix().replace("'", "'\\''")
        listing.write_text("ffconcat version 1.0\nfile '" + quoted(before) + "'\noutpoint " +
                           f"{boundary:.6f}\nfile '" + quoted(after["path"]) + "'\n", encoding="utf-8")
        try:
            run = subprocess.run([checker.ffmpeg, "-v", "error", "-nostdin", "-y", "-f", "concat", "-auto_convert", "0", "-safe", "0",
                                  "-i", str(listing), "-map", "0:V:0", "-map", "0:a:0", "-c", "copy", str(joined)],
                                 capture_output=True, timeout=120, **hidden_options())
            checked = checker.inspect(joined)
            if run.returncode or not checked["valid"]:
                raise ValueError("joined_integrity_failed")
            # Prove no extra repeated packets were introduced by the muxer.
            # A concat outpoint is DTS based; frame count is the union, not sum.
            def fingerprint(sources):
                digests = {k: hashlib.sha256() for k in ("audio", "video")}
                counts = {k: 0 for k in digests}
                for source, cutoff, ignored in sources:
                    for packet in packets(checker.ffprobe, source, ignore_streams=ignored):
                        if cutoff is None or packet["dts"] < cutoff:
                            kind = packet["codec_type"]
                            digests[kind].update(packet["data_hash"].encode())
                            counts[kind] += 1
                return counts, {k: d.hexdigest() for k, d in digests.items()}
            expected = fingerprint([(before, boundary, ignored_before), (after["path"], None, ignored_after)])
            actual = fingerprint([(joined, None, ())])
            if actual != expected:
                raise ValueError("joined_packet_fingerprint_mismatch")
            report["joined"] = checked
            result.update(status="joined", cut_dts=boundary, duplicate_packets_in_output=0,
                          packet_counts=actual[0], joined=str(joined))
        finally:
            listing.unlink(missing_ok=True)
            if result["status"] != "joined":
                joined.unlink(missing_ok=True)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        result["reason"] = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
    report["catch_up_join"] = result
    return result
