"""Shared tasks test factories and doubles."""
import threading
import time
from video_downloader.state.app_state import AppState
from video_downloader.tasks import TaskManager


class FakeExecutor:
    def __init__(self, task, callbacks, on_finished, mode="success"):
        self.task = task
        self.callbacks = callbacks
        self.on_finished = on_finished
        self.mode = mode
        self.stopped = threading.Event()

    def start_download(self, url, **kwargs):
        if self.mode == "success":
            self.callbacks.update_progress(0.5, "下载中", "1.2 MB/s", "00:10", "video")
            self.callbacks.add_history(url, "title", "YouTube", "success", "out.mp4")
        elif self.mode == "fail":
            self.callbacks.add_history(url, "", "YouTube", "fail")
        self.on_finished(object())
        return {"ok": True}

    def batch_download(self, urls, **kwargs):
        return self.start_download(urls[0], **kwargs)

    def stop_download(self):
        self.stopped.set()
        return {"ok": True}


def make_manager(mode="success", max_parallel=2, order="none"):
    state = AppState()
    state.replace_config({"TASK_MAX_PARALLEL": max_parallel, "TASK_ORDER": order})
    events = []
    tasks = {}

    def factory(task, task_state, manager, callbacks, on_finished):
        executor = FakeExecutor(task, callbacks, on_finished, mode=mode)
        tasks[task.id] = executor
        return executor

    manager = TaskManager(
        base_app_state=state,
        executor_factory=factory,
        max_parallel_getter=lambda: state.config_snapshot()["TASK_MAX_PARALLEL"],
        order_getter=lambda: state.config_snapshot()["TASK_ORDER"],
        publish=lambda event: events.append(event),
    )
    return manager, state, events, tasks


def wait_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False
