# v2.6.0 WebUI

## 🎉 发布说明

多平台视频下载工具 v2.6.0 WebUI 版已正式发布。本次版本在 v2.5.0 WebUI 基础上新增跨平台直播录制、直播状态展示、TwitCasting 密码表和完成后清理 `.ytdl` 文件，并整合下载归档、独立批量封面和 PO Token Provider 启动改进。主程序文件名升级为 `视频下载工具v2.6.0-GUI.exe`，原有设置、预设、Cookie 和下载记录继续兼容。

## 🤝 本次贡献者

- [猫猫葉汐A_spy（@maomaoyexi）](https://github.com/maomaoyexi) - v2.6.0 YouTube、Bilibili、Twitch、Niconico、NicoChannel、TwitCasting、Twitter/X Spaces 各平台直播入口识别、直播录制策略、断流处理与实时状态展示；任务页「本次 yt-dlp 参数」和「直播录制设置」两个按钮及相关设置功能、Cookie 模板修复、TwitCasting 密码表及失效记录清理、HLS 回退、完成后 `.ytdl` 清理、回归测试与相关文档整理
- [ErgouTree（@ergou10086）](https://github.com/ergou10086) - PR #15 下载归档选择、独立批量封面及 PO Token Provider 启动改进

## ✨ 主要更新

- **跨平台直播录制** - 支持 YouTube、Bilibili、Twitch、Niconico、NicoChannel、TwitCasting 和 Twitter/X Spaces 的直播入口识别、录制和输出目录归档
- **直播录制策略** - 保留本分支的自动、条件追开播、从当前时刻和持久化蹲开播；按平台核验能力，继续支持独立直播引擎、完整性报告和弹幕。
- **断流与实时状态** - 处理直播起点分片不可回溯、断流和重连，显示 LIVE 状态、时长、大小、速度及分片状态
- **直播任务选项** - 保留下载页现有参数输入框、任务列表及直播设置页；本次参数在任务成功提交后清空。
- **Cookie 模板修复** - 保留 Netscape 首行标识，中文说明使用 `#` 注释，并以 UTF-8 无 BOM 编码写入
- **TwitCasting 密码表** - 平台专项设置中的“记住密码”和“保存密码到 XLSX”均默认关闭；前者在本次运行内复用，后者允许明文保存、读取及迁移根目录 twitcasting_passwords.xlsx。
- **TwitCasting HLS 回退** - 多初始化片段由插件并发预取并交给 FFmpeg 封装；异常时按受控路径回退
- **完成后清理 `.ytdl`** - 视频输出确认完成后删除对应的 yt-dlp 恢复元数据，未确认完成或删除失败时保留文件
- **下载归档选择** - PR #15 增加命中归档时重新下载或跳过的选择，20 秒无选择默认跳过，并单独统计跳过数量
- **独立批量封面** - PR #15 增加多链接 JPG 封面下载，沿用鉴权和命名规则，不写入视频下载归档
- **PO Token Provider 启动** - PR #15 改为后台准备本地 Provider，最多等待 60 秒并报告进度，支持停止和失败后重试
- **兼容与回归保护** - 保留 v2.5.0 的 WebUI、代理直连、BgUtils Provider、自定义 yt-dlp 参数、目录迁移和 TwitCasting 并发预取能力

## 📦 下载说明

### 文件清单

| 文件 | 说明 | 必须 |
|------|------|------|
| `video-downloader-v2.6.0-GUI.exe` | 主程序，单文件绿色版 | ✅ |
| `video-downloader-v2.6.0-dependencies.zip` | 通用依赖包（下载工具、Provider 和平台插件） | ✅ |

> v2.6.0 直接作为正式版发布到 GitHub，Release 附件仅提供 Windows EXE 和依赖包；附件名称以 Release 页面为准。

> **依赖包已包含**：`dependency/` 中的 yt-dlp.exe、ffmpeg.exe、ffprobe.exe、deno.exe、fantiadl.exe、withny-dl-windows-amd64.exe 和插件。NicoChannel 还需要单独准备 `nicochannel.zip` 并放入 `dependency/`。

### SHA-256

```text
6A1570FE0B94DF91E7DABC73C3AB24DE339C10879CA267EE943DF746435EADA1  video-downloader-v2.6.0-GUI.exe
86B0C7B241009B3BC59EBAB7F0B3DE05B40EBEFFCB3CF8FC38B1D9769C4CE892  video-downloader-v2.6.0-dependencies.zip
```

## 🚀 快速开始

### 新用户安装
1. 下载 `video-downloader-v2.6.0-GUI.exe` 和 `video-downloader-v2.6.0-dependencies.zip`
2. 新建一个文件夹（如「视频下载工具」），将 `video-downloader-v2.6.0-GUI.exe` 放入其中
3. 解压依赖包，将其中的 `dependency` 文件夹完整放到 exe 同一目录
4. 双击 `video-downloader-v2.6.0-GUI.exe` 运行，自动打开浏览器界面
5. （可选）配置 Cookie 以支持会员、直播或高画质内容

### 老用户升级
1. 关闭正在运行的旧版本程序（点击右上角「✕ 退出」按钮）
2. 下载新版 `video-downloader-v2.6.0-GUI.exe` 替换旧版 exe，并解压 v2.6.0 依赖包
3. 原有 `settings.ini`、`presets.json`、`cookies.txt` 和下载记录继续兼容
4. 原有 `download/`、`dependency/`、Cookie 和密码表无需删除；密码表仅在启用记住密码和 XLSX 保存后读取或迁移
5. 双击运行新版 exe 即可

## 📖 文档

- [使用教程](https://github.com/maomaoyexi/video-downloader/blob/main/docs/%E4%BD%BF%E7%94%A8%E6%95%99%E7%A8%8B.txt)
- [Cookie配置指南](https://github.com/maomaoyexi/video-downloader/blob/main/docs/cookies%E9%97%AE%E9%A2%98%E7%AD%94%E7%96%91.txt)
- [常见问题](https://github.com/maomaoyexi/video-downloader/blob/main/docs/%E5%B8%B8%E8%A7%81%E9%97%AE%E9%A2%98%E7%答疑.txt)
- [错误码说明](https://github.com/maomaoyexi/video-downloader/blob/main/docs/%E9%94%99%E8%AF%AF%E7%A0%81.txt)
- [更新日志](https://github.com/maomaoyexi/video-downloader/blob/main/RELEASE_NOTES.md)

## ⚠️ 注意事项

- v2.6.0 已直接作为正式版发布，Windows EXE 和依赖包以 GitHub Release 页面为准
- 使用过程中不要关闭控制台窗口（它是后端服务器）
- 有下载任务时关闭浏览器页面会提示确认；确认关闭后任务继续在后台运行
- 无下载任务时关闭浏览器页面，程序会在 30 秒后自动退出
- 需要彻底关闭时，请点击界面右上角红色「✕ 退出」按钮
- 登录、会员可见、地区受限或高画质内容可能需要对应平台有效 Cookie；Cookie 只提供登录态，不能绕过付费、地区或 DRM 限制
- Niconico 720P 及以上画质需要配置登录 Cookie
- Bilibili 1080P 及以上画质通常需要配置登录 Cookie
- Fantia 仅支持 `cookies.txt` 文件模式，不支持浏览器提取
- 自动更新要求 Release 提供有效 SHA-256，并会校验文件大小和 Windows EXE 格式；缺少有效摘要时请从 Release 页面手动下载更新
- NicoChannel 直播需在 Firefox 登录以提取令牌
- `twitcasting_passwords.xlsx` 以明文保存密码，除非获得明确授权，请勿发送给其他人
- Withny 直播监控由 `withny-dl` 配置驱动；HAR、配置文件和凭据可能包含登录信息，请妥善保管
- 使用本工具下载内容时请遵守平台规则和当地法律法规

## 💡 推荐配置

- Cookie 模式：`cookies.txt` 文件模式
- 输出格式：MP4
- 音视频模式：合并输出
- 下载限速：推荐设置为 5–10 MB/s。高速或大批量下载可能导致 IP 或账号被限制或封禁，相关后果由使用者自行承担
- 直播录制：根据场景选择「蹲开播」「追开播」或「加入时开录」
- 关闭方式：使用 WebUI 右上角「✕ 退出」按钮

本分支兼容合并说明：保留现有任务队列、直播与弹幕实现；上游旧直播配置仅作导入迁移，不启动第二套等待器。上文贡献记录保留上游 v2.6.0 的原始开发归属，当前界面与行为以此兼容说明为准。
