"""Install the two pinned, pure-Python live extras without changing system Python."""
from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen


def install(root):
    root = Path(root)
    lock = json.loads((root / "dependency/live-python.lock.json").read_text(encoding="utf-8"))
    target = root / "dependency/live-python"
    if target.exists():
        if (target / "installed.json").read_text(encoding="utf-8") == json.dumps(lock, indent=2):
            return target
        raise RuntimeError("dependency/live-python already exists with different contents")
    with tempfile.TemporaryDirectory(prefix="live-install-", dir=root / "dependency") as name:
        stage = Path(name) / "runtime"
        stage.mkdir()
        for package in lock["packages"]:
            url = package["url"]
            if urlsplit(url).hostname != "files.pythonhosted.org" or urlsplit(url).scheme != "https":
                raise ValueError("Only pinned official PyPI wheels are accepted")
            with urlopen(url, timeout=30) as response:
                data = response.read(4 * 1024 * 1024)
            if hashlib.sha256(data).hexdigest() != package["sha256"]:
                raise ValueError("Wheel checksum mismatch: " + package["name"])
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for member in archive.infolist():
                    if not (stage / member.filename).resolve().is_relative_to(stage.resolve()):
                        raise ValueError("Invalid wheel path")
                archive.extractall(stage)
        (stage / "installed.json").write_text(json.dumps(lock, indent=2), encoding="utf-8")
        os.replace(stage, target)
    return target


if __name__ == "__main__":
    print(install(Path(__file__).resolve().parents[1]))
