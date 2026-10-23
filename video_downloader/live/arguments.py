"""直播参数策略。

命令构造不直接写 ``--live-from-start``；它消费一个策略返回的参数元组。
以后新增引擎（BililiveRecorder/Streamlink）时实现自己的策略/适配器，
不需要改 ``build_ytdlp_cmd`` 的平台分支。
"""

from __future__ import annotations

from typing import Protocol

from .modes import LiveDecision, LiveMode, LiveModeError, decide_live


class LiveArgumentStrategy(Protocol):
    """把直播决策翻译成某个录制器的命令行参数。"""

    def arguments(self, decision: LiveDecision) -> tuple[str, ...]:
        ...


class YtDlpLiveArgumentStrategy:
    """yt-dlp 的直播参数策略。"""

    def arguments(self, decision: LiveDecision) -> tuple[str, ...]:
        if not decision.is_live or decision.mode is None:
            return ()
        if decision.mode is LiveMode.CATCH_UP:
            return ("--live-from-start",)
        if decision.mode is LiveMode.LIVE_EDGE:
            # 显式声明从当前时刻，避免未来 yt-dlp 默认值变化导致行为漂移。
            return ("--no-live-from-start",)
        raise LiveModeError(f"yt-dlp 不支持直播模式: {decision.mode.value}")


DEFAULT_YTDLP_LIVE_ARGUMENTS = YtDlpLiveArgumentStrategy()


def build_live_arguments(
    platform: str | None,
    requested_mode: "LiveMode | str | None",
    is_live: bool,
    strategy: LiveArgumentStrategy = DEFAULT_YTDLP_LIVE_ARGUMENTS,
) -> tuple[str, ...]:
    """解析模式并返回参数；不支持的模式抛 LiveModeError。"""
    if not is_live:
        return ()
    decision = decide_live(platform, requested_mode, is_live=True)
    return strategy.arguments(decision)
