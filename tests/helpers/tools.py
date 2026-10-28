"""Tool service factories and subprocess/thread doubles."""
from video_downloader.services.tools import ToolService


class FakeAppState:
    def __init__(self):
        self.updates = []

    def update_config(self, values):
        self.updates.append(values)


def create_service(tool_dir, build_subtitle_command=None, download_manager=None, log=None,
                   build_cover_command=None):
    return ToolService(
        tool_dir=tool_dir,
        exe_suffix=".exe",
        app_state=FakeAppState(),
        save_config=lambda: None,
        log=log or (lambda message, level="info": None),
        build_subtitle_command=build_subtitle_command,
        build_cover_command=build_cover_command,
        download_manager=download_manager,
    )


class ImmediateThread:
    def __init__(self, target, args=(), kwargs=None, daemon=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}

    def start(self):
        self.target(*self.args, **self.kwargs)


class FakePopen:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    def communicate(self, timeout=None):
        return self._stdout, self._stderr

    def kill(self):
        pass

    def wait(self):
        return self.returncode
