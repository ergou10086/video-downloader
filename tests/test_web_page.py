import os
import re
import unittest

from video_downloader.web.rendering import SESSION_TOKEN_PLACEHOLDER, render_html_page, serve_static_file


def _skip_if_frozen():
    import sys
    if getattr(sys, "frozen", False):
        raise unittest.SkipTest("PyInstaller frozen mode")


class WebPageTests(unittest.TestCase):
    def test_render_replaces_session_token(self):
        token = "test-session-token"
        rendered = render_html_page(token)
        self.assertIsInstance(rendered, bytes)
        text = rendered.decode("utf-8")
        # Token is injected via window.SESSION_TOKEN inline script
        self.assertIn(f'window.SESSION_TOKEN = "{token}";', text)
        self.assertNotIn(SESSION_TOKEN_PLACEHOLDER, text)

    def test_template_keeps_expected_structure(self):
        _skip_if_frozen()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        template_path = os.path.join(base, "resource", "templates", "index.html")
        self.assertTrue(os.path.isfile(template_path), f"Template missing: {template_path}")
        with open(template_path, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn("</html>", html)
        # HTML 结构检查
        self.assertIn("page-download", html)
        self.assertIn("page-settings", html)
        self.assertIn("page-history", html)
        self.assertIn("page-tools", html)
        self.assertIn("page-help", html)
        self.assertIn("page-about", html)
        self.assertIn('class="app"', html)
        self.assertIn('class="rail" aria-label="应用侧栏"', html)
        self.assertIn('class="main"', html)
        self.assertIn('aria-label="主导航"', html)
        self.assertIn("ErgouTree", html)
        self.assertIn("@ergou10086", html)
        self.assertIn("https://github.com/ergou10086", html)
        self.assertIn("DarkKandaoMaster", html)
        self.assertIn("强壮的砍刀", html)
        self.assertIn("https://github.com/DarkKandaoMaster", html)
        self.assertIn("https://github.com/maomaoyexi", html)
        # 自建单色墨系设计系统：base.css 定义令牌与组件，dark.css 只覆盖变量
        self.assertIn("/static/css/base.css", html)
        self.assertIn("/static/css/dark.css", html)
        self.assertIn("/static/css/responsive.css", html)
        self.assertIn("/static/css/animations.css", html)
        self.assertIn("/static/js/app.js", html)
        self.assertNotIn("tabler.min.css", html)
        self.assertNotIn("tabler.min.js", html)
        # 图标为内联 SVG sprite，不再有独立的 icons.js
        self.assertIn('<symbol id="i-download"', html)
        self.assertNotIn("/static/js/icons.js", html)
        # 下载历史的列表 / 网格视图切换
        self.assertIn('id="viewList"', html)
        self.assertIn('id="viewGrid"', html)
        # Token 占位符
        self.assertIn("__SESSION_TOKEN__", html)
        self.assertIn('id="btnWithnyLive"', html)
        self.assertIn('id="nicochannelHint"', html)
        self.assertIn('id="btnCopyCommand"', html)
        self.assertIn('id="speedText"', html)
        self.assertIn('id="sw_subtitles"', html)
        self.assertIn('id="s_subtitle_type"', html)
        self.assertIn('id="subtitleDownloadDialog"', html)
        self.assertIn('id="btnSubtitleDownload"', html)
        self.assertIn('id="coverDownloadDialog"', html)
        self.assertIn('id="btnCoverDownload"', html)
        self.assertIn('data-panel="coverDownloadDialog"', html)
        self.assertIn('id="archiveChoiceOverlay"', html)
        self.assertIn('id="btnArchiveRedownload"', html)
        self.assertIn('id="btnArchiveSkip"', html)
        self.assertIn('id="statSkip"', html)
        self.assertIn('id="task_ytdlp_args"', html)
        self.assertIn('id="s_ytdlp_default_args"', html)
        self.assertIn('id="sw_youtube_po_token"', html)
        self.assertIn('id="s_live_record_mode"', html)
        self.assertIn('id="s_live_watch_interval"', html)
        self.assertIn('id="btnLiveRecordSettings"', html)
        self.assertIn('id="liveRecordOverlay"', html)
        self.assertIn('id="btnTaskYtdlpArgs"', html)
        self.assertIn('id="taskYtdlpArgsOverlay"', html)
        self.assertIn('onclick="showTaskYtdlpArgs()"', html)
        self.assertIn('onclick="showLiveRecordSettings()"', html)
        self.assertIn('value="wait"', html)
        self.assertIn('value="from_start"', html)
        self.assertIn('value="current"', html)
        self.assertIn('蹲开播', html)
        self.assertIn('追开播', html)
        self.assertIn('加入时开录', html)

        # 直播录制模式属于提交任务时的选项，控件应位于下载任务页，
        # 避免为了修改录制行为再切换到下载设置页。
        download_html = html.split('<div class="page active" id="page-download">', 1)[1].split(
            '<div class="page" id="page-history">', 1
        )[0]
        settings_html = html.split('<div class="page" id="page-settings">', 1)[1].split(
            '<div class="page" id="page-tools">', 1
        )[0]
        self.assertIn('id="s_live_record_mode"', download_html)
        self.assertIn('id="s_live_watch_interval"', download_html)
        self.assertNotIn('id="s_live_record_mode"', settings_html)
        self.assertNotIn('id="s_live_watch_interval"', settings_html)

        # 两个任务选项共用一排按钮，参数输入只在对应的小窗口中显示。
        task_actions_html = download_html.split('<div class="task-option-actions">', 1)[1].split('</div>', 1)[0]
        self.assertIn('id="btnLiveRecordSettings"', task_actions_html)
        self.assertIn('id="btnTaskYtdlpArgs"', task_actions_html)
        self.assertNotIn('id="task_ytdlp_args"', task_actions_html)
        args_dialog_html = download_html.split('id="taskYtdlpArgsOverlay"', 1)[1].split('<!-- ====== 直播录制设置', 1)[0]
        self.assertIn('class="dlg task-args-dlg"', args_dialog_html)
        self.assertIn('role="dialog" aria-modal="true"', args_dialog_html)
        self.assertIn('id="task_ytdlp_args"', args_dialog_html)
        self.assertEqual(1, html.count('id="task_ytdlp_args"'))

    def test_reset_config_uses_post(self):
        _skip_if_frozen()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        js_path = os.path.join(base, "resource", "static", "js", "app.js")
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()
        # reset-config 使用 POST 在 JS 中
        self.assertIn("api('/api/reset-config', {method:'POST'})", js)
        self.assertIn("api('/api/start-withny-live'", js)

    def test_live_record_mode_is_loaded_and_saved(self):
        """直播三种录制模式必须经过下载任务页的配置读写。"""
        _skip_if_frozen()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base, "resource", "static", "js", "app.js"), "r", encoding="utf-8") as f:
            js = f.read()
        apply_js = js[js.index("function applyConfig"):js.index("/** 根据值设置开关")]
        collect_js = js[js.index("function collectCfg"):js.index("/** 保存当前设置")]
        self.assertIn("s.LIVE_RECORD_MODE", apply_js)
        self.assertIn("LIVE_RECORD_MODE: $('s_live_record_mode').value", collect_js)
        self.assertIn("s.LIVE_WATCH_INTERVAL", apply_js)
        self.assertIn("LIVE_WATCH_INTERVAL: parseInt($('s_live_watch_interval').value, 10)", collect_js)
        self.assertIn("function onLiveRecordModeChange()", js)
        self.assertIn("function showLiveRecordSettings()", js)
        self.assertIn("function hideLiveRecordSettings()", js)
        self.assertIn("function updateLiveRecordModeUI()", js)

    def test_settings_javascript_only_references_existing_form_controls(self):
        """设置加载/保存不能读取模板中不存在的控件。"""
        _skip_if_frozen()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base, "resource", "templates", "index.html"), "r", encoding="utf-8") as f:
            html = f.read()
        with open(os.path.join(base, "resource", "static", "js", "app.js"), "r", encoding="utf-8") as f:
            js = f.read()

        settings_js = js[js.index("function applyConfig"):js.index("async function saveSettings()")]
        referenced_ids = set(
            re.findall(r"(?:\$|isOn|setSwitch)\('([^']+)'", settings_js)
        )
        template_ids = set(re.findall(r'id="([^"]+)"', html))

        self.assertEqual(set(), referenced_ids - template_ids)

    def test_only_light_dark_theme_remains(self):
        """配色切换（Everforest ↔ 中性）已整套删除，只剩明暗两态。"""
        _skip_if_frozen()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base, "resource", "templates", "index.html"), "r", encoding="utf-8") as f:
            html = f.read()
        with open(os.path.join(base, "resource", "static", "js", "theme.js"), "r", encoding="utf-8") as f:
            js = f.read()
        with open(os.path.join(base, "resource", "static", "css", "dark.css"), "r", encoding="utf-8") as f:
            css = f.read()
        self.assertNotIn("data-palette", html)
        self.assertNotIn("paletteToggle", html)
        self.assertNotIn("video-dl-palette", js)
        self.assertNotIn("togglePalette", js)
        self.assertIn("video-dl-theme", js)
        self.assertIn("toggleTheme", js)
        self.assertIn('theme-toggle', html)
        # 深色只覆盖 :root 里的颜色变量
        self.assertIn('[data-theme="dark"]{', css)

    def test_app_js_has_api_endpoints(self):
        _skip_if_frozen()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        js_path = os.path.join(base, "resource", "static", "js", "app.js")
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()
        # 关键 API 端点仍在 JS 中
        self.assertIn("/api/events?token=", js)
        self.assertIn("/api/start", js)
        self.assertIn("/api/start-withny-archive", js)
        self.assertIn("/api/current-command", js)
        self.assertIn("/api/download-subtitles", js)
        self.assertIn("/api/download-covers", js)
        self.assertIn("/api/archive-choice", js)
        self.assertIn("[LEGACY_ALL_SUBTITLE_LANGS, '全部字幕']", js)
        self.assertIn("[DEFAULT_SUBTITLE_LANGS, '中文（默认）']", js)
        self.assertIn('{name:"Withny",color:"#22C55E"}', js)
        self.assertIn("/api/do-update", js)

    def test_archive_choice_and_task_state_survive_sse_reconnect(self):
        """PR task-state additions must coexist with the live controls and modal args."""
        _skip_if_frozen()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base, "resource", "static", "js", "app.js"), "r", encoding="utf-8") as f:
            js = f.read()
        self.assertIn("downloadGeneration = readyData.generation", js)
        self.assertIn("if(readyData.archive_prompt) showArchiveChoice(readyData.archive_prompt);", js)
        self.assertIn("evt.type === 'archive_choice_required'", js)
        self.assertIn("evt.type === 'archive_choice_closed'", js)
        self.assertIn("data.generation !== downloadGeneration", js)
        self.assertIn("ok + fail + skipped", js)
        self.assertIn("updateTaskYtdlpArgsUI();", js)
        start_handlers = js[js.index("async function doStartDl("):js.index("async function stopDl(")]
        self.assertNotIn("markStarted(", start_handlers)
        self.assertIn("clearStartedTaskArgs(taskArgs);", start_handlers)

    def test_bilibili_part_title_uses_safe_dom_properties(self):
        _skip_if_frozen()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        js_path = os.path.join(base, "resource", "static", "js", "app.js")
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()
        self.assertIn("title.title = String(p.title ?? '');", js)
        self.assertIn("title.textContent = String(p.title ?? '');", js)
        self.assertNotIn("list.innerHTML = parts.map", js)

    def test_serve_static_file_css(self):
        content, mime = serve_static_file("/static/css/base.css")
        self.assertIsNotNone(content)
        self.assertIn("text/css", mime)
        self.assertIn(b":root", content)

    def test_animation_styles_keep_motion_accessible(self):
        content, mime = serve_static_file("/static/css/animations.css")
        self.assertIsNotNone(content)
        self.assertIn("text/css", mime)
        self.assertIn(b"@keyframes page-in", content)
        self.assertIn(b"prefers-reduced-motion:reduce", content)

    def test_serve_static_file_js(self):
        content, mime = serve_static_file("/static/js/app.js")
        self.assertIsNotNone(content)
        self.assertIn("javascript", mime)

    def test_serve_static_file_not_found(self):
        content, mime = serve_static_file("/static/nonexistent.file")
        self.assertIsNone(content)
        self.assertIsNone(mime)

    def test_serve_static_file_path_traversal_blocked(self):
        content, mime = serve_static_file("/static/../../../etc/passwd")
        self.assertIsNone(content)
        self.assertIsNone(mime)

    def test_serve_static_file_non_static_prefix_blocked(self):
        content, mime = serve_static_file("/api/config")
        self.assertIsNone(content)
        self.assertIsNone(mime)

    def test_fallback_html(self):
        from video_downloader.web.rendering import _fallback_html
        html = _fallback_html("fallback-token")
        self.assertIsInstance(html, bytes)
        text = html.decode("utf-8")
        self.assertIn("fallback-token", text)


if __name__ == "__main__":
    unittest.main()
