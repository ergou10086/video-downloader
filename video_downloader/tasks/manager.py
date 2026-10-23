"""任务队列与并行调度。

每个 RUNNING 任务拥有独立的 DownloadExecutor / DownloadManager；
TaskManager 只负责排队、并发上限、排序、取消和快照广播。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from video_downloader.core.platform import clean_url, detect_platform
from video_downloader.live import is_live_url
from video_downloader.services.download_manager import DownloadManager

from .context import TaskAppState
from .models import Task, TaskStatus


@dataclass
class TaskCallbacks:
    log: Callable
    update_progress: Callable
    add_history: Callable
    broadcast_download_state: Callable
    emit_event: Callable
    cancel_idle_timer: Callable
    start_idle_timer: Callable


class TaskManager:
    def __init__(
        self,
        *,
        base_app_state,
        executor_factory: Callable,
        max_parallel_getter: Callable[[], int],
        order_getter: Callable[[], str],
        publish: Callable[[dict], None] | None = None,
        cancel_idle_timer: Callable[[], None] | None = None,
        start_idle_timer: Callable[[], None] | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self._base_app_state = base_app_state
        self._executor_factory = executor_factory
        self._max_parallel_getter = max_parallel_getter
        self._order_getter = order_getter
        self._publish = publish or (lambda event: None)
        self._cancel_idle = cancel_idle_timer or (lambda: None)
        self._start_idle = start_idle_timer or (lambda: None)
        self._clock = clock
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._tasks: dict[str, Task] = {}
        self._runtimes: dict[str, dict] = {}
        self._order_seq = 0
        self._start_thread()

    # ---- 生命周期 ----
    def _start_thread(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stopping.clear()
        self._thread = threading.Thread(target=self._loop, name="task-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self._wake.set()
        self.cancel_all()
        if self._thread:
            self._thread.join(timeout=3)

    def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                self._dispatch()
            except Exception:
                pass
            self._wake.wait(0.5)
            self._wake.clear()

    # ---- 提交/查询 ----
    def submit(self, urls, *, kind: str | None = None, live_mode: str | None = None,
               bili_parts: str | None = None, bili_parts_map: dict | None = None,
               tc_password: str | None = None,
               custom_args: str | None = None) -> dict:
        cleaned = [url for raw in (urls or []) if (url := clean_url(raw))]
        if not cleaned:
            return {"error": "没有有效的链接"}
        if str(live_mode or "").lower() == "wait":
            return {"error": "蹲开播任务请使用等待开播面板，不能加入任务队列"}
        if kind is None:
            kind = "live" if any(is_live_url(url, detect_platform(url)) for url in cleaned) else "download"
        with self._lock:
            self._order_seq += 1
            task = Task(
                urls=cleaned,
                kind=kind,
                live_mode=live_mode,
                bili_parts=bili_parts,
                bili_parts_map=bili_parts_map,
                tc_password=tc_password,
                custom_args=custom_args,
                priority=2 if kind == "live" else 1,
                order_index=self._order_seq,
                message="排队中",
            )
            self._tasks[task.id] = task
            self._broadcast()
        self._wake.set()
        return {"ok": True, "task": task.to_dict()}

    def list_tasks(self) -> list[dict]:
        with self._lock:
            tasks = sorted(self._tasks.values(), key=lambda item: item.created_at)
            return [task.to_dict() for task in tasks]

    def has_active(self) -> bool:
        with self._lock:
            return any(
                task.status in {TaskStatus.QUEUED, TaskStatus.RUNNING}
                for task in self._tasks.values()
            )

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for task in self._tasks.values()
                       if task.status in {TaskStatus.QUEUED, TaskStatus.RUNNING})

    def clear_finished(self) -> dict:
        with self._lock:
            removable = [task_id for task_id, task in self._tasks.items()
                         if task.is_terminal and task_id not in self._runtimes]
            for task_id in removable:
                self._tasks.pop(task_id, None)
            self._broadcast()
        return {"ok": True, "removed": len(removable)}

    def cancel(self, task_id: str) -> dict:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return {"error": "任务不存在"}
            if task.is_terminal:
                return {"ok": True, "task": task.to_dict()}
            task.cancel_requested = True
            task.message = "正在停止"
            runtime = self._runtimes.get(task_id)
            if task.status is TaskStatus.QUEUED:
                task.status = TaskStatus.CANCELLED
                task.finished_at = self._clock()
                task.progress = 0
                self._broadcast()
                return {"ok": True, "task": task.to_dict()}
            self._broadcast()
        if runtime:
            try:
                runtime["executor"].stop_download()
            except Exception:
                pass
        return {"ok": True, "task": task.to_dict()}

    def cancel_all(self) -> dict:
        with self._lock:
            ids = [task_id for task_id, task in self._tasks.items() if not task.is_terminal]
        for task_id in ids:
            self.cancel(task_id)
        return {"ok": True, "cancelled": len(ids)}

    # ---- 调度 ----
    def _max_parallel(self) -> int:
        try:
            value = int(self._max_parallel_getter())
        except Exception:
            value = 1
        return max(1, min(8, value))

    def _dispatch(self) -> None:
        with self._lock:
            running = sum(1 for task in self._tasks.values() if task.status is TaskStatus.RUNNING)
            free = self._max_parallel() - running
            if free <= 0:
                return
            queued = [task for task in self._tasks.values() if task.status is TaskStatus.QUEUED]
            order = str(self._order_getter() or "none").lower()
            if order == "live_first":
                queued.sort(key=lambda task: (-task.priority, task.order_index))
            elif order == "download_first":
                queued.sort(key=lambda task: (task.priority, task.order_index))
            else:
                queued.sort(key=lambda task: task.order_index)
            selected = queued[:free]
            for task in selected:
                task.status = TaskStatus.RUNNING
                task.started_at = self._clock()
                task.message = "开始下载"
            self._broadcast()
        for task in selected:
            self._start_task(task)

    def _start_task(self, task: Task) -> None:
        with self._lock:
            current = self._tasks.get(task.id)
            if not current or current.status is not TaskStatus.RUNNING or current.cancel_requested:
                return
        state = TaskAppState(self._base_app_state, task.id)
        download_manager = DownloadManager()
        callbacks = TaskCallbacks(
            log=lambda msg, level="info": self._on_log(task.id, msg, level),
            update_progress=lambda percent, status=None, speed="", eta="", stage="video": self._on_progress(
                task.id, percent, status, speed, eta, stage),
            add_history=lambda *args, **kwargs: self._on_history(task.id, *args, **kwargs),
            broadcast_download_state=lambda: self._broadcast(),
            emit_event=lambda event_type, data=None: self._on_event(task.id, event_type, data),
            cancel_idle_timer=self._cancel_idle,
            start_idle_timer=self._start_idle,
        )
        try:
            executor = self._executor_factory(
                task, state, download_manager, callbacks,
                lambda _handle: self._complete(task.id),
            )
        except Exception as exc:
            self._fail(task.id, f"任务执行器创建失败: {exc}")
            return
        runtime = {"executor": executor, "manager": download_manager, "thread": None}
        with self._lock:
            self._runtimes[task.id] = runtime
        thread = threading.Thread(
            target=self._run_task, args=(task, executor), name=f"task-{task.id[:8]}", daemon=True
        )
        runtime["thread"] = thread
        thread.start()

    # 由容器注入更合适；默认不操作空闲计时器。

    def _run_task(self, task: Task, executor) -> None:
        try:
            if len(task.urls) == 1:
                result = executor.start_download(
                    task.urls[0],
                    bili_parts=task.bili_parts,
                    tc_password=task.tc_password,
                    custom_args=task.custom_args,
                    live_mode=task.live_mode,
                )
            else:
                result = executor.batch_download(
                    task.urls,
                    bili_parts_map=task.bili_parts_map,
                    custom_args=task.custom_args,
                    live_mode=task.live_mode,
                )
            if isinstance(result, dict) and result.get("error"):
                self._fail(task.id, str(result["error"]))
        except Exception as exc:
            self._fail(task.id, f"{type(exc).__name__}: {exc}")

    def _complete(self, task_id: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            if task.cancel_requested:
                task.status = TaskStatus.CANCELLED
                task.message = "已取消"
            elif task.history:
                successes = [item for item in task.history if item.get("status") == "success"]
                failures = [item for item in task.history if item.get("status") in {"fail", "timeout"}]
                if successes and not failures:
                    task.status = TaskStatus.COMPLETED
                    task.progress = 100.0
                    task.message = "已完成"
                elif successes:
                    task.status = TaskStatus.COMPLETED
                    task.message = f"完成，但有 {len(failures)} 项失败"
                    task.error = f"{len(failures)} 项失败"
                else:
                    task.status = TaskStatus.FAILED
                    task.message = "失败"
            elif task.error:
                task.status = TaskStatus.FAILED
            else:
                task.status = TaskStatus.COMPLETED
                task.progress = 100.0
                task.message = "已完成"
            task.finished_at = self._clock()
            self._runtimes.pop(task_id, None)
            self._broadcast()
        self._wake.set()

    def _fail(self, task_id: str, message: str) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            if task.cancel_requested:
                task.status = TaskStatus.CANCELLED
                task.message = "已取消"
            else:
                task.status = TaskStatus.FAILED
                task.error = message
                task.message = "失败"
            task.finished_at = self._clock()
            self._runtimes.pop(task_id, None)
            self._broadcast()
        self._wake.set()

    # ---- 回调 ----
    def _on_progress(self, task_id, percent, status, speed, eta, stage):
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            if percent is not None:
                if percent < 0:
                    task.indeterminate = True
                    task.message = status or task.message
                else:
                    task.indeterminate = False
                    task.progress = max(0.0, min(100.0, float(percent)))
            if status:
                task.message = status
            task.speed = speed or ""
            task.eta = eta or ""
            task.stage = stage or "video"
            self._broadcast()

    def _on_log(self, task_id, message, level="info"):
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.logs.append({
                    "time": time.strftime("%H:%M:%S"),
                    "msg": str(message),
                    "level": level,
                })
                if len(task.logs) > 120:
                    task.logs = task.logs[-120:]
                if level == "error":
                    task.error = str(message)
            self._broadcast()

    def _on_history(self, task_id, url, title, platform, status, output_path=""):
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.history.append({
                "url": url, "title": title, "platform": platform,
                "status": status, "output": output_path,
            })
            if len(task.history) > 50:
                task.history = task.history[-50:]
            if title:
                task.title = title
            self._broadcast()

    def _on_event(self, task_id, event_type, data=None):
        event = {"type": event_type, "task_id": task_id}
        if data is not None:
            event["data"] = data
        self._publish(event)

    def _broadcast(self) -> None:
        # 调用方通常已持锁；这里只构造快照，避免重入。
        tasks = [task.to_dict() for task in sorted(self._tasks.values(), key=lambda item: item.created_at)]
        self._publish({"type": "task_snapshot", "data": {"tasks": tasks}})
