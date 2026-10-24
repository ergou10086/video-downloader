"""BililiveRecorder 2.20 portable CLI and authenticated loopback REST adapter."""
from __future__ import annotations

import base64
import hashlib
import http.cookiejar
import json
import re
import secrets
import socket
import subprocess
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler

from ..events import BrecEvents
from ..process import hidden_options


class EngineUnavailable(RuntimeError):
    pass


def validate_install(directory):
    directory = Path(directory)
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest["version"] != "2.20.0" or not manifest["files"]:
            raise ValueError("unsupported manifest")
        for relative, expected in manifest["files"].items():
            file = (directory / relative).resolve()
            if not file.is_relative_to(directory.resolve()):
                raise ValueError("invalid manifest path")
            with file.open("rb") as source:
                digest = hashlib.sha256()
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                raise ValueError("checksum mismatch: " + relative)
        binary = directory / "BililiveRecorder.Cli.exe"
        result = subprocess.run([str(binary), "--version"], capture_output=True, timeout=15, **hidden_options())
        if result.returncode or not result.stdout.decode("utf-8", "replace").startswith("2.20.0+"):
            raise ValueError("unsupported CLI version")
        return binary
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        raise EngineUnavailable("录播姬未安装、校验失败或版本不兼容: " + str(exc)) from exc


def cookie_from_file(path):
    jar = http.cookiejar.MozillaCookieJar(str(path))
    jar.load(ignore_discard=True, ignore_expires=False)
    return "; ".join(f"{c.name}={c.value}" for c in jar if
                     (c.domain.lstrip(".") == "bilibili.com" or c.domain.endswith(".bilibili.com"))
                     and not c.is_expired())


class BililiveEngine:
    name = "bililive-recorder"

    def __init__(self, binary, session, room_id, *, cookie=""):
        self.binary, self.session, self.room_id = str(binary), session, int(room_id)
        self.cookie = cookie
        self.user, self.password = secrets.token_urlsafe(12), secrets.token_urlsafe(32)
        # 2.20 suppresses Kestrel's listening-address log; reserve an OS-assigned
        # port. A bind race is a startup failure handled before media fallback.
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            self.base_url = f"http://127.0.0.1:{reservation.getsockname()[1]}"
        self.events = None
        self.opener = build_opener(ProxyHandler({}))
        self._auth = "Basic " + base64.b64encode(f"{self.user}:{self.password}".encode()).decode()

    def command(self, directory):
        self.events = BrecEvents(self.session, directory, self.room_id)
        command = [self.binary, "portable", str(directory), str(self.room_id),
                   "--bind", self.base_url, "--http-basic-user", self.user,
                   "--http-basic-pass", self.password, "--enable-file-browser", "false",
                   "--mode", "Standard", "--danmaku", "All", "--webhook-url", self.events.url,
                   "--log", "Information", "--flog", "Error"]
        if self.cookie:
            command += ["--cookie", self.cookie]
        return command

    def line(self, value):
        match = re.search(r"Now listening on:\s*(http://127\.0\.0\.1:\d+)", value)
        if match:
            self.base_url = match.group(1)

    def request(self, suffix, method="POST", data=None):
        if self.base_url is None:
            raise EngineUnavailable("录播姬控制 API 尚未启动")
        request = Request(self.base_url + suffix, data=json.dumps(data or {}).encode() if method == "POST" else None,
                          headers={"Authorization": self._auth, "Content-Type": "application/json"}, method=method)
        with self.opener.open(request, timeout=2) as response:
            return json.loads(response.read() or b"{}")

    def stop_recording(self):
        # Disable AutoRecord first, otherwise the room monitor can start another session.
        self.request(f"/api/room/{self.room_id}/config", data={"autoRecord": False})
        self.request(f"/api/room/{self.room_id}/stop")

    def close(self):
        if self.events:
            self.events.close()
