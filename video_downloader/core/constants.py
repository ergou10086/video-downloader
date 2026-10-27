VERSION = "v2.6.0 WebUI"
VERSION_NUM = 20600

GITHUB_OWNER = "maomaoyexi"
GITHUB_REPO = "video-downloader"
EXE_NAME = "视频下载工具v2.6.0-GUI.exe"
UPDATE_HOSTS = {
    "github.com",
    "api.github.com",
    "objects.githubusercontent.com",
}
MAX_UPDATE_SIZE = 512 * 1024 * 1024
IDLE_TIMEOUT = 30

LEGACY_ALL_SUBTITLE_LANGS = "all,-live_chat"
RECOMMENDED_SUBTITLE_LANGS = "ja.*,zh.*,zh-Hans,zh-Hant,en.*,ko.*"
DEFAULT_SUBTITLE_LANGS = "zh.*,zh-Hans,zh-Hant"

DEFAULT_CONFIG = {
    "PLATFORM": "YouTube",
    "RESOLUTION": "best",
    "CODEC": "best",
    "AUDIO_QUALITY": "best",
    "OUTPUT_FORMAT": "mp4",
    "MERGE_MODE": 1,
    "AUDIO_MODE": "0",
    "AUDIO_FORMAT": "mp3",
    "THREADS": 4,
    "SPEED_LIMIT": 0,
    "PROXY_ENABLED": 0,
    "PROXY_TYPE": "http",
    "PROXY_ADDR": "127.0.0.1",
    "PROXY_PORT": "7890",
    "USE_COOKIES": 1,
    "COOKIE_MODE": 1,
    "BROWSER_NAME": "chrome",
    "BROWSER_PROFILE": "Default",
    "HWACCEL": "cpu",
    "EMBED_META": 1,
    "DOWNLOAD_THUMB": 1,
    "DOWNLOAD_SUBTITLES": 0,
    "SUBTITLE_TYPE": "all",
    "SUBTITLE_LANGS": DEFAULT_SUBTITLE_LANGS,
    "WIN_FILENAMES": 1,
    "STRICT_FILENAME": 0,
    "NICO_COMMENTS": 0,
    "NICO_RECODE": 0,
    "LIVE_STREAM_METHOD": "yt-dlp",
    # 直播录制策略：wait=蹲开播，from_start=追开播，current=加入时开录。
    # 默认值保持历史行为，避免升级后正在使用的链接改变录制起点。
    "LIVE_RECORD_MODE": "from_start",
    # 蹲开播模式的状态探测间隔（秒）。
    "LIVE_WATCH_INTERVAL": 30,
    "LIVE_DOWNLOAD_TIMEOUT": 0,
    "ENABLE_LOG": 1,
    "MP3_BITRATE": 320,
    "DEL_WAV_AFTER_CONVERT": 0,
    "BILI_MULTIP_POLICY": "all",
    "YOUTUBE_PO_TOKEN_ENABLED": 0,
    "YTDLP_DEFAULT_ARGS": "",
}

RESOLUTION_OPTIONS = ["best", "2160", "1440", "1080", "720", "480", "360"]
CODEC_OPTIONS = ["best", "h264", "av1", "vp9"]
AUDIO_OPTIONS = ["best", "192", "128"]
FORMAT_OPTIONS = ["mp4", "mkv", "webm"]
AUDIO_MODE_OPTIONS = ["0", "1", "2", "3"]
AUDIO_FORMAT_OPTIONS = ["m4a", "mp3", "wav"]
HWACCEL_OPTIONS = ["cpu", "h264_nvenc", "h264_qsv", "h264_amf"]
BROWSER_OPTIONS = ["chrome", "edge", "firefox", "brave", "opera"]
PROXY_TYPE_OPTIONS = ["http", "socks5"]
MP3_BITRATE_OPTIONS = [128, 192, 256, 320]
BILI_POLICY_OPTIONS = ["all", "select"]
LIVE_STREAM_METHOD_OPTIONS = ["yt-dlp"]
LIVE_RECORD_MODE_OPTIONS = ["wait", "from_start", "current"]
SUBTITLE_TYPE_OPTIONS = ["all", "manual", "auto"]

PLATFORM_INFO = [
    {"name": "YouTube", "color": "#FF0000", "domains": ["youtube.com", "youtu.be"]},
    {"name": "Bilibili", "color": "#FB7299", "domains": ["bilibili.com", "b23.tv"]},
    {"name": "Twitch", "color": "#9146FF", "domains": ["twitch.tv"]},
    {"name": "Niconico", "color": "#00A0D1", "domains": ["nicovideo.jp", "nico.ms"]},
    {"name": "Fantia", "color": "#E6399B", "domains": ["fantia.jp"]},
    {"name": "TwitCasting", "color": "#4B4B4D", "domains": ["twitcasting.tv"]},
    {"name": "Twitter", "color": "#1DA1F2", "domains": ["twitter.com", "x.com", "t.co"]},
    {"name": "NicoChannel", "color": "#FF6B35", "domains": ["nicochannel.jp"]},
]
