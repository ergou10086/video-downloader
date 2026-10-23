"""任务级 AppState 代理。

``DownloadExecutor`` 原本假设全局只有一个 ``batch_stats`` / ``progress_data``。
每个任务代理出独立的统计与进度；其它只读能力（配置、SSE、线程局部）委托给
基础 AppState，避免复制整个应用状态。
"""

from __future__ import annotations


class TaskAppState:
    def __init__(self, base, task_id: str):
        self._base = base
        self.task_id = task_id
        self.download_thread_context = base.download_thread_context
        self.log_history = base.log_history
        self.batch_stats = {"ok": 0, "fail": 0, "total": 0, "current": 0, "skipped": 0}
        self.progress_data = {
            "percent": 0,
            "status": "等待开始",
            "speed": "",
            "eta": "",
            "stage": "video",
        }

    def config_snapshot(self):
        return self._base.config_snapshot()

    def has_sse_clients(self):
        return self._base.has_sse_clients()

    def publish(self, event):
        event = dict(event or {})
        event["task_id"] = self.task_id
        self._base.publish(event)

    # 归档确认目前共用基础状态；并行任务下如有冲突由任务标签区分来源。
    @property
    def archive_prompt(self):
        return getattr(self._base, "archive_prompt", None)

    @archive_prompt.setter
    def archive_prompt(self, value):
        self._base.archive_prompt = value
