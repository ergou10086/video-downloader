import subprocess
import threading
import time
import unittest
from unittest.mock import Mock, patch

from video_downloader.core.constants import DEFAULT_CONFIG
from video_downloader.core.validation import validate_config
from video_downloader.services.network_diagnostics import (
    MAX_TEST_BYTES, NetworkDiagnostics, network_path, recommend_profiles,
)
from video_downloader.state.app_state import AppState


def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(.01)
    return False


def good_probe(size, timeout, config, cancel):
    duration = .02 + size / (80 * 1024 * 1024)
    cancel.wait(min(.05, duration))
    return {"ok": not cancel.is_set(), "bytes": size, "duration": duration, "ttfb": .02}


class NetworkDiagnosticsTests(unittest.TestCase):
    def make(self, probe=good_probe, begin=None, save=None):
        state = AppState(config=dict(DEFAULT_CONFIG))
        saved = save or Mock()
        end = Mock()
        events = []
        service = NetworkDiagnostics(app_state=state, save_config=saved,
            begin_guard=begin or Mock(return_value=None), end_guard=end,
            publish=events.append, probe=probe, curl_path="curl-test")
        self.addCleanup(service.stop)
        return service, state, saved, end, events

    def complete(self, service):
        self.assertTrue(service.start()["ok"])
        self.assertTrue(wait_until(lambda: not service.snapshot()["running"]))
        status = service.snapshot()
        self.assertEqual(status["phase"], "completed", status)
        return status["result"]

    def test_test_is_bounded_and_produces_two_valid_distinct_profiles(self):
        sizes, timeouts = [], []
        def probe(size, timeout, config, cancel):
            sizes.append(size)
            timeouts.append(timeout)
            return good_probe(size, timeout, config, cancel)
        service, _, _, end, events = self.make(probe)
        result = self.complete(service)
        self.assertLessEqual(sum(sizes), MAX_TEST_BYTES)
        self.assertLessEqual(max(timeouts), 3)
        self.assertLess(result["metrics"]["duration_seconds"], 20)
        for profile in result["profiles"].values():
            self.assertEqual(validate_config(profile["settings"])[1], [])
        self.assertEqual(result["profiles"]["reliable"]["settings"]["TASK_DOWNLOAD_PARALLEL"], 1)
        self.assertGreater(result["profiles"]["reliable"]["settings"]["TASK_DOWNLOAD_SPEED_LIMIT"], 0)
        self.assertEqual(result["profiles"]["performance"]["settings"]["TASK_DOWNLOAD_SPEED_LIMIT"], 0)
        end.assert_called_once()
        self.assertTrue(any(event["type"] == "network_test" for event in events))

    def test_apply_patches_only_tuning_fields_and_saves_config(self):
        service, state, saved, end, _ = self.make()
        state.update_config({"RESOLUTION":"720", "TASK_ORDER":"live_first"})
        result = self.complete(service)
        response = service.apply("reliable", result["id"])
        self.assertTrue(response["ok"])
        self.assertEqual(state.config_snapshot()["RESOLUTION"], "720")
        self.assertEqual(state.config_snapshot()["TASK_ORDER"], "live_first")
        self.assertEqual(state.config_snapshot()["TASK_DOWNLOAD_PARALLEL"], 1)
        saved.assert_called_once()
        self.assertEqual(end.call_count, 2)

    def test_tiny_transfer_windows_do_not_claim_loaded_latency_or_full_confidence(self):
        service, _, _, _, _ = self.make()
        result = self.complete(service)
        self.assertIsNone(result["metrics"]["loaded_latency_ms"])
        self.assertEqual(result["metrics"]["confidence"], "limited")

    def test_failed_save_restores_all_original_config(self):
        service, state, saved, _, _ = self.make(save=Mock(side_effect=OSError("disk full")))
        result = self.complete(service)
        previous = state.config_snapshot()
        self.assertIn("error", service.apply("performance", result["id"]))
        self.assertEqual(state.config_snapshot(), previous)

    def test_proxy_change_rejects_old_recommendations(self):
        service, state, saved, _, _ = self.make()
        result = self.complete(service)
        state.update_config({"PROXY_ENABLED":1})
        self.assertIn("error", service.apply("reliable", result["id"]))
        saved.assert_not_called()

    def test_stale_result_unknown_mode_and_wrong_id_are_rejected(self):
        service, _, saved, _, _ = self.make()
        result = self.complete(service)
        self.assertIn("error", service.apply("bad", result["id"]))
        self.assertIn("error", service.apply("reliable", "wrong"))
        service._result_time -= 901
        self.assertIn("error", service.apply("reliable", result["id"]))
        saved.assert_not_called()

    def test_running_tasks_prevent_test_and_profile_application(self):
        guard = Mock(return_value={"error":"running tasks"})
        service, _, _, end, _ = self.make(begin=guard)
        self.assertIn("error", service.start())
        self.assertFalse(service.snapshot()["running"])
        end.assert_not_called()
        guard.return_value = None
        result = self.complete(service)
        guard.return_value = {"error":"running tasks"}
        self.assertIn("error", service.apply("performance", result["id"]))

    def test_cancel_wakes_probe_and_releases_guard_once(self):
        entered = threading.Event()
        def blocked(size, timeout, config, cancel):
            entered.set()
            cancel.wait(2)
            return {"ok":False, "bytes":0, "error":"cancelled"}
        service, _, _, end, _ = self.make(blocked)
        service.start()
        self.assertTrue(entered.wait(1))
        self.assertIn("error", service.start())
        service.cancel()
        self.assertTrue(wait_until(lambda: not service.snapshot()["running"]))
        self.assertEqual(service.snapshot()["phase"], "cancelled")
        self.assertIsNone(service.snapshot()["result"])
        end.assert_called_once()

    def test_failed_measurement_does_not_invent_bandwidth_or_profiles(self):
        service, _, saved, end, _ = self.make(
            lambda *args: {"ok":False, "bytes":0, "error":"test endpoint unavailable"})
        service.start()
        self.assertTrue(wait_until(lambda: not service.snapshot()["running"]))
        self.assertEqual(service.snapshot()["phase"], "failed")
        self.assertIsNone(service.snapshot()["result"])
        self.assertIn("test endpoint unavailable", service.snapshot()["message"])
        self.assertIn("error", service.apply("performance", "none"))
        saved.assert_not_called()
        end.assert_called_once()

    def test_thread_start_failure_releases_guard(self):
        service, _, _, end, _ = self.make()
        with patch("video_downloader.services.network_diagnostics.threading.Thread.start",
                   side_effect=RuntimeError("no thread")):
            self.assertIn("error", service.start())
        self.assertFalse(service.snapshot()["running"])
        end.assert_called_once()

    def test_begin_guard_does_not_hold_snapshot_lock_during_publication(self):
        service, _, _, _, _ = self.make()
        observed = threading.Event()
        def guard():
            thread = threading.Thread(target=lambda: (service.snapshot(), observed.set()), daemon=True)
            thread.start()
            self.assertTrue(observed.wait(1), "guard publication must not deadlock SSE ready")
            return {"error":"skip"}
        service._begin = guard
        self.assertIn("error", service.start())

    def test_curl_uses_explicit_proxy_path_and_does_not_inherit_environment(self):
        service, _, _, _, _ = self.make()
        process = Mock()
        process.communicate.return_value = ("200 0 0.05 0.04", "")
        process.poll.return_value = 0
        process.returncode = 0
        with patch("video_downloader.services.network_diagnostics.subprocess.Popen", return_value=process) as popen, \
             patch.dict("os.environ", {"HTTP_PROXY":"bad", "NO_PROXY":"*"}):
            result = service._curl_probe(0, 2, dict(DEFAULT_CONFIG), threading.Event())
        self.assertTrue(result["ok"])
        command = popen.call_args.args[0]
        self.assertEqual(command[1], "--disable")
        self.assertEqual(command[command.index("--proxy") + 1], "")
        self.assertEqual(command[command.index("--noproxy") + 1], "*")
        self.assertNotIn("HTTP_PROXY", popen.call_args.kwargs["env"])
        self.assertNotIn("NO_PROXY", popen.call_args.kwargs["env"])
        with patch("video_downloader.services.network_diagnostics.subprocess.Popen", return_value=process) as popen:
            service._curl_probe(0, 2, dict(DEFAULT_CONFIG, PROXY_ENABLED=1, PROXY_TYPE="socks5",
                                         PROXY_ADDR="::1"), threading.Event())
        command = popen.call_args.args[0]
        self.assertEqual(command[command.index("--proxy") + 1], "socks5h://[::1]:7890")

    def test_inactive_proxy_address_edits_do_not_invalidate_direct_route(self):
        self.assertEqual(network_path(DEFAULT_CONFIG),
                         network_path(dict(DEFAULT_CONFIG, PROXY_ADDR="changed")))


