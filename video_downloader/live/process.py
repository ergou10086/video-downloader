"""Hidden isolated consoles allow Ctrl+C even in a PyInstaller GUI process."""
from __future__ import annotations

import base64
import os
import signal
import subprocess


def hidden_options(*, console=False):
    if os.name != "nt":
        return {"start_new_session": True} if console else {}
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = subprocess.SW_HIDE
    return {"startupinfo": info,
            "creationflags": subprocess.CREATE_NEW_CONSOLE if console else subprocess.CREATE_NO_WINDOW}


def spawn(command, *, cwd, env=None):
    return subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            **hidden_options(console=True))


def interrupt(process):
    if process.poll() is not None:
        return
    if os.name != "nt":
        os.killpg(process.pid, signal.SIGINT)
        return
    # Attaching the GUI process itself would race other concurrent recordings.
    # A short-lived hidden helper attaches to this child's dedicated console.
    script = '''Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class LiveConsole {
 [DllImport("kernel32.dll")] public static extern bool FreeConsole();
 [DllImport("kernel32.dll")] public static extern bool AttachConsole(uint id);
 [DllImport("kernel32.dll")] public static extern bool SetConsoleCtrlHandler(IntPtr p, bool add);
 [DllImport("kernel32.dll")] public static extern bool GenerateConsoleCtrlEvent(uint kind, uint group);
}
'@
[LiveConsole]::FreeConsole() | Out-Null
if (-not [LiveConsole]::AttachConsole(PID_VALUE)) { exit 2 }
[LiveConsole]::SetConsoleCtrlHandler([IntPtr]::Zero, $true) | Out-Null
if (-not [LiveConsole]::GenerateConsoleCtrlEvent(0, 0)) { exit 3 }
Start-Sleep -Milliseconds 200
[LiveConsole]::FreeConsole() | Out-Null
'''.replace("PID_VALUE", str(int(process.pid)))
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    powershell = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    completed = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                               capture_output=True, timeout=8, **hidden_options())
    if completed.returncode:
        raise OSError("无法向独立录制控制台发送 Ctrl+C")


def stop(process, force_kill, *, timeout=10):
    if process.poll() is not None:
        return True
    try:
        interrupt(process)
        process.wait(timeout=timeout)
        return True
    except (OSError, subprocess.TimeoutExpired):
        force_kill(process)
        return False
