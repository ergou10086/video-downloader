"""Build the MIT native Withny recorder with the local chat protocol fix.

Requires Go >=1.25. Source archive and Go modules are checksum verified.
The resulting executable stays external to the main application.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'https://codeload.github.com/Darkness4/withny-dl/zip/refs/tags/v2.0.0'
SOURCE_SHA256 = 'f64134ff918b6611b635a1f13563f098531a7143ff19d3276adb483a5dd69f11'


def prepare(source):
    patch = Path(__file__).with_name('withny_patch')
    shutil.copyfile(patch / 'chat.go', source / 'withny/chat.go')
    shutil.copyfile(patch / 'lifecycle.go', source / 'withny/managed_lifecycle.go')
    path = source / 'withny/channel_watcher.go'
    code = path.read_text(encoding='utf-8')
    if code.count('res, err := w.HasNewStream(ctx)') != 2:
        raise ValueError('Unexpected upstream watcher implementation')
    code = code.replace('res, err := w.HasNewStream(ctx)',
                        'res, err := w.HasNewStream(ctx)\n reportNativePoll(w.filterChannelID, res.HasNewStream, err)')
    code = code.replace('err := w.Process(ctx, api.MetaData{',
                        'reportNativeState("started", res.User.Username, res.Stream.UUID)\n'
                        'defer reportNativeState("finished", res.User.Username, res.Stream.UUID)\n'
                        'err := w.Process(ctx, api.MetaData{')
    path.write_text(code, encoding='utf-8', newline='\n')
    shutil.copyfile(patch / 'chat_protocol.go', source / 'withny/api/chat_protocol.go')
    shutil.copyfile(patch / 'probe_windows.go', source / 'video/probe/probe_portable_windows.go')
    # Preserve upstream selection/order helpers, replace only the C mux entry.
    path = source / 'video/concat/concat.go'
    code = path.read_text(encoding='utf-8')
    start, end = code.index('func Do('), code.index('func filterFiles(')
    code = code[:start] + code[end:]
    code = code[:code.index('//export goTraceProcessInputStart')]
    code = re.sub(r'/\*.*?\*/\s*import "C"', '', code, count=1, flags=re.S)
    for unused in ('unsafe', 'errors', 'fmt', 'time', 'github.com/mattn/go-pointer', 'github.com/Darkness4/withny-dl/telemetry/metrics',
                   'go.opentelemetry.io/otel', 'go.opentelemetry.io/otel/attribute',
                   'go.opentelemetry.io/otel/codes', 'go.opentelemetry.io/otel/metric', 'go.opentelemetry.io/otel/trace'):
        code = re.sub(r'^.*"' + re.escape(unused) + r'".*\n', '', code, flags=re.M)
    path.write_text(code, encoding='utf-8', newline='\n')
    shutil.copyfile(patch / 'remux_windows.go', source / 'video/concat/remux_portable_windows.go')
    path = source / 'withny/api/comment_ws.go'
    code = path.read_text(encoding='utf-8')
    code = code.replace('realtimeURL *neturl.URL', 'realtimeURL *neturl.URL\n chatToken string\n chatAction string')
    old = '''creds, err := w.credentialsCache.Get()
	if err != nil {
		log.Err(err).Msg("failed to get cached credentials")
	}'''
    if code.count(old) != 2:
        raise ValueError('Unexpected upstream WebSocket implementation')
    code = code.replace(old, '')
    code = code.replace('"Bearer " + creds.AccessToken', '"Bearer " + w.chatToken')
    # Never put a token-bearing handshake URL in logs or mutate shared state.
    code = code.replace('w.realtimeURL.String()', 'w.realtimeURL.Host')
    code = code.replace('w.realtimeURL.RawQuery = q.Encode()', 'dialURL := *w.realtimeURL\n dialURL.RawQuery = q.Encode()')
    code = code.replace('websocket.Dial(ctx, w.realtimeURL.Host,', 'websocket.Dial(ctx, dialURL.String(),')
    path.write_text(code, encoding='utf-8', newline='\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--go', default='go')
    parser.add_argument('--source', type=Path, help='Offline verified v2.0.0 archive')
    parser.add_argument('--output', type=Path, default=ROOT / 'dependency/Withny')
    args = parser.parse_args()
    archive = args.source.read_bytes() if args.source else urllib.request.urlopen(SOURCE, timeout=60).read()
    if hashlib.sha256(archive).hexdigest() != SOURCE_SHA256:
        raise ValueError('Withny source checksum mismatch')
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='withny-build-') as temporary:
        work = Path(temporary)
        (work / 'tmp').mkdir()
        packed = work / 'source.zip'
        packed.write_bytes(archive)
        with zipfile.ZipFile(packed) as z:
            if any(not (work / n).resolve().is_relative_to(work) for n in z.namelist()):
                raise ValueError('Unsafe source archive')
            z.extractall(work)
        source = work / 'withny-dl-2.0.0'
        prepare(source)
        env = dict(os.environ, GOTOOLCHAIN='local', CGO_ENABLED='0', GOOS='windows', GOARCH='amd64', GOPROXY='https://proxy.golang.org',
                   GOTMPDIR=str(work / 'tmp'), GOCACHE=str(work / 'cache'), GOMODCACHE=str(work / 'modules'))
        subprocess.run([args.go, 'build', '-mod=readonly', '-trimpath', '-ldflags=-s -w',
                        '-o', str(work / 'withny-dl.exe'), '.'], cwd=source, env=env, check=True)
        target = args.output / 'withny-dl.exe'
        shutil.copyfile(work / 'withny-dl.exe', target)
        shutil.copyfile(source / 'LICENSE', args.output / 'LICENSE')
        manifest = {'version':'2.0.0-local-chat-1', 'source':SOURCE, 'source_sha256':SOURCE_SHA256,
                    'sha256':hashlib.sha256(target.read_bytes()).hexdigest(), 'license':'MIT',
                    'patches':['scripts/withny_patch/chat.go','scripts/withny_patch/lifecycle.go','scripts/withny_patch/chat_protocol.go','scripts/withny_patch/probe_windows.go',
                               'scripts/withny_patch/remux_windows.go',
                               'scripts/build_withny_dependency.py']}
        (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    print('Withny dependency installed:', args.output)


if __name__ == '__main__':
    main()
