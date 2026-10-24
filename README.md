# 多平台视频下载工具 v2.5.0 WebUI
支持 YouTube / Bilibili / Twitch / Niconico / NicoChannel / Fantia / TwitCasting / Twitter 八个平台的视频/直播下载，并提供 Withny 已授权历史存档 HAR 保存及直播监控录制功能。Release 的 EXE 绿色版无需安装 Python；源码运行版使用 Python 3 启动。

![Version](https://img.shields.io/badge/version-v2.5.0%20WebUI-purple)
![Platform](https://img.shields.io/badge/platform-Windows-blue)
![License](https://img.shields.io/badge/license-MIT-green)

> v2.5.0 由 [DarkKandaoMaster](https://github.com/DarkKandaoMaster) 重构 WebUI 视觉与交互体系；[ErgouTree (@ergou10086)](https://github.com/ergou10086) 完善设置控件、TwitCasting 下载与进度、YouTube PO Token Provider 集成及运行目录收拢。本版同时支持自定义 yt-dlp 参数，并修复关闭代理后仍可能继承系统代理的问题。

## ✨ 功能特性

- 🌐 **全新WebUI界面** - 内置HTTP服务器，自动打开浏览器，深色主题，响应式设计
- 🎬 **八平台支持** - YouTube、Bilibili、Twitch、Niconico、NicoChannel、Fantia、TwitCasting、Twitter，自动识别平台
- 📦 **Withny 支持** - 从 HAR 保存已授权历史存档，也可通过 withny-dl 配置监控和录制直播
- 📺 **Bilibili 支持** - 支持普通视频、直播和多 P 分集选择
- 🎮 **直播录制** - 支持直播模式选择（自动/追开播/从当前时刻/蹲开播）；开始前按平台检查直播状态并提示开播时间/已开播时长，蹲开播会在开播后自动开始录制
- 🗂️ **任务模式** - 一次点击创建一个任务；支持 1–8 个任务并行、直播优先/下载优先排序、任务级进度/取消/日志详情
- 💾 **配置预设** - 保存常用设置组合，一键切换
- 📜 **下载历史** - 自动记录每次下载，最多500条
- 🔄 **断点续传** - 默认启用，网络中断后自动续传
- 📊 **批量下载** - 支持从TXT文件批量导入链接
- ⌨️ **命令行模式** - 支持直接传入 URL 或通过 `--batch` 批量下载
- 🧾 **多行链接** - 下载页可直接粘贴多行 URL，按顺序加入批量队列
- 🖼️ **封面处理** - 下载独立 JPG 封面，并在兼容格式中自动嵌入
- **字幕下载** - 支持普通下载附带字幕及独立多链接字幕下载，默认关闭，开启后默认中文
- 🎵 **MP3 音频下载** - 支持在下载视频时单独保存 MP3 音频
- 🍪 **Cookie支持** - 支持cookies.txt文件模式
- 🛡️ **YouTube PO Token** - 可选自动启动本地 BgUtils Provider，缓解部分 GVS/PO Token 相关 403
- 🧩 **自定义 yt-dlp 参数** - 支持仅本次任务参数与每次下载默认参数
- ⚡ **硬件加速** - 支持NVIDIA NVENC、Intel QSV、AMD AMF
- 🔄 **自动更新** - 启动后通过 GitHub Releases 检查新版本，校验通过后自动更新替换
- 🧰 **工具箱** - 内置WAV转MP3、yt-dlp更新、临时文件清理等8个工具
- 🛡️ **进程管理** - 关闭网页30秒后自动退出，无残留进程

## 🚀 快速开始

1. 从 [Releases](https://github.com/maomaoyexi/video-downloader/releases) 下载最新版本（两个文件都要下载）：
   - `video-downloader-v2.5.0-GUI.exe` - 主程序
   - `video-downloader-v2.5.0-dependencies.zip` - 通用依赖包（包含下载工具和帮助文档）
2. 新建一个文件夹（如「视频下载工具」），将 `video-downloader-v2.5.0-GUI.exe` 放入其中
3. 解压依赖包，将其中的 `dependency` 文件夹完整放到主程序同一目录
4. 双击 `video-downloader-v2.5.0-GUI.exe` 运行，自动打开浏览器界面

> 💡 **提示**：依赖包的 `dependency/` 包含 yt-dlp.exe、ffmpeg.exe、ffprobe.exe、deno.exe、fantiadl.exe、withny-dl-windows-amd64.exe 和 `yt-dlp-plugins` 目录。NicoChannel 还需要单独准备 `nicochannel.zip` 并放入 `dependency/`。首次运行会自动生成 `download/`、归档及日志目录。

若要启用 YouTube PO Token，请同时保留 `dependency/yt-dlp-plugins/bgutil-ytdlp-pot-provider.zip` 和 `dependency/bgutil-ytdlp-pot-provider/server`（含已安装的 `node_modules`）。在「设置 → 平台专项」打开 YouTube PO Token 后，程序会在 YouTube 任务开始前自动启动 Provider，并在退出工具时关闭它；无需另开 CMD。Provider 可能缓解部分 403，但不能保证绕过所有风控或登录校验。

Provider 首次启动在后台准备，界面会显示准备状态，日志每 5 秒报告等待进度，最多等待 60 秒；此时可点击「停止」。健康检查通过后才运行 yt-dlp，后续任务会复用已就绪的 Provider。启动失败会在日志中保留 Deno 错误并恢复可重试状态。启动过程仅使用已安装的依赖，不会在线安装包或等待控制台确认；若日志提示依赖缺失，请重新准备完整的 Provider 依赖包。

命中下载归档时会弹窗询问是否重新下载，默认「跳过」，20 秒未选择后自动跳过并继续批量队列。归档只代表曾经记录过该视频，不能证明当前文件完整；跳过会单独计数，不再显示为下载成功。选择重下只清除本次命中的归档记录，保留其他记录，并沿用当前输出模板覆盖同名视频及配套音频，不生成编号副本。重下失败不会重新写入成功归档；如果修改了输出目录、文件名模板或格式，新文件会按新设置保存。

TwitCasting 录播会自动加载随项目提供的 `dependency/yt-dlp-plugins/video_downloader` 插件，在首次下载前检查 HLS 清单。普通清单使用 yt-dlp 原生下载；多初始化段清单按设置中的下载线程数（1–32）并发下载，再由 FFmpeg 本地封装，无需先失败重试或另装下载器。多初始化段缓存会在中断重试时校验分片长度与 SHA-256 再续传，播放地址失效时先复用当前登录状态刷新一次；网络失败保留完整分片，不会悄悄改为串行重下。字节范围等特殊清单才进入 FFmpeg 兼容路径。若插件缺失，仍保留原有的错误检测及 FFmpeg 重试兜底。原因分析和真实录播验证见 [TwitCasting 下载分析与验证](docs/TwitCasting下载分析与验证.md)。

### 源码运行版

保持 `视频下载工具v2.5.0-GUI.py`、`video_downloader/` 与 `dependency/` 位于同一目录，安装 Python 3 后运行：

```powershell
python ".\视频下载工具v2.5.0-GUI.py"
```

源码运行版不会用下载到的 EXE 自动覆盖 Python 源码；升级源码时请手动替换主脚本与 `video_downloader/` 目录。

## 📖 使用说明

### 单视频下载
1. 在「下载」页面粘贴视频链接
2. 点击「开始下载」
3. 实时查看进度、速度、剩余时间

### 任务模式
在「设置 → 任务与并发」启用任务模式后，每次点击「开始」会创建一个任务，显示在链接输入框下方的任务列表。多行链接和 TXT 批量分别归入一次点击对应的任务，Withny 专用下载/监控也进入队列。任务行按进度填充颜色，点击展开可查看每条链接的状态、历史和日志，并单独取消父任务；密码与归档确认直接在对应详情内处理，刷新页面也能恢复待确认内容。

可设置最大并行任务数（1 为串行）、任务排序（直播录制优先/下载任务优先/不排序）和任务内直播并行数（默认 1，任务内全部链接串行）。开启内部并行后直播可重叠，普通下载最多一路，同任务总链接并行数不超过该设置。排序只影响排队任务，不中断运行中的任务；下载设置在提交时固定。每条链接的线程数和限速单独生效，总执行器数最多为两个并行数的乘积。

任务列表保留本次运行中最近 100 个已结束任务，程序重启后不恢复普通队列；全局下载历史照常保存。相同的活跃链接会拒绝重复提交。关闭任务模式后，需先完成或取消现有队列，才能启动旧单任务流程；“停止”会处理实际活跃任务。蹲开播仍通过等待开播面板管理。实现检查和当前边界见 [任务模式检查报告](docs/任务模式检查报告.md)。

### 批量下载
1. 进入「工具箱」页面
2. 点击「生成链接模板」创建 `urls.txt`
3. 编辑 `urls.txt`，每行一个链接（支持混合平台）
4. 点击「TXT批量下载」开始批量下载

### 直播录制（Twitch / YouTube）
在「设置 → 直播设置」选择全局模式，并可分别为支持追开播的平台设置默认录制方式。开始直播任务前会检查直播状态：未开播时提示是否蹲开播；已开播时显示开播时间/已开播时长并让你选择录制方式；追开播不可用时会说明原因并降级为从当前时刻。蹲开播任务可在下载页「等待开播」面板取消。Twitch 粘贴主播频道URL（如 `https://www.twitch.tv/xqc`），文件保存到 `download/Twitch/主播名/直播/`。Twitch 未开播时按提示选择蹲开播，不会静默无限等待。

### YouTube / Niconico 直播录制
YouTube 使用 `/live` 直播链接，Niconico 使用 `live.nicovideo.jp` 或 `live2.nicovideo.jp` 链接。YouTube 在 DVR/归档可用时可追开播；Niconico 当前只从当前时刻录制（上游 chasePlay 固定关闭）。程序实时显示录制时长、大小、速度和分片状态。

### TwitCasting 直播录制 / 录播下载
粘贴主播页 URL（如 `https://twitcasting.tv/主播名`）后默认从当前时刻录制（平台不支持 yt-dlp 从头），文件保存到 `download/TwitCasting/主播名/直播/` 目录。单条录播使用 `/movie/数字ID` 链接，历史直播列表使用 `/show` 或 `/archive` 链接。密码保护或会员限定内容可在「设置」页填写「TwitCasting 密码」后下载。

### Bilibili 下载
粘贴 Bilibili 视频或直播链接后程序会自动识别。直播默认从当前时刻录制（普通观看侧无 DVR，不支持追开播）；多 P 视频可按设置下载全部分集或弹出分集选择器；1080P 及以上画质通常需要在程序目录配置 `cookies.txt`。

### Withny 历史存档
在下载页面选择 Withny，点击「选择 HAR 并下载」，依次选择浏览器导出的包含内容 HAR 和输出文件。程序只处理已授权的普通未加密 HLS，检测到 DRM、加密 HLS、缺失媒体清单正文或签名 Cookie 时会拒绝下载。HAR 可能包含登录信息，使用后应立即删除。

### 配置预设
1. 在「设置」页面调整好各项参数
2. 在「配置预设」区域输入预设名称
3. 点击「保存」按钮
4. 之后可随时从下拉框选择预设一键加载

### 自动更新
程序启动后3秒自动通过 GitHub Releases 静默检查更新。检测到新版本时右上角显示「⬆ 有更新」徽标，点击后可一键下载；程序会校验可信下载来源、文件大小、Windows EXE 格式及 SHA-256，校验通过后自动替换重启，所有配置和下载记录保留。

## ⚙️ 配置选项

| 设置项 | 说明 | 默认值 |
|--------|------|--------|
| 分辨率 | best/2160/1440/1080/720/480/360 | best |
| 编码 | best/h264/av1/vp9 | best |
| 音频质量 | best/192/128 | best |
| 输出格式 | mp4/mkv/webm | mp4 |
| 合并模式 | 合并/分离 | 合并 |
| 线程数 | 下载线程数 | 4 |
| 代理 | HTTP/SOCKS5代理支持 | 关闭 |
| Cookie | cookies.txt文件模式 | 文件模式 |
| 硬件加速 | CPU/NVENC/QSV/AMF | CPU |
| 字幕下载 | 人工/自动字幕，支持语言预设 | 关闭（开启后默认中文） |

## 🍪 Cookie配置

对于需要登录才能观看的视频（如年龄限制、会员内容、Niconico高画质），需要配置Cookie：

1. 安装浏览器扩展「Get cookies.txt LOCALLY」（Chrome/Edge/Firefox均支持，纯本地运行）
2. 登录对应平台（YouTube/Twitch/Niconico/Fantia/TwitCasting）
3. 在目标平台页面点击扩展图标，导出 **Netscape格式** Cookie
4. 将导出的文件重命名为 `cookies.txt`，放到exe同目录
5. 重启程序即可生效

> ⚠️ **注意**：Fantia仅支持cookies.txt文件模式，不支持浏览器提取。Cookie仅传递登录态，不能绕过付费墙。

## 📂 目录结构

```
工具目录/
├── 视频下载工具v2.5.0-GUI.exe # 主程序
├── dependency/              # 所有第三方依赖，可整体替换
│   ├── yt-dlp.exe           # 下载核心
│   ├── ffmpeg.exe           # 音视频处理
│   ├── ffprobe.exe          # 媒体信息探测
│   ├── deno.exe             # JavaScript运行时
│   ├── fantiadl.exe         # Fantia下载器（可选）
│   ├── nicochannel.zip      # NicoChannel插件（可选）
│   ├── yt-dlp-plugins/
│   │   └── bgutil-ytdlp-pot-provider.zip
│   └── bgutil-ytdlp-pot-provider/
│       └── server/          # BgUtils Provider 与 node_modules（可选）
├── settings.ini             # 配置文件（自动生成）
├── presets.json             # 预设配置（自动生成）
├── cookies.txt              # Cookie文件（自行放置）
├── urls.txt                 # 批量下载链接（自行编辑）
├── changelog.html           # 更新日志
├── CREDITS.txt              # 作者与贡献者
├── docs/                    # 帮助文档
│   ├── 使用教程.txt
│   ├── 常见问题答疑.txt
│   ├── 错误码.txt
│   └── cookies问题答疑.txt
└── download/                # 所有运行产物，可整体迁移或备份
    ├── archive/             # 各平台 *_archive.txt
    ├── download_history.json # 下载历史（自动生成）
    ├── logs/                # 日志目录
    ├── YouTube/             # YouTube下载目录
    │   └── 上传者名/
    │       └── 视频标题 [id].mp4
    ├── Twitch/              # Twitch下载目录
    ├── Niconico/            # Niconico下载目录
    ├── NicoChannel/         # NicoChannel下载目录
    ├── Bilibili/            # Bilibili视频、直播及多P目录
    ├── Fantia/              # Fantia下载目录
    ├── Twitter/             # Twitter/X下载目录
    ├── Withny/              # Withny历史存档目录
    └── TwitCasting/         # TwitCasting下载目录
```

旧版本散落在根目录的依赖、平台下载目录和 `*_archive.txt` 会在首次启动时自动迁移到上述结构。迁移不会覆盖同名文件；发生冲突时，旧文件会以 `.legacy-N` 后缀保留。

## 🔧 工具箱功能

- 📋 **TXT批量下载** - 从urls.txt读取链接批量下载
- 📝 **生成链接模板** - 生成带注释的urls.txt模板
- 🍪 **生成Cookie模板** - 生成Netscape格式cookies.txt模板
- 🔄 **更新yt-dlp** - 一键更新下载核心到最新版本
- 🗑️ **清理临时文件** - 清理下载产生的.part/.ytdl等临时文件
- 🎵 **WAV转MP3** - 批量音频转换，支持比特率选择
- 📂 **打开下载目录** - 在资源管理器中打开下载文件夹
- 📋 **打开日志目录** - 在资源管理器中打开日志文件夹
- **单独下载字幕** - 输入一个或多个链接，仅下载指定类型和语言的字幕
- 🖼️ **下载视频封面** - 输入一个或多个链接，只抓封面图片；自动识别平台，保存
  到该视频所在的平台目录，文件名与视频完全一致（如 `[20260907] 标题 [ID].jpg`），
  不写入下载归档，因此不影响之后的正式下载。Fantia 与 Withny 不走 yt-dlp，暂不支持。

## ❓ 常见问题

**Q: 下载速度慢怎么办？**
> A: 1. 配置代理；2. 适当增加线程数；3. 在工具箱更新yt-dlp到最新版本。

**Q: 提示需要登录？**
> A: 配置Cookie，参考Cookie配置说明。

**Q: Niconico只能下载低画质？**
> A: 需要配置登录Cookie，游客身份仅能获取低清晰度。登录后导出cookies.txt即可。

**Q: 下载的文件在哪里？**
> A: 默认保存在exe同目录的 `download/` 下，如 `download/YouTube/`、`download/Twitch/` 等。

**Q: 可以同时下载多个视频吗？**
> A: 同一时间只能运行一个下载任务，但批量下载会按顺序自动下载所有链接。

**Q: 关闭浏览器会中断下载吗？**
> A: 不会。下载在后台继续进行，下载完成后30秒自动退出。如需停止请点击「停止」按钮或右上角「✕ 退出」按钮。

**Q: 双击exe后浏览器没自动打开？**
> A: 查看控制台窗口显示的端口号（如 http://127.0.0.1:8765），手动在浏览器中输入该地址访问。

**Q: 老用户如何升级？**
> A: 下载 `video-downloader-v2.5.0-GUI.exe` 替换旧版 exe，并使用 v2.5.0 依赖包补齐新增插件；原有配置和下载记录无需改动。

## 📚 详细文档

更多详细说明请查看 `docs/` 目录下的文档：

- [📖 完整使用教程](docs/使用教程.txt) - 从安装到高级功能的完整指南
- [📦 Withny HAR 指南](docs/withny_har_guide.txt) - 获取包含内容 HAR、下载和隐私安全说明
- [🍪 Cookie配置指南](docs/cookies问题答疑.txt) - Cookie配置详细说明和常见问题
- [❓ 常见问题答疑](docs/常见问题答疑.txt) - 常见问题的解决方案
- [⚠️ 错误码说明手册](docs/错误码.txt) - 下载错误码详解和排查流程
- [📋 更新日志](resource/templates/changelog.html) - 版本更新历史

## 📋 版本更新

v2.5.0 的完整更新内容和升级说明请查看：

- [发布说明](RELEASE_NOTES.md)
- [内置更新日志](resource/templates/changelog.html)

## ⚠️ 免责声明

- 本工具仅供学习和个人使用，请遵守当地法律法规
- 请勿用于下载受版权保护的内容，除非您拥有相关权利
- 使用者需自行承担使用本工具产生的一切责任
- 各平台商标归其各自所有者所有

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## 作者与贡献者

- 项目原版作者：[猫猫葉汐A_spy（GitHub：@maomaoyexi）](https://github.com/maomaoyexi)
- v2.1.0 WebUI 重构：[DarkKandaoMaster（强壮的砍刀）](https://github.com/DarkKandaoMaster)
- v2.3.0 NicoChannel、Twitter/X、TwitCasting、UI 与音频工具：[ErgouTree（GitHub：@ergou10086）](https://github.com/ergou10086)
- v2.3.0 Withny 历史存档、直播录制与 UI 调整：[猫猫葉汐A_spy（GitHub：@maomaoyexi）](https://github.com/maomaoyexi)
- v2.4.0 UI 重构：[DarkKandaoMaster（强壮的砍刀）](https://github.com/DarkKandaoMaster)
- v2.4.0 字幕下载：[ZheYi101](https://github.com/ZheYi101)
- v2.4.0 其他更新与修复：[ErgouTree（GitHub：@ergou10086）](https://github.com/ergou10086)
- v2.4.0 字幕功能修复与合并适配：[猫猫葉汐A_spy（GitHub：@maomaoyexi）](https://github.com/maomaoyexi)
- v2.5.0 WebUI 视觉与交互体系重构：[DarkKandaoMaster](https://github.com/DarkKandaoMaster)
- v2.5.0 设置控件、TwitCasting 下载与进度、BgUtils Provider 及目录收拢：[ErgouTree（GitHub：@ergou10086）](https://github.com/ergou10086)

## 直播录制 P2/P3

直播录制新增 P2/P3：优雅停止、会话与完整性报告、磁盘/超时/看门狗，以及外置 BililiveRecorder 引擎。安装、设置限制、验证范围与一手资料见 [直播录制 P2/P3 说明](docs/直播录制-P2-P3.md)。完整性报告通过前不会显示录制成功；第三方许可见 [NOTICE](NOTICE)。

## 致谢

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - 强大的视频下载引擎
- [FFmpeg](https://ffmpeg.org/) - 音视频处理工具

---

**如果这个工具对您有帮助，欢迎给个Star ⭐**
