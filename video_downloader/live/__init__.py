"""直播录制的公共 API。

对外只暴露领域模型、能力门面和参数策略；内部实现可独立演进。
"""

from .arguments import (
    DEFAULT_YTDLP_LIVE_ARGUMENTS,
    LiveArgumentStrategy,
    YtDlpLiveArgumentStrategy,
    build_live_arguments,
)
from .classifier import is_live_url
from .modes import (
    CAPABILITIES,
    LiveDecision,
    LiveMode,
    LiveModeError,
    PlatformCapability,
    Support,
    auto_mode_for,
    capability_for,
    decide_live,
    resolve_mode,
)
from .probe import LiveProbe, LiveStatus, ProbeService
from .service import LIVE_SERVICE, LiveService
from .urls import LiveTarget, TargetKind, classify_target, expand_short_url
from .wait import LiveWatchService, WatchJob, WatchJobStore, WatchStatus

__all__ = [
    "CAPABILITIES",
    "DEFAULT_YTDLP_LIVE_ARGUMENTS",
    "LIVE_SERVICE",
    "LiveArgumentStrategy",
    "LiveDecision",
    "LiveMode",
    "LiveModeError",
    "LiveProbe",
    "LiveService",
    "LiveStatus",
    "LiveTarget",
    "LiveWatchService",
    "PlatformCapability",
    "ProbeService",
    "Support",
    "TargetKind",
    "WatchJob",
    "WatchJobStore",
    "WatchStatus",
    "YtDlpLiveArgumentStrategy",
    "auto_mode_for",
    "build_live_arguments",
    "capability_for",
    "classify_target",
    "decide_live",
    "expand_short_url",
    "is_live_url",
    "resolve_mode",
]
