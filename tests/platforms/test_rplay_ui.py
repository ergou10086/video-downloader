"""Check the actual UI routing helper against backend classification."""

import json
import shutil
import subprocess
from unittest import mock

import pytest

from tests.helpers import PROJECT_ROOT
from video_downloader.core.paths import AppPaths
from video_downloader.live.classifier import is_live_url


def test_ui_and_backend_agree_on_rplay_routes():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is unavailable for the UI routing check')
    oid = '682065da13ed2c564c77d8f7'
    urls = [
        f'https://rplay.live/live/{oid}', f'https://www.rplay.live/creatorhome/{oid}',
        f'https://rplay.live/play/{oid}', f'https://rplay.live/creatorhome/{oid}?page=contents',
        f'https://api.rplay.live/live/{oid}', f'https://rplay.live.evil/live/{oid}',
        f'https://rplay.live/live/{oid}/extra', f'https://rplay.live/live/{oid}?page=contents',
        f'https://rplay.live:443/live/{oid}', f'https://rplay.live:444/live/{oid}',
        f'https://user:secret@rplay.live/live/{oid}', f'https://rplay.live/LIVE/{oid}',
        f'https://rplay.live//live/{oid}', f'https://rplay.live/live/{oid}//', 'not a URL',
    ]
    script = r'''
const fs = require('fs'), vm = require('vm');
const inputs = JSON.parse(process.argv[1]);
const context = {URL, window:{}, document:{addEventListener(){}, getElementById(){return null;}}, setTimeout(){}};
vm.createContext(context);
const source = fs.readFileSync('resource/static/js/app.js','utf8').replace(/^init\(\);$/m, '');
vm.runInContext(source,context);
const flags = inputs.map(url => vm.runInContext(`Boolean(isLiveCandidateUrl(${JSON.stringify(url)}))`,context));
const platforms = vm.runInContext('PLATFORMS.filter(p=>p.name==="Rplay")',context);
process.stdout.write(JSON.stringify({flags, platforms}));
'''
    result = subprocess.run([node, '-e', script, json.dumps(urls)], cwd=PROJECT_ROOT,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data['flags'] == [is_live_url(url) for url in urls]
    assert len(data['platforms']) == 1


def test_source_plugin_is_found_in_a_simulated_frozen_resource_root(tmp_path):
    bundled = tmp_path/'frozen/yt-dlp-plugins'
    shutil.copytree(PROJECT_ROOT/'resource/yt-dlp-plugins', bundled)
    with mock.patch('sys._MEIPASS', str(bundled.parent), create=True):
        roots = AppPaths(tmp_path/'portable').plugin_dirs()
    assert bundled in roots
    assert (bundled/'video_downloader/yt_dlp_plugins/extractor/rplay.py').is_file()
