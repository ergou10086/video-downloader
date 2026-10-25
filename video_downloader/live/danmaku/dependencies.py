"""Source portable installs and frozen builds use the same pinned libraries."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path


def library(name):
    if not getattr(sys, "frozen", False):
        vendor = Path(__file__).resolve().parents[3] / "dependency" / "live-python"
        if vendor.is_dir() and str(vendor) not in sys.path:
            sys.path.insert(0, str(vendor))
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise RuntimeError("直播弹幕依赖缺失，请运行 python scripts/install_live_dependencies.py") from exc
