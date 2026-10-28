"""Repository boundaries remain enforced even after an accidental forced add."""
from tests.helpers import PROJECT_ROOT
from pathlib import Path
import subprocess

from scripts.check_repository_layout import violations, MAINTAINED_SCRIPTS


def test_tracked_tree_contains_no_local_plans_or_installed_dependencies():
    root = PROJECT_ROOT
    files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode('utf-8').split('\0')
    assert violations(files) == []


def test_guard_rejects_forced_adds_and_accepts_only_license_files():
    invalid = ['temp/plan/example.md', 'Temp/test.txt', 'dependency/tool.exe',
               'dependency/.venv/pyvenv.cfg', 'dependency/package/LICENSE',
               'dependency/runtime.lock.json', 'scripts/one_off_probe.py', 'tests/test_scattered.py']
    assert violations(invalid) == invalid
    assert violations(['dependency/pysubs2.LICENSE', 'dependency/withny-dl.LICENSE',
                       'resource/dependencies/live-python.lock.json',
                       'resource/yt-dlp-plugins/video_downloader/yt_dlp_plugins/extractor/twitcasting.py',
                       'tests/core/test_paths.py', *MAINTAINED_SCRIPTS]) == []


def test_gitignore_uses_default_deny_for_runtime_and_temporary_scripts():
    root = PROJECT_ROOT
    ignored = ['temp/plan/new.md', 'dependency/new-tool.dll', 'dependency/package/LICENSE',
               'dependency/yt-dlp-plugins/plugin.py', 'scripts/temporary-test.py']
    output = subprocess.check_output(['git', 'check-ignore', '--no-index', *ignored], cwd=root)
    assert output.decode('utf-8').splitlines() == ignored
    for allowed in ['dependency/new-library.LICENSE', *MAINTAINED_SCRIPTS]:
        result = subprocess.run(['git', 'check-ignore', '--no-index', allowed], cwd=root,
                                stdout=subprocess.PIPE)
        assert result.returncode == 1, allowed
