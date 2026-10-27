from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files


project_root = Path(SPECPATH)
sys.path.insert(0, str(project_root / "dependency" / "live-python"))
entry_script = project_root / "视频下载工具v2.6.0-GUI.py"
resource_root = project_root / "resource"
plugin_root = project_root / "dependency" / "yt-dlp-plugins"
packaging_deps = project_root / "build" / "packaging-deps"

datas = [
    (str(project_root / "NOTICE"), "licenses"),
    (str(project_root / "dependency" / "pysubs2.LICENSE"), "licenses"),
    (str(project_root / "dependency" / "defusedxml.LICENSE"), "licenses"),
    (str(project_root / "dependency" / "NDGR-protocol.LICENSE"), "licenses"),
    (str(project_root / "dependency" / "live-python.lock.json"), "licenses"),
    (str(resource_root / "templates"), "templates"),
    (str(resource_root / "static"), "static"),
    (str(plugin_root), "yt-dlp-plugins"),
]
live_vendor = project_root / "dependency" / "live-python"
for metadata in live_vendor.glob("*.dist-info"):
    datas.append((str(metadata), "licenses/" + metadata.name))
datas += collect_data_files("certifi")
live_modules = ["pysubs2", "websocket", "python_socks", "httpx", "httpcore", "h2", "socksio",
                "google.protobuf", "ndgr_client.proto", "ruamel.yaml", "anyio"]

a = Analysis(
    [str(entry_script)],
    pathex=[str(project_root), str(packaging_deps), str(project_root / "dependency" / "live-python")],
    binaries=[],
    datas=datas,
    hiddenimports=["tkinter", "tkinter.filedialog", "yt_dlp", "yt_dlp.cookies", "yt_dlp.utils", "cramjam",
                   *(module for package in live_modules for module in collect_submodules(package)),
                   "defusedxml.ElementTree", "certifi"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="视频下载工具v2.6.0-GUI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
