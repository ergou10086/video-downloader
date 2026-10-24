"""Bounded HTTP measurements and conservative, reviewable concurrency profiles.

Uses Cloudflare's public /__down endpoint, never video URLs or user cookies.
HTTP TTFB includes DNS/TCP/TLS; request failures are not packet-loss estimates.
"""
from __future__ import annotations

import copy
import math
import os
import shutil
import statistics
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from video_downloader.core.validation import validate_config

MIB = 1024 * 1024
MAX_TEST_BYTES = 32 * MIB
TEST_SECONDS = 20
RESULT_TTL = 15 * 60
PROXY_KEYS = ("PROXY_ENABLED", "PROXY_TYPE", "PROXY_ADDR", "PROXY_PORT")


def network_path(config):
    if not int(config.get("PROXY_ENABLED", 0)):
        return ("direct",)
    return tuple(str(config.get(key, "")) for key in PROXY_KEYS)


def recommend_profiles(metrics):
    """Heuristics, not a guarantee about arbitrary live-stream bitrates."""
    low = max(0.01, float(metrics["download_low_mbps"]))
    high = max(low, float(metrics["download_high_mbps"]))
    failures = metrics["request_failure_rate"]
    jitter = metrics["http_jitter_ms"] or 0
    loaded = metrics.get("loaded_latency_ms")
    increase = max(0, loaded - metrics["http_latency_ms"]) if loaded is not None else 0
    unstable = failures > 0 or jitter > 100 or increase > 200
    usable_high = high * (0.5 if unstable else 0.9)
    parents = min(5, max(1, int(usable_high // 80) + 1))
    live = min(5, max(2, int(usable_high / (parents * 24))))
    downloads = min(5, max(1, int(usable_high / (parents * 40))))
    fragments = min(16, max(2, int(usable_high / 15)),
                    max(1, 64 // (parents * (live + downloads))))
    if metrics["confidence"] == "limited":
        parents, live, downloads, fragments = min(parents, 2), min(live, 2), min(downloads, 2), min(fragments, 4)
    if unstable:
        parents, downloads = 1, 1
        live, fragments = 2, min(fragments, 2)
    safe_mbps = low * (0.45 if unstable else 0.65)
    reliable_parents = min(parents, 2, max(1, int(safe_mbps // 100) + 1))
    reliable_live = min(live, 3, max(2, int(safe_mbps / (reliable_parents * 32))))
    # At most 40% of the conservative budget goes to ordinary video downloads.
    # Only those URLs receive this limit; recordings keep their full bitrate.
    video_limit = max(0.1, math.floor((safe_mbps * 1e6 / 8 / MIB) * 0.4 / reliable_parents * 10) / 10)

    def settings(parent, live_count, video_count, threads, limit):
        return {"TASK_MAX_PARALLEL": parent, "TASK_MIXED_PARALLEL": 1,
                "TASK_LIVE_PARALLEL": live_count, "TASK_DOWNLOAD_PARALLEL": video_count,
                "THREADS": threads, "SPEED_LIMIT": 0, "TASK_DOWNLOAD_SPEED_LIMIT": limit}

    return {
        "performance": {
            "settings": settings(parents, live, downloads, fragments, 0),
            "summary": "按实测带宽高位提高并发，并按抖动、失败率及样本可信度收敛连接数。",
        },
        "reliable": {
            "settings": settings(reliable_parents, reliable_live, 1,
                                 1 if unstable else min(3, max(1, int(safe_mbps / 40))), round(video_limit, 1)),
            "summary": "按实测带宽低位留余量，每任务视频保持串行，并仅限制普通 yt-dlp 视频带宽，为直播预留容量。",
        },
    }


class NetworkDiagnostics:
    def __init__(self, *, app_state, save_config, begin_guard, end_guard,
                 publish=None, probe=None, curl_path=None, clock=time.monotonic):
        self._state = app_state
        self._save = save_config
        self._begin = begin_guard
        self._end = end_guard
        self._publish = publish or (lambda event: None)
        self._clock = clock
        self._curl = curl_path or shutil.which("curl.exe" if os.name == "nt" else "curl")
        self._probe = probe or self._curl_probe
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._processes = set()
        self._thread = None
        self._result_path = None
        self._result_time = None
        self._closed = False
        self._status = {"running": False, "phase": "idle", "message": "尚未检测", "result": None}

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._status)

    def _update(self, **values):
        with self._lock:
            self._status.update(values)
            snapshot = copy.deepcopy(self._status)
        self._publish({"type": "network_test", "data": snapshot})

    def start(self):
        with self._lock:
            if self._closed:
                return {"error": "程序正在关闭"}
            if self._status["running"]:
                return {"error": "网络检测已在运行"}
            if not self._curl and self._probe == self._curl_probe:
                return {"error": "未找到系统 curl，无法进行网络检测"}
            previous = copy.deepcopy(self._status)
            self._cancel.clear()
            self._status["running"] = True
        # Maintenance callbacks publish SSE: never call them under _lock.
        error = self._begin()
        if error:
            with self._lock:
                self._status = previous
            return error
        config = self._state.config_snapshot()
        with self._lock:
            self._result_time = None
            self._result_path = None
            self._status = {"running": True, "phase": "starting", "message": "正在准备网络检测", "result": None}
            self._thread = threading.Thread(target=self._run, args=(config,), name="network-test", daemon=True)
            if self._closed:
                self._status.update(running=False, phase="cancelled", message="程序正在关闭")
                error = "程序正在关闭"
            else:
                error = None
                try:
                    self._thread.start()
                except Exception as exc:
                    error = f"检测线程启动失败: {exc}"
        if error:
            self._update(running=False, phase="failed", message=error)
            self._end()
            return {"error": error}
        return {"ok": True}

    def cancel(self):
        self._cancel.set()
        with self._lock:
            processes = list(self._processes)
        for process in processes:
            try:
                process.kill()
            except OSError:
                pass
        return {"ok": True}

    def stop(self):
        with self._lock:
            self._closed = True
        self.cancel()
        with self._lock:
            thread = self._thread
        if thread and thread.ident is not None and thread is not threading.current_thread():
            thread.join(timeout=5)

    def _curl_probe(self, size, timeout, config, cancel):
        writeout = "%{http_code} %{size_download} %{time_total} %{time_starttransfer}"
        command = [self._curl, "--disable", "--silent", "--show-error", "--fail",
                   "--proto", "=https", "--max-time", f"{timeout:.2f}",
                   "--connect-timeout", f"{min(2.5, timeout):.2f}",
                   "--max-filesize", str(max(1, size)), "--output", os.devnull,
                   "--header", "Accept-Encoding: identity", "--header", "Cache-Control: no-cache",
                   "--user-agent", "VideoDownloader-NetworkCheck/1.0", "--write-out", writeout]
        # Ignore curlrc and proxy environment variables, including NO_PROXY.
        if int(config.get("PROXY_ENABLED", 0)):
            host = str(config.get("PROXY_ADDR", "")).strip()
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            scheme = "socks5h" if config.get("PROXY_TYPE") == "socks5" else "http"
            command += ["--proxy", f"{scheme}://{host}:{config['PROXY_PORT']}", "--noproxy", ""]
        else:
            command += ["--noproxy", "*", "--proxy", ""]
        command += [f"https://speed.cloudflare.com/__down?bytes={size}&nonce={uuid.uuid4().hex}"]
        env = {key: value for key, value in os.environ.items()
               if key.lower() not in {"http_proxy", "https_proxy", "all_proxy", "no_proxy", "ftp_proxy"}}
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=env, text=True, encoding="utf-8", errors="replace",
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            hard_deadline = time.monotonic() + timeout + 1
            with self._lock:
                self._processes.add(process)
            while True:
                if cancel.is_set() or time.monotonic() >= hard_deadline:
                    try:
                        process.kill()
                    except OSError:
                        pass
                try:
                    output, error = process.communicate(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    continue
            parts = output.strip().split()
            if len(parts) != 4:
                return {"ok": False, "bytes": 0, "error": error.strip()[:200] or "检测请求无有效结果"}
            status, received, duration, ttfb = map(float, parts)
            valid = all(math.isfinite(value) for value in (received, duration, ttfb))
            return {"ok": valid and process.returncode == 0 and status == 200 and received == size,
                    "bytes": max(0, int(received)) if valid else 0, "duration": duration, "ttfb": ttfb,
                    "error": error.strip()[:200] or ("" if process.returncode == 0 else f"请求失败 ({process.returncode})")}
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
            with self._lock:
                self._processes.discard(process)

    def _measure(self, config):
        started = self._clock()
        deadline = started + TEST_SECONDS
        samples, latencies, loaded_latencies, bandwidth = [], [], [], []
        loaded_candidates = []
        sample_lock = threading.Lock()
        allocated = 0

        def sample(size, category):
            if self._cancel.is_set() or self._clock() >= deadline:
                return None
            begin = self._clock()
            item = self._probe(size, max(0.1, min(3, deadline - begin)), config, self._cancel)
            item = dict(item, category=category, started=begin, finished=self._clock())
            with sample_lock:
                samples.append(item)
            return item

        def rate(item):
            return item["bytes"] * 8 / max(item["duration"], 0.001) / 1e6

        self._update(phase="latency", message="检测 HTTP 延迟与抖动（1/3）")
        for _ in range(3):
            item = sample(0, "latency")
            if item and item["ok"]:
                latencies.append(item["ttfb"] * 1000)
        if self._cancel.is_set():
            return None
        self._update(phase="single", message="检测单连接吞吐与波动（2/3）")
        warmup = sample(256 * 1024, "warmup")
        allocated += 256 * 1024
        estimate = rate(warmup) if warmup and warmup["ok"] else 2
        block_size = max(256 * 1024, min(4 * MIB, int(estimate * 1e6 / 8 * 1.5)))
        single_rates = []
        for _ in range(2):
            allocated += block_size
            item = sample(block_size, "single")
            if item and item["ok"]:
                single_rates.append(rate(item))
                bandwidth.append(item)
        if self._cancel.is_set():
            return None
        self._update(phase="parallel", message="检测多连接吞吐和负载延迟（3/3）")
        parallel_size = min(block_size * 2, 8 * MIB, (MAX_TEST_BYTES - allocated) // 3)
        parallel_samples = []
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="network-probe") as pool:
            futures = [pool.submit(sample, parallel_size, "parallel") for _ in range(3)]

            def loaded_probe():
                for _ in range(3):
                    if all(future.done() for future in futures) or self._cancel.is_set():
                        break
                    item = sample(0, "loaded")
                    if item and item["ok"]:
                        loaded_candidates.append(item)

            latency_future = pool.submit(loaded_probe)
            for future in futures:
                item = future.result()
                if item:
                    parallel_samples.append(item)
                    if item["ok"]:
                        bandwidth.append(item)
            latency_future.result()
        if self._cancel.is_set():
            return None
        successful_parallel = [item for item in parallel_samples if item["ok"]]
        # An overlapping TLS handshake alone is not download load. Require a
        # sustained body transfer and check overlap after its timings are known.
        body_windows = [(i["started"] + i["ttfb"], i["finished"]) for i in parallel_samples
                        if i.get("duration", 0) - i.get("ttfb", 0) >= .25]
        for probe in loaded_candidates:
            if any(min(probe["finished"], end) - max(probe["started"], begin) >= .01
                   for begin, end in body_windows):
                loaded_latencies.append(probe["ttfb"] * 1000)
        parallel_rate = None
        if successful_parallel:
            # Failed/partial transfers consumed capacity too; include their time
            # span but only count complete successful payloads in the estimate.
            elapsed = max(i["finished"] for i in parallel_samples) - min(i["started"] for i in parallel_samples)
            parallel_rate = sum(i["bytes"] for i in successful_parallel) * 8 / max(elapsed, .001) / 1e6
        rates = single_rates + ([parallel_rate] if parallel_rate else [])
        if not latencies or len(bandwidth) < 2 or not rates:
            detail = next((item.get("error") for item in samples if item.get("error")), "连接超时或测试节点不可达")
            raise RuntimeError("有效测量样本不足，未生成自动配置；请检查网络/代理或稍后重试：" + detail)
        failures = sum(not item["ok"] for item in samples) / len(samples)
        jitter = statistics.mean(abs(b - a) for a, b in zip(latencies, latencies[1:])) if len(latencies) > 1 else None
        longest_body = max(max(0, i["duration"] - i["ttfb"]) for i in bandwidth)
        limited = len(latencies) < 3 or len(bandwidth) < 4 or failures > .15 or longest_body < .25
        notes = [
            "这是到 Cloudflare 测试节点的短时 HTTP 测量；不是平台专属带宽、ICMP 延迟或丢包率。",
            "首字节延迟包含 DNS/TCP/TLS；带宽区间是本轮观测高低位，不是线路绝对上下限。",
            "未检测上传带宽、长时间断流、磁盘性能或具体直播码率；任何方案均不能保证不漏录。",
        ]
        if limited:
            notes.append("本轮样本有限或线路波动明显，已收敛高性能方案的并发数量。")
        if not loaded_latencies:
            notes.append("下载阶段太短或探针未有效重叠，负载延迟未测得。")
        if min(rates) < 24:
            notes.append("低位带宽较低，两路高码率直播可能已超过容量；请减少录制任务或降低平台画质。")
        metrics = {
            "download_low_mbps": round(min(rates), 2), "download_high_mbps": round(max(rates), 2),
            "single_mbps": round(statistics.median(single_rates), 2) if single_rates else None,
            "parallel_mbps": round(parallel_rate, 2) if parallel_rate else None,
            "http_latency_ms": round(statistics.median(latencies), 1), "http_jitter_ms": round(jitter, 1) if jitter is not None else None,
            "loaded_latency_ms": round(statistics.median(loaded_latencies), 1) if loaded_latencies else None,
            "request_failure_rate": round(failures, 4), "sample_count": len(samples),
            "downloaded_mib": round(sum(i.get("bytes", 0) for i in samples) / MIB, 2),
            "duration_seconds": round(self._clock() - started, 1),
            "confidence": "limited" if limited else "normal",
        }
        return {"id": uuid.uuid4().hex, "metrics": metrics, "notes": notes,
                "route": "直连" if network_path(config) == ("direct",) else "使用应用配置的代理",
                "profiles": recommend_profiles(metrics)}

    def _run(self, config):
        result, error = None, None
        try:
            result = self._measure(config)
        except Exception as exc:
            error = str(exc)
        finally:
            # Release maintenance only once every probe/curl process has stopped.
            try:
                self._end()
            except Exception as exc:
                error = error or f"检测清理失败: {exc}"
        with self._lock:
            if result is not None and not error and not self._cancel.is_set():
                self._result_path = network_path(config)
                self._result_time = self._clock()
        cancelled = self._cancel.is_set()
        self._update(running=False, phase="cancelled" if cancelled else "failed" if error or result is None else "completed",
                     message="检测已取消" if cancelled else error or "检测完成，请选择配置方案",
                     result=None if cancelled or error else result)

    def apply(self, mode, result_id):
        with self._lock:
            result = self._status.get("result")
            if mode not in {"performance", "reliable"}:
                return {"error": "未知配置方案"}
            if (self._status["running"] or not result or result["id"] != result_id
                    or self._result_time is None or self._clock() - self._result_time > RESULT_TTL):
                return {"error": "检测结果已失效，请重新检测"}
            settings = dict(result["profiles"][mode]["settings"])
            path = self._result_path
        error = self._begin()
        if error:
            return error
        try:
            with self._state.config_lock:
                previous = self._state.config_snapshot()
                if network_path(previous) != path:
                    return {"error": "代理或网络路径设置已改变，请重新检测"}
                config, errors = validate_config(settings, previous)
                if errors:
                    return {"error": "推荐配置校验失败: " + ", ".join(errors)}
                self._state.replace_config(config)
                try:
                    self._save()
                except Exception as exc:
                    self._state.replace_config(previous)
                    return {"error": f"保存自动配置失败，已恢复原设置: {exc}"}
            return {"ok": True, "config": config}
        finally:
            self._end()
