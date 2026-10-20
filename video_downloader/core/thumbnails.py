"""封面下载的结果判定：从 yt-dlp 输出中还原最终落盘的缩略图路径。"""

import re


_THUMBNAIL_WRITTEN = re.compile(
    r"Writing video thumbnail(?: \d+)? to:\s*(.+?)\s*$",
    re.MULTILINE,
)
_THUMBNAIL_CONVERTED = re.compile(
    r'Converting thumbnail "(.+?)" to (\w+)',
    re.MULTILINE,
)
_THUMBNAIL_CACHED = re.compile(
    r"^\[download\] (.+?\.(?:jpe?g|png|webp|gif|avif)) has already been downloaded",
    re.MULTILINE | re.IGNORECASE,
)


def thumbnail_written_path(output):
    """返回 yt-dlp 最终写出的缩略图路径；未写出时返回空字符串。

    ``--convert-thumbnails`` 会在转换完成后删除原始文件，因此磁盘上留下的是转换
    结果，报告给用户的应当是转换后的目标路径而不是源文件名。
    """
    output = output or ""
    converted = _THUMBNAIL_CONVERTED.search(output)
    if converted:
        source, target_ext = converted.groups()
        base = source.rsplit(".", 1)[0]
        return f"{base}.{target_ext}" if base else source
    cached = _THUMBNAIL_CACHED.search(output)
    if cached:
        return cached.group(1)
    written = _THUMBNAIL_WRITTEN.search(output)
    return written.group(1) if written else ""


def classify_thumbnail_result(returncode, output):
    """把一次封面下载的结果归类为 success / missing / error。"""
    if returncode != 0:
        return "error"
    if thumbnail_written_path(output):
        return "success"
    return "missing"
