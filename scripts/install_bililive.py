"""Install the pinned external recorder; never add GPL binaries to the main exe.

Usage: python scripts/install_bililive.py [path-to-official-zip]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "2.20.0"
ARCHIVE_SHA256 = "4fcd057125dda3d37836bf9e192b68c4af0ed229f7fdbcd195c4bdb3918d9403"
SOURCE = f"https://github.com/BililiveRecorder/BililiveRecorder/tree/v{VERSION}"


def install(archive, destination):
    archive, destination = Path(archive), Path(destination)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("压缩包 SHA256 与官方 v2.20.0 win-x64 发布资产不一致，拒绝安装")
    if (destination / "BililiveRecorder.Cli.exe").exists():
        raise ValueError("目标目录已有录播姬。请先停止录制，再备份或移走原目录后安装")
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        for entry in zipped.infolist():
            if not (destination / entry.filename).resolve().is_relative_to(destination.resolve()):
                raise ValueError("压缩包包含越界路径")
        zipped.extractall(destination)
        names = [entry.filename for entry in zipped.infolist() if not entry.is_dir()]
    shutil.copyfile(ROOT / "dependency/BililiveRecorder.LICENSE", destination / "LICENSE")
    (destination / "SOURCE.txt").write_text(
        f"BililiveRecorder v{VERSION} (GPL-3.0)\nSource: {SOURCE}\n"
        f"Source archive: https://github.com/BililiveRecorder/BililiveRecorder/archive/refs/tags/v{VERSION}.zip\n"
        f"Release: https://github.com/BililiveRecorder/BililiveRecorder/releases/tag/v{VERSION}\n"
        f"Binary archive SHA256: {ARCHIVE_SHA256}\n", encoding="utf-8")
    names += ["LICENSE", "SOURCE.txt"]
    files = {name: hashlib.sha256((destination / name).read_bytes()).hexdigest() for name in sorted(names)}
    (destination / "manifest.json").write_text(json.dumps({
        "version": VERSION, "archive_sha256": ARCHIVE_SHA256, "files": files}, indent=2), encoding="utf-8")
    (destination / "SHA256.txt").write_text("".join(f"{digest}  {name}\n" for name, digest in files.items()), encoding="utf-8")
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", nargs="?", type=Path, default=ROOT / "dependency/BililiveRecorder-CLI-win-x64.zip")
    args = parser.parse_args()
    try:
        print(install(args.archive, ROOT / "dependency/BililiveRecorder"))
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
