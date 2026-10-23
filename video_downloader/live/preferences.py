"""用户直播偏好的解析。

配置格式：
- ``LIVE_MODE``：全局默认模式（auto/catch_up/live_edge/wait）；
- ``LIVE_PLATFORM_MODES``：JSON 对象，例如 ``{"YouTube":"catch_up","Twitch":"live_edge"}``。
"""

from __future__ import annotations

import json
from typing import Mapping

from .modes import LiveMode


def parse_platform_modes(value) -> dict[str, str]:
    if isinstance(value, Mapping):
        raw = value
    else:
        try:
            raw = json.loads(value or "{}")
        except (TypeError, ValueError):
            return {}
    if not isinstance(raw, Mapping):
        return {}
    allowed = {mode.value for mode in (LiveMode.AUTO, LiveMode.CATCH_UP, LiveMode.LIVE_EDGE)}
    result: dict[str, str] = {}
    for platform, mode in raw.items():
        text = str(mode).strip().lower()
        if str(platform).strip() and text in allowed:
            result[str(platform).strip()] = text
    return result


def resolve_platform_mode(
    platform: str | None,
    global_mode: str | None,
    platform_modes=None,
) -> str:
    """全局显式模式优先；auto 时使用平台级设置；最后回到 auto。"""
    global_text = str(global_mode or "auto").strip().lower()
    if global_text != LiveMode.AUTO.value:
        return global_text
    if not platform:
        return LiveMode.AUTO.value
    return parse_platform_modes(platform_modes).get(platform, LiveMode.AUTO.value)
