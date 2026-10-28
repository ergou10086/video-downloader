"""Reject local plans, installed dependencies and ad-hoc scripts in Git's index."""
from __future__ import annotations

import argparse
from pathlib import PurePosixPath
import subprocess
import sys


MAINTAINED_SCRIPTS = frozenset({
    'scripts/install_bililive.py', 'scripts/install_live_dependencies.py',
    'scripts/build_withny_dependency.py', 'scripts/check_live_release.py',
    'scripts/check_repository_layout.py',
    'scripts/withny_patch/chat.go', 'scripts/withny_patch/chat_protocol.go',
    'scripts/withny_patch/lifecycle.go', 'scripts/withny_patch/probe_windows.go',
    'scripts/withny_patch/remux_windows.go',
})


def violations(paths):
    invalid = []
    for path in paths:
        normalized = path.replace('\\', '/')
        parts = PurePosixPath(normalized).parts
        if not parts:
            continue
        top = parts[0].casefold()
        if (top == 'temp'
                or (top == 'dependency' and not (
                    len(parts) == 2 and parts[-1].endswith('.LICENSE')))
                or (top == 'scripts' and normalized not in MAINTAINED_SCRIPTS)):
            invalid.append(path)
    return invalid


def check(*, staged=False):
    command = (['git', 'diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z']
               if staged else ['git', 'ls-files', '-z'])
    result = subprocess.run(command, check=True, stdout=subprocess.PIPE)
    paths = result.stdout.decode('utf-8', errors='surrogateescape').split('\0')
    invalid = violations(paths)
    if invalid:
        print('拒绝提交：temp 仅留本地，dependency 仅保留根目录 *.LICENSE，'
              'scripts 仅保留明确维护的脚本。', file=sys.stderr)
        for path in invalid:
            print(f'  {path}', file=sys.stderr)
        print('使用 git rm --cached 取消跟踪；不要用 git add -f 绕过目录规则。', file=sys.stderr)
    return 1 if invalid else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged', action='store_true', help='Check files added or modified by this commit')
    raise SystemExit(check(staged=parser.parse_args().staged))
