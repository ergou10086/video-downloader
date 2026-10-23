"""任务级 AppState 代理。

``DownloadExecutor`` 原本假设全局只有一个 ``batch_stats`` / ``progress_data``。
每条链接使用独立的统计、进度和归档确认；下载配置固定为提交时的快照。
SSE 客户端和线程局部能力委托给基础 AppState。
"""

from __future__ import annotations


class TaskAppState:
    def __init__(self, base, task_id: str, config=None, publish=None):
        self._base = base
        self.task_id = task_id
        self._config = dict(config if config is not None else base.config_snapshot())
        self._publish = publish or self._base.publish
        self.archive_prompt = None
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
        return dict(self._config)

    def has_sse_clients(self):
        return self._base.has_sse_clients()

    def publish(self, event):
        event = dict(event or {})
        event["task_id"] = self.task_id
        self._publish(event)
