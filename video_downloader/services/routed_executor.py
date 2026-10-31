"""Route native content downloads without adding platform logic to yt-dlp."""
from __future__ import annotations

from video_downloader.platforms.fanbox.urls import split_http_url
from video_downloader.platforms.fanbox.errors import FanboxError


def is_fanbox(url):
    try:
        host=split_http_url(url.strip()).hostname.lower()
        return host=='fanbox.cc' or host.endswith('.fanbox.cc')
    except (FanboxError,AttributeError):
        return False


class RoutedDownloadExecutor:
    def __init__(self,video,fanbox):
        self.video,self.fanbox=video,fanbox
        self.active=video

    def __getattr__(self,name):
        return getattr(self.video,name)

    def __setattr__(self,name,value):
        video=self.__dict__.get('video')
        if name not in {'video','fanbox','active'} and video is not None and hasattr(video,name):
            setattr(video,name,value)
        else:
            object.__setattr__(self,name,value)

    @property
    def last_result(self):
        return getattr(self.active,'last_result',None)

    def start_download(self,url,**kwargs):
        self.active=self.fanbox if is_fanbox(url) else self.video
        return self.active.start_download(url,**kwargs)

    def stop_download(self):
        return self.active.stop_download()

    def get_current_ytdlp_command(self):
        return self.active.get_current_ytdlp_command()
