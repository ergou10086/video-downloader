"""Shared web test factories and doubles."""
from video_downloader.state.app_state import AppState
from video_downloader.web.handler import HttpHandlerDependencies


class FakeDownloadManager:
    def snapshot(self):
        return {"running": False, "phase": "idle", "generation": 1}


class FakeUpdater:
    def is_checking(self):
        return False

    def start_check_thread(self, silent):
        pass

    def snapshot(self):
        return {"checking": False}

    def do_update(self):
        return {"ok": True}


def make_dependencies(exit_event):
    app_state = AppState()
    app_state.replace_config({"output_dir": "downloads"})
    value = lambda: {"ok": True}
    named_value = lambda name: {"name": name}
    return HttpHandlerDependencies(
        session_token="test-token",
        version="1.9.5",
        default_config={"output_dir": "downloads"},
        app_state=app_state,
        download_manager=FakeDownloadManager(),
        updater=FakeUpdater(),
        render_html_page=lambda token: f"token={token}".encode(),
        serve_static_file=lambda path: (None, None),
        check_deps=lambda: {"yt-dlp": True},
        load_presets=lambda: {"default": {}},
        load_history=lambda: [{"url": "example"}],
        cancel_idle_timer=lambda: None,
        start_idle_timer=lambda: None,
        start_download=lambda url, bili_parts=None, tc_password=None, custom_args=None, live_mode=None: {
            "url": url, **({"custom_args": custom_args} if custom_args else {}),
            **({"live_mode": live_mode} if live_mode else {}),
        },
        list_live_watch_jobs=lambda: [],
        cancel_live_watch=lambda job_id: {"ok": True, "id": job_id},
        inspect_live_url=lambda url, live_mode=None: {"is_live_target": False, "url": url},
        live_capabilities=lambda: {},
        list_tasks=lambda: [],
        cancel_task=lambda task_id: {"ok": True, "id": task_id},
        clear_tasks=lambda: {"ok": True, "removed": 0},
        start_withny_archive=lambda: {"ok": True, "kind": "withny-archive"},
        start_withny_live=lambda: {"ok": True, "kind": "withny-live"},
        batch_txt_download=lambda bili_parts_map=None, custom_args=None: {
            "custom_args": custom_args,
        },
        start_urls_download=lambda urls, custom_args=None: {
            "urls": urls, **({"custom_args": custom_args} if custom_args else {}),
        },
        download_subtitles=lambda *args: {"args": list(args)},
        download_covers=lambda *args: {"args": list(args)},
        stop_download=value,
        get_current_command=lambda: {"ok": True, "command": "yt-dlp https://example.com"},
        submit_password=lambda url, password: {"ok": True},
        submit_task_password=lambda task_id, url, password, **kwargs: {"ok": True, "task_id": task_id, **kwargs},
        submit_archive_choice=lambda request_id, redownload: {"request_id": request_id, "redownload": redownload},
        submit_task_archive_choice=lambda task_id, request_id, redownload: {"ok": True, "task_id": task_id},
        fetch_bili_playlist=lambda url: {"parts": [], "total": 0},
        save_preset=named_value,
        load_preset=named_value,
        delete_preset=named_value,
        clear_history=value,
        find_cover=lambda path: (b"JPEGDATA", "image/jpeg") if path == "known" else (None, None),
        validate_config=lambda data, current: (data, []),
        save_config=lambda: None,
        handle_tool_action=named_value,
        browse_folder=value,
        update_ytdlp=value,
        clean_temp=value,
        gen_url_template=value,
        wav_to_mp3=lambda *args: {"args": args},
        audio_loudnorm=lambda *args, **kwargs: {"args": args},
        audio_volume=lambda *args, **kwargs: {"args": args},
        request_exit=exit_event.set,
    )
