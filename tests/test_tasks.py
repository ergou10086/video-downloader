import threading
import time
import unittest

from video_downloader.state.app_state import AppState
from video_downloader.tasks import TaskManager, TaskStatus


class FakeExecutor:
    def __init__(self, task, callbacks, on_finished, mode="success"):
        self.task = task
        self.callbacks = callbacks
        self.on_finished = on_finished
        self.mode = mode
        self.stopped = threading.Event()

    def start_download(self, url, **kwargs):
        if self.mode == "success":
            self.callbacks.update_progress(50, "下载中", "1.2 MB/s", "00:10", "video")
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


class TaskManagerTests(unittest.TestCase):
    def test_task_completes_and_publishes_snapshot(self):
        manager, state, events, _ = make_manager()
        try:
            result = manager.submit(["https://example.com/video"])
            self.assertTrue(result["ok"])
            task_id = result["task"]["id"]
            self.assertTrue(wait_until(lambda: manager.list_tasks()[0]["status"] == "completed"))
            self.assertFalse(manager.has_active())
            self.assertTrue(any(event["type"] == "task_snapshot" for event in events))
            task = manager.list_tasks()[0]
            self.assertEqual(task["urls"], ["https://example.com/video"])
            self.assertEqual(task["progress"], 100)
            self.assertEqual(task["history"][0]["status"], "success")
        finally:
            manager.stop()

    def test_failed_task(self):
        manager, state, events, _ = make_manager(mode="fail")
        try:
            result = manager.submit(["https://example.com/video"])
            self.assertTrue(wait_until(lambda: manager.list_tasks()[0]["status"] == "failed"))
            self.assertIn("失败", manager.list_tasks()[0]["message"])
            self.assertFalse(manager.has_active())
        finally:
            manager.stop()

    def test_queue_waits_when_parallel_is_one(self):
        manager, state, events, tasks = make_manager(max_parallel=1)
        gate = threading.Event()

        class BlockingExecutor(FakeExecutor):
            def start_download(self, url, **kwargs):
                gate.wait(2)
                return super().start_download(url, **kwargs)

        def factory(task, task_state, dm, callbacks, on_finished):
            executor = BlockingExecutor(task, callbacks, on_finished)
            tasks[task.id] = executor
            return executor

        manager._executor_factory = factory
        try:
            first = manager.submit(["https://example.com/1"])["task"]["id"]
            second = manager.submit(["https://example.com/2"])["task"]["id"]
            self.assertTrue(wait_until(lambda: len([t for t in manager.list_tasks() if t["status"] == "running"]) == 1))
            queued = [t for t in manager.list_tasks() if t["status"] == "queued"]
            self.assertEqual(len(queued), 1)
            gate.set()
            self.assertTrue(wait_until(lambda: all(t["status"] == "completed" for t in manager.list_tasks())))
        finally:
            gate.set()
            manager.stop()

    def test_cancel_queued_task(self):
        manager, state, events, tasks = make_manager(max_parallel=1)
        gate = threading.Event()

        class BlockingExecutor(FakeExecutor):
            def start_download(self, url, **kwargs):
                gate.wait(2)
                return super().start_download(url, **kwargs)

        manager._executor_factory = lambda task, ts, dm, cb, done: BlockingExecutor(task, cb, done)
        try:
            first = manager.submit(["https://example.com/1"])["task"]["id"]
            second = manager.submit(["https://example.com/2"])["task"]["id"]
            self.assertTrue(wait_until(lambda: manager.list_tasks()[0]["status"] == "running"))
            result = manager.cancel(second)
            self.assertEqual(result["task"]["status"], "cancelled")
            gate.set()
            self.assertTrue(wait_until(lambda: manager.list_tasks()[0]["status"] == "completed"))
        finally:
            gate.set()
            manager.stop()

    def test_max_parallel_and_priority(self):
        manager, state, events, tasks = make_manager(max_parallel=2, order="live_first")
        gate = threading.Event()
        started = []

        class BlockingExecutor(FakeExecutor):
            def start_download(self, url, **kwargs):
                started.append((self.task.kind, url))
                gate.wait(2)
                return super().start_download(url, **kwargs)

        manager._executor_factory = lambda task, ts, dm, cb, done: BlockingExecutor(task, cb, done)
        try:
            manager.submit(["https://example.com/d1"], kind="download")
            manager.submit(["https://example.com/l1"], kind="live")
            self.assertTrue(wait_until(lambda: len(started) == 2))
            # 两个都启动；live_first 只影响排队顺序，不阻止并行。
            self.assertEqual(len(started), 2)
            gate.set()
            self.assertTrue(wait_until(lambda: all(t["status"] == "completed" for t in manager.list_tasks())))
        finally:
            gate.set()
            manager.stop()

    def test_task_app_state_is_isolated(self):
        # TaskAppState 的 stats/progress 不污染基础 AppState。
        manager, state, events, _ = make_manager()
        try:
            manager.submit(["https://example.com/1"])
            self.assertTrue(wait_until(lambda: not manager.has_active()))
            self.assertEqual(state.batch_stats["ok"], 0)
        finally:
            manager.stop()


if __name__ == "__main__":
    unittest.main()
