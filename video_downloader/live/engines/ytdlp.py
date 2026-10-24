from __future__ import annotations


class YtDlpEngine:
    name = "yt-dlp"

    def __init__(self, command):
        self.original = list(command)

    def command(self, directory):
        # Isolate retries; never overwrite an earlier attempt or share archive state.
        pairs = {"-o", "--output", "-P", "--paths", "--download-archive"}
        result, i = [], 0
        while i < len(self.original):
            value = self.original[i]
            if value in {"--skip-download", "--simulate", "-s"}:
                i += 1
                continue
            if value in pairs:
                i += 2
                continue
            if any(value.startswith(option + "=") for option in pairs):
                i += 1
                continue
            result.append(value)
            i += 1
        # JSON progress is independent of localization and title/path quoting.
        result += ["--no-simulate", "--newline",
                   "-P", str(directory), "-o", "recording.%(ext)s",
                   "--print", "before_dl:LIVE_META:%(.{id,title,is_live,live_status,tbr,vcodec,acodec})j",
                   "--print", "after_move:LIVE_FILE:%(filepath)j"]
        return result

    def stop_recording(self):
        return

    def close(self):
        return
