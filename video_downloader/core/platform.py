"""
core.platform - 纯函数工具：URL 清理、平台检测、直播检测、编码解码、版本号转换。
所有函数无副作用、无 IO、无线程操作。
从 video_downloader.utils 提取。
"""

import re
from urllib.parse import urlparse

from .constants import PLATFORM_INFO, UPDATE_HOSTS


def safe_decode(buf):
    """安全解码字节流，依次尝试 utf-8, gbk, cp936, shift_jis, euc-jp。"""
    if isinstance(buf, str):
        return buf
    for enc in ("utf-8", "gbk", "cp936", "shift_jis", "euc-jp"):
        try:
            return buf.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return buf.decode("utf-8", errors="replace")


def clean_url(url):
    """清理 URL：去除空白、反引号、引号（最多 3 轮）。"""
    if not url:
        return ""
    for _ in range(3):
        old = url
        url = url.strip().strip("`'\"")
        if url == old:
            break
    return url.strip()


def detect_platform(url):
    """根据 URL 的 hostname 匹配平台（YouTube/Twitch/Niconico/Fantia）。"""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return None
    for platform in PLATFORM_INFO:
        for domain in platform["domains"]:
            if host == domain or host.endswith("." + domain):
                return platform["name"]
    return None


def is_live_url(url, platform=None):
    """检测 URL 是否指向直播入口。

    这里只根据 URL 形状做保守判断；最终的开播状态仍由 yt-dlp 提取器
    决定。这样频道页、预告页和已结束直播不会被误认为正在录制。
    """
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = parsed.path.lower().rstrip("/")
    except Exception:
        return False
    platform_name = platform or detect_platform(url)
    if platform_name == "YouTube":
        return (host == "youtube.com" or host.endswith(".youtube.com")) and (
            path == "/live" or path.startswith("/live/") or path.endswith("/live")
        )
    if platform_name == "Twitch":
        if host not in {"twitch.tv", "www.twitch.tv", "m.twitch.tv"}:
            return False
        segments = [segment for segment in path.split("/") if segment]
        return len(segments) == 1 and segments[0] not in {"videos", "clips", "directory"}
    if platform_name == "Niconico":
        # 官方直播入口既有 live.nicovideo.jp，也有带 lv 编号的普通观看页。
        # 普通视频使用 sm/so 编号，因此按 ID 前缀区分可避免 VOD 误判。
        if host in {"live.nicovideo.jp", "live2.nicovideo.jp"}:
            return True
        return (
            host in {"nicovideo.jp", "www.nicovideo.jp", "m.nicovideo.jp"}
            and re.search(r"/watch/lv\d+", path) is not None
        )
    if platform_name == "Bilibili":
        return host == "live.bilibili.com" or host.endswith(".live.bilibili.com")
    if platform_name == "TwitCasting":
        if host != "twitcasting.tv" and not host.endswith(".twitcasting.tv"):
            return False
        segments = [segment for segment in path.split("/") if segment]
        # 单段路径（/主播名）为当前直播；含 movie/twplayer/show/archive 为录播或历史列表。
        return len(segments) == 1 and segments[0] not in {"movie", "twplayer", "show", "archive"}
    if platform_name == "Twitter":
        # Twitter Space: x.com/i/spaces/xxx 或 twitter.com/i/spaces/xxx
        return host in {"x.com", "twitter.com", "www.x.com", "www.twitter.com"} and (
            path.startswith("/i/spaces/")
        )
    if platform_name == "NicoChannel":
        # nicochannel.jp/<channel>/live/sm... 是直播详情页；同一路径下的
        # /video/ 页面是录播，不能仅凭 sm 编号判定为直播。
        segments = [segment for segment in path.split("/") if segment]
        return (
            host == "nicochannel.jp" or host.endswith(".nicochannel.jp")
        ) and len(segments) == 3 and segments[1] == "live" and re.fullmatch(
            r"sm\w+", segments[2]
        ) is not None
    return False


def version_num_to_str(num):
    """10905 → "v1.9.5"。"""
    major = num // 10000
    minor = (num // 100) % 100
    patch = num % 100
    return f"v{major}.{minor}.{patch}"


def parse_version_tag(tag):
    """"v1.9.5" → 10905。解析失败返回 0。"""
    if not tag:
        return 0
    match = re.match(r"v?(\d+)\.(\d+)\.(\d+)", tag.strip())
    if not match:
        return 0
    return int(match.group(1)) * 10000 + int(match.group(2)) * 100 + int(match.group(3))


def is_allowed_update_url(url):
    """检查 URL 是否在允许的更新域名白名单中（HTTPS + UPDATE_HOSTS）。"""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and any(
            host == allowed or host.endswith("." + allowed) for allowed in UPDATE_HOSTS
        )
    except Exception:
        return False


def asset_digest(asset, notes=""):
    """从 GitHub Release asset 中提取 SHA-256 摘要。"""
    digest = str(asset.get("digest") or "").strip().lower()
    match = re.fullmatch(r"sha256:([0-9a-f]{64})", digest)
    if match:
        return match.group(1)
    name = re.escape(str(asset.get("name") or ""))
    if name:
        match = re.search(rf"(?im)\b([0-9a-f]{{64}})\b\s+[*]?{name}\s*$", notes or "")
        if match:
            return match.group(1).lower()
    return None
