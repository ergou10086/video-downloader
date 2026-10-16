import io
import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from video_downloader.services.po_token_provider import PoTokenProviderService


class PoTokenProviderServiceTests(unittest.TestCase):
    def test_missing_dependencies_returns_actionable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            service = PoTokenProviderService(Path(directory), Mock())
            with patch.object(service, "_ping", return_value=None):
                result = service.ensure_running()
        self.assertIn("error", result)
        self.assertIn("deno", result["error"])
        self.assertIn("bgutil-ytdlp-pot-provider", result["error"])

    def test_existing_provider_is_reused_without_spawning_process(self):
        log = Mock()
        with tempfile.TemporaryDirectory() as directory:
            service = PoTokenProviderService(Path(directory), log)
            with patch.object(service, "_ping", return_value={"version": "1.3.2"}), patch(
                "video_downloader.services.po_token_provider.subprocess.Popen"
            ) as popen:
                result = service.ensure_running()
        self.assertEqual(result, {
            "ok": True,
            "version": "1.3.2",
            "reused": True,
            "base_url": "http://127.0.0.1:4416",
        })
        popen.assert_not_called()
        self.assertIn("已连接现有", log.call_args.args[0])

    def test_cold_start_is_noninteractive_and_uses_installed_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            service = PoTokenProviderService(Path(directory), Mock())
            process = Mock(stdout=io.StringIO("Started POT server\n"))
            process.poll.return_value = None
            with (
                patch.object(service, "_ping", side_effect=[None, None, {"version": "1.3.2"}]),
                patch.object(service, "_dependency_error", return_value=None),
                patch.object(service._shutdown, "wait"),
                patch("video_downloader.services.po_token_provider.subprocess.Popen", return_value=process) as popen,
            ):
                result = service.ensure_running()
            self.assertTrue(result["ok"])
            self.assertFalse(result["reused"])
            command = popen.call_args.args[0]
            for flag in ("--no-prompt", "--cached-only", "--node-modules-dir=manual", "--allow-sys"):
                self.assertIn(flag, command)
            self.assertEqual(popen.call_args.kwargs["stdin"], subprocess.DEVNULL)
            self.assertEqual(popen.call_args.kwargs["env"]["DENO_NO_UPDATE_CHECK"], "1")

    def test_startup_failure_includes_deno_error_instead_of_last_stack_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            service = PoTokenProviderService(Path(directory), Mock())
            process = Mock(stdout=io.StringIO("error: missing cached dependency\n    at main.ts:1\n"))
            process.poll.return_value = 1
            with (
                patch.object(service, "_ping", return_value=None),
                patch.object(service, "_dependency_error", return_value=None),
                patch("video_downloader.services.po_token_provider.subprocess.Popen", return_value=process),
            ):
                result = service.ensure_running()
            self.assertIn("missing cached dependency", result["error"])
            self.assertIsNone(service._process)

    def test_unresponsive_provider_times_out_with_progress_and_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Mock()
            service = PoTokenProviderService(Path(directory), log)
            service.START_TIMEOUT = 0.03
            service.PROGRESS_INTERVAL = 0
            process = Mock(stdout=io.StringIO("Loading dependencies\n"))
            process.poll.return_value = None
            with (
                patch.object(service, "_ping", return_value=None),
                patch.object(service, "_dependency_error", return_value=None),
                patch.object(service, "_stop_owned_process") as stop,
                patch.object(service._shutdown, "wait"),
                patch("video_downloader.services.po_token_provider.time.monotonic", side_effect=[0, 0, 0, 0.01, 0.04]),
                patch("video_downloader.services.po_token_provider.subprocess.Popen", return_value=process),
            ):
                result = service.ensure_running()
            self.assertIn("启动超时", result["error"])
            self.assertIn("Loading dependencies", result["error"])
            self.assertTrue(any("等待 Provider 就绪" in call.args[0] for call in log.call_args_list))
            stop.assert_called_once_with(process)
            self.assertIsNone(service._process)

    def test_cancellation_during_cold_start_stops_owned_process(self):
        with tempfile.TemporaryDirectory() as directory:
            service = PoTokenProviderService(Path(directory), Mock())
            cancel_event = threading.Event()
            process = Mock(stdout=io.StringIO())
            process.poll.return_value = None

            def cancel_startup():
                cancel_event.set()
                return None

            with (
                patch.object(service, "_ping", side_effect=lambda: cancel_startup() if service._process else None),
                patch.object(service, "_dependency_error", return_value=None),
                patch.object(service, "_stop_owned_process") as stop,
                patch("video_downloader.services.po_token_provider.subprocess.Popen", return_value=process),
            ):
                result = service.ensure_running(cancel_event=cancel_event)
            self.assertEqual(result, {"cancelled": True})
            stop.assert_called_once_with(process)
            self.assertIsNone(service._process)

    def test_cancelled_task_does_not_probe_or_spawn(self):
        service = PoTokenProviderService(Path.cwd(), Mock())
        cancel_event = threading.Event()
        cancel_event.set()
        with patch.object(service, "_ping") as ping:
            self.assertEqual(service.ensure_running(cancel_event=cancel_event), {"cancelled": True})
        ping.assert_not_called()

    def test_shutdown_cancels_inflight_startup_before_taking_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            service = PoTokenProviderService(Path(directory), Mock())
            waiting = threading.Event()
            process = Mock(stdout=io.StringIO())
            process.poll.return_value = None

            def ping():
                if service._process is not None:
                    waiting.set()
                return None

            results = []
            with (
                patch.object(service, "_ping", side_effect=ping),
                patch.object(service, "_dependency_error", return_value=None),
                patch.object(service, "_stop_owned_process") as stop,
                patch("video_downloader.services.po_token_provider.subprocess.Popen", return_value=process),
            ):
                worker = threading.Thread(target=lambda: results.append(service.ensure_running()))
                worker.start()
                try:
                    self.assertTrue(waiting.wait(2))
                finally:
                    service.stop()
                    worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(results, [{"cancelled": True}])
            stop.assert_called_once_with(process)

    def test_ipv6_health_probe_bypasses_proxy_and_remembers_working_address(self):
        service = PoTokenProviderService(Path.cwd(), Mock())
        response = Mock(status=200)
        response.read.return_value = json.dumps({"version": "1.3.2"}).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.side_effect = [OSError("IPv4 refused"), response]
        with (
            patch("video_downloader.services.po_token_provider.ProxyHandler") as proxy,
            patch("video_downloader.services.po_token_provider.build_opener", return_value=opener),
        ):
            self.assertEqual(service._ping(), {"version": "1.3.2"})
        proxy.assert_called_once_with({})
        self.assertEqual(service.base_url, "http://[::1]:4416")
        self.assertEqual(service._candidate_base_urls[0], service.base_url)
        response.read.assert_called_once_with(4096)

    def test_stop_never_terminates_reused_external_provider(self):
        service = PoTokenProviderService(Path.cwd(), Mock())
        with (
            patch.object(service, "_ping", return_value={"version": "1.3.2"}),
            patch.object(service, "_stop_owned_process") as stop,
        ):
            service.ensure_running()
            service.stop()
        stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
