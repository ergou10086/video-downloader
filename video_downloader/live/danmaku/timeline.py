"""Explicit clock provenance; never disguise a wall-clock estimate as exact sync."""
from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime


def epoch(value):
    if value is None or value == "":
        return None
    try:
        if isinstance(value, str) and not value.replace(".", "", 1).isdigit():
            value = datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def project(events, *, segment, anchor_utc, mode, platform, offset_ms=0, duration_ms=None, stats=None, clock_ranges=()):
    stats = stats if stats is not None else {}
    stats.update(anchor_error_ms=None, anchor_source="clock_estimate", pre_start_count=0, unmapped_count=0)
    stats.update(clock_verified_count=0, clock_estimated_count=0)
    for event in events:
        if mode == "catch_up" and platform == "YouTube" and event.time_source == "source_relative":
            # YouTube's replay offset is programme-relative. An unknown DVR head
            # remains an explicit uncertainty in the report, not an invented zero error.
            point = event.relative_ms
            stats["anchor_source"] = "programme_relative_unverified_head"
        else:
            stamp = event.utc_ts if event.utc_ts is not None else event.recv_ts
            if stamp is None or anchor_utc is None:
                stats["unmapped_count"] += 1
                continue
            verified = next((r for r in clock_ranges if r['utc_start'] <= stamp <= r['utc_end']
                             and r['error_ms'] < 2000), None)
            if verified and event.time_source != 'receive':
                point = round((stamp - verified['origin_utc']) * 1000)
                stats['clock_verified_count'] += 1
                stats['anchor_source'] = 'hls_pdt_aac_packet_match'
                if not stats['clock_estimated_count']:
                    stats['anchor_error_ms'] = max(stats.get('anchor_error_ms') or 0, verified['error_ms'])
            else:
                point = round((stamp - anchor_utc) * 1000)
                stats['clock_estimated_count'] += 1
                stats['anchor_error_ms'] = None
        point += offset_ms
        if point < 0:
            stats["pre_start_count"] += 1
        if abs(point) > 31 * 86400000:
            stats["unmapped_count"] += 1
            continue
        yield replace(event, segment_id=segment, relative_ms=point)
