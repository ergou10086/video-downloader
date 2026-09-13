"""Centralized application directory layout and legacy path compatibility."""

from __future__ import annotations

import os
from pathlib import Path


DOWNLOAD_PLATFORM_DIRS = (
    "YouTube",
    "Bilibili",
    "Twitch",
    "Niconico",
    "NicoChannel",
    "Fantia",
    "TwitCasting",
    "Twitter",
    "Withny",
)


class AppPaths:
    """Resolve the clean runtime layout relative to the application directory.

    New installations keep third-party components in ``dependency`` and all
    generated downloads in ``download``.  Existing portable installations that
    still have a dependency in the application directory remain usable: an
    individual legacy asset is selected only when its canonical replacement is
    absent.
    """

    def __init__(self, app_dir: str | os.PathLike[str]):
        self.app_dir = Path(app_dir)
        self.dependency_dir = self.app_dir / "dependency"
        self.download_dir = self.app_dir / "download"
        self.archive_dir = self.download_dir / "archive"
        self.log_dir = self.download_dir / "logs"

    def ensure_runtime_dirs(self) -> None:
        """Create directories written by the application itself."""
        self.dependency_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        for platform_name in DOWNLOAD_PLATFORM_DIRS:
            (self.download_dir / platform_name).mkdir(parents=True, exist_ok=True)

    def dependency(self, relative_path: str | os.PathLike[str]) -> Path:
        """Return a dependency path, falling back to the pre-v2.4 layout."""
        relative = Path(relative_path)
        canonical = self.dependency_dir / relative
        legacy = self.app_dir / relative
        if canonical.exists() or not legacy.exists():
            return canonical
        return legacy

    def executable(self, name: str, exe_suffix: str = "") -> Path:
        return self.dependency(f"{name}{exe_suffix}")

    def plugin_dir(self) -> Path:
        """Return the root passed to yt-dlp for bundled plugin discovery."""
        canonical_markers = (
            self.dependency_dir / "yt-dlp-plugins",
            self.dependency_dir / "nicochannel.zip",
        )
        legacy_markers = (
            self.app_dir / "yt-dlp-plugins",
            self.app_dir / "nicochannel.zip",
        )
        if any(path.exists() for path in canonical_markers):
            return self.dependency_dir
        if any(path.exists() for path in legacy_markers):
            return self.app_dir
        return self.dependency_dir

    def subprocess_env(self, base: dict[str, str] | None = None) -> dict[str, str]:
        """Return an environment that can discover co-located dependencies."""
        env = dict(os.environ if base is None else base)
        search_dirs = [str(self.dependency_dir)]
        # Keep the old portable layout working while users transition.
        if self.app_dir != self.dependency_dir:
            search_dirs.append(str(self.app_dir))
        current = env.get("PATH", "")
        if current:
            search_dirs.append(current)
        env["PATH"] = os.pathsep.join(search_dirs)
        return env