class NetworkRecommendationTests(unittest.TestCase):
    def test_any_failed_request_constrains_concurrency_even_on_fast_link(self):
        profiles = recommend_profiles({"download_low_mbps":500, "download_high_mbps":1000,
            "request_failure_rate":.02, "http_jitter_ms":1, "http_latency_ms":10,
            "loaded_latency_ms":15, "confidence":"normal"})
        for profile in profiles.values():
            self.assertEqual(profile["settings"]["TASK_MAX_PARALLEL"], 1)
            self.assertEqual(profile["settings"]["TASK_DOWNLOAD_PARALLEL"], 1)

    def test_ranges_remain_valid_across_slow_fast_unstable_and_limited_samples(self):
        for low, high in ((.1, .5), (10, 20), (60, 100), (500, 1000), (1000, 3000)):
            for limited in (False, True):
                for unstable in (False, True):
                    metrics = {"download_low_mbps":low, "download_high_mbps":high,
                               "request_failure_rate":.3 if unstable else 0,
                               "http_jitter_ms":200 if unstable else 5,
                               "http_latency_ms":20, "loaded_latency_ms":500 if unstable else 30,
                               "confidence":"limited" if limited else "normal"}
                    profiles = recommend_profiles(metrics)
                    for profile in profiles.values():
                        self.assertEqual(validate_config(profile["settings"])[1], [])
                    perf, reliable = (profiles[key]["settings"] for key in ("performance", "reliable"))
                    self.assertLessEqual(reliable["TASK_MAX_PARALLEL"], perf["TASK_MAX_PARALLEL"])
                    self.assertLessEqual(reliable["TASK_LIVE_PARALLEL"], perf["TASK_LIVE_PARALLEL"])
                    self.assertEqual(reliable["TASK_DOWNLOAD_PARALLEL"], 1)
