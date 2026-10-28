"""Verify the portable live runtime and source/frozen API compatibility before release."""
import hashlib
import importlib.metadata
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from video_downloader.live.danmaku.dependencies import self_check


def check(root=ROOT):
    root = Path(root)
    lock = json.loads((root / "resource/dependencies/live-python.lock.json").read_text(encoding="utf-8"))
    runtime = root / "dependency/live-python"
    result = self_check()
    result["installed_lock"] = json.loads((runtime / "installed.json").read_text(encoding="utf-8")) == lock
    for package in lock["packages"]:
        result[package["name"]] = importlib.metadata.version(package["name"]) == package["version"]
    for asset in lock.get("assets", []):
        path = runtime / asset["path"]
        result[asset["path"]] = path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"]
    return result


if __name__ == "__main__":
    result = check()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if all(result.values()) else 1)
