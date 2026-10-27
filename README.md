# 多平台视频下载工具 v2.6.0 WebUI
支持 YouTube / Bilibili / Twitch / Niconico / NicoChannel / Fantia / TwitCasting / Twitter 八个平台的视频/直播下载，并提供 Withny 已授权历史存档 HAR 保存及直播监控录制功能。Release 的 EXE 绿色版无需安装 Python；源码运行版使用 Python 3 启动。

![Version](https://img.shields.io/badge/version-v2.6.0%20WebUI-purple) ![Platform](https://img.shields.io/badge/platform-Windows-blue) ![License](https://img.shields.io/badge/license-MIT-green)

> v2.6.0 由 [猫猫葉汐A_spy（@maomaoyexi）](https://github.com/maomaoyexi) 完成 YouTube、Bilibili、Twitch、Niconico、NicoChannel、TwitCasting、Twitter/X Spaces 直播入口识别、直播录制策略、断流处理与实时状态展示，以及任务页「本次 yt-dlp 参数」和「直播录制设置」两个按钮及相关设置功能、Cookie 模板修复、TwitCasting 密码表与失效记录清理、HLS 回退、下载完成后 `.ytdl` 清理、回归测试及相关文档整理；[ErgouTree（@ergou10086）](https://github.com/ergou10086) 完成 PR #15 的下载归档选择、独立批量封面及 PO Token Provider 启动改进。

## ✨ 功能特性

- 🌐 **全新WebUI界面** - 内置HTTP服务器，自动打开浏览器，深色主题，响应式设计
- 🎬 **八平台支持** - YouTube、Bilibili、Twitch、Niconico、NicoChannel、Fantia、TwitCasting、Twitter，自动识别平台
- 📦 **Withny 支持** - 从 HAR 保存已授权历史存档，也可通过 withny-dl 配置监控和录制直播
- 📺 **Bilibili 支持** - 支持普通视频、直播和多 P 分集选择
- 🎮 **直播录制** - 支持 YouTube、Bilibili、Twitch、Niconico、NicoChannel、TwitCasting、Twitter/X Spaces 直播识别、录制和实时状态；Withny 另提供独立监控录制。本版跨平台直播录制由 [猫猫葉汐A_spy（@maomaoyexi）](https://github.com/maomaoyexi) 实现与维护
- 💾 **配置预设** - 保存常用设置组合，一键切换
- 📜 **下载历史** - 自动记录每次下载，最多500条
- 📂 **下载归档选择** - 命中归档时可选择重新下载或跳过，20 秒未选择默认跳过；跳过单独计数
- 🔄 **断点续传** - 默认启用，网络中断后自动续传
- 📊 **批量下载** - 支持从TXT文件批量导入链接
- ⌨️ **命令行模式** - 支持直接传入 URL 或通过 `--batch` 批量下载
- 🧾 **多行链接** - 下载页可直接粘贴多行 URL，按顺序加入批量队列
- 🖼️ **封面处理** - 下载独立 JPG 封面，并在兼容格式中自动嵌入
- 🖼️ **独立批量封面** - 可仅下载多个视频的封面，沿用视频命名规则，不写入下载归档
- **字幕下载** - 支持普通下载附带字幕及独立多链接字幕下载，默认关闭，开启后默认中文
- 🎵 **MP3 音频下载** - 支持在下载视频时单独保存 MP3 音频
- 🍪 **Cookie支持** - 支持cookies.txt文件模式
- 🛡️ **YouTube PO Token** - 可选自动启动本地 BgUtils Provider，缓解部分 GVS/PO Token 相关 403
- 🧩 **自定义 yt-dlp 参数** - 支持仅本次任务参数与每次下载默认参数
- ⚡ **硬件加速** - 支持NVIDIA NVENC、Intel QSV、AMD AMF
- 🔄 **自动更新** - 启动后通过 GitHub Releases 检查新版本，校验通过后自动更新替换
- 🧰 **工具箱** - 提供独立字幕与封面下载、WAV转MP3、yt-dlp更新、临时文件清理等工具
- 🛡️ **进程管理** - 关闭网页30秒后自动退出，无残留进程

## 🚀 快速开始

1. 安装 Python 3，并确保 `python` 命令可用。
2. 保持 `视频下载工具v2.6.0-GUI.py`、`video_downloader/`、`resource/` 和 `dependency/` 位于同一目录。
3. 确认 `dependency/` 中的下载工具已准备好。
4. 使用下方源码启动命令运行，程序会自动打开浏览器界面。

> 💡 **提示**：依赖包的 `dependency/` 包含 yt-dlp.exe、ffmpeg.exe、ffprobe.exe、deno.exe、fantiadl.exe、withny-dl-windows-amd64.exe 和 `yt-dlp-plugins` 目录。NicoChannel 还需要单独准备 `nicochannel.zip` 并放入 `dependency/`。首次运行会自动生成 `download/`、归档及日志目录。

若要启用 YouTube PO Token，请同时保留 `dependency/yt-dlp-plugins/bgutil-ytdlp-pot-provider.zip` 和 `dependency/bgutil-ytdlp-pot-provider/server`（含已安装的 `node_modules`）。在「设置 → 平台专项」打开 YouTube PO Token 后，程序会在 YouTube 任务开始前自动启动 Provider，并在退出工具时关闭它；无需另开 CMD。Provider 可能缓解部分 403，但不能保证绕过所有风控或登录校验。

Provider 首次启动在后台准备，日志每 5 秒报告等待进度，最多等待 60 秒，期间可点击「停止」。健康检查通过后才运行 yt-dlp，后续任务复用已就绪的 Provider。启动失败会保留 Deno 错误并释放任务，修复依赖后可重试；启动过程只使用已安装的依赖，不在线安装包，也不等待控制台确认。

TwitCasting 多初始化段归档会自动加载随项目提供的 `dependency/yt-dlp-plugins/video_downloader` 插件，按设置中的下载线程数并发预取 HLS 分片，再由 FFmpeg 完成本地封装；无需另装下载器。若插件缺失，程序会安全退回 FFmpeg 串行下载。

### 源码运行版

保持 `视频下载工具v2.6.0-GUI.py`、`video_downloader/`、`resource/` 与 `dependency/` 位于同一目录，安装 Python 3 后运行：

```powershell
python ".\视频下载工具v2.6.0-GUI.py"
```

源码运行版不会用下载到的 EXE 自动覆盖 Python 源码；升级源码时请手动替换主脚本、`video_downloader/` 与 `resource/` 目录。

如需 EXE 绿色版，请查看 [Releases](https://github.com/maomaoyexi/video-downloader/releases) 中的 v2.6.0 正式版及其配套依赖包，并按该版本说明安装。

## 📖 使用说明

### 单视频下载
1. 在「下载」页面粘贴视频链接
2. 点击「开始下载」
3. 实时查看进度、速度、剩余时间

### 批量下载
1. 进入「工具箱」页面
2. 点击「生成链接模板」创建 `urls.txt`
3. 编辑 `urls.txt`，每行一个链接（支持混合平台）
4. 点击「TXT批量下载」开始批量下载

### 已下载记录与重新下载

命中下载归档时，弹窗提供「重新下载」和「跳过」，20 秒未选择后默认跳过并继续队列。跳过单独计数，不算下载成功。归档只表示曾经记录过该视频，不能证明磁盘文件仍然完整。

选择重下只清除当前命中的归档记录，保留其他记录，并按当前输出模板覆盖同名视频和配套音频，不生成编号副本。重下失败不会重新写入成功归档。更改输出目录、文件名模板或格式后，文件会按新设置保存。

### Twitch直播录制
直接粘贴主播频道URL（如 `https://www.twitch.tv/xqc`）即可录制，具体从哪里开始由「直播录制模式」决定：默认追开播，选择蹲开播可等待未开播频道。停止则结束录制，文件自动保存到 `download/Twitch/主播名/直播/` 目录。

### 各平台直播录制

程序会按链接形状自动识别直播入口，并将直播文件保存到对应平台的 `download/<平台>/.../直播/` 目录。支持的入口如下：

本版 YouTube、Bilibili、Twitch、Niconico、NicoChannel、TwitCasting 和 Twitter/X Spaces 的直播入口识别、录制流程、断流处理与实时状态由 [猫猫葉汐A_spy（@maomaoyexi）](https://github.com/maomaoyexi) 完成。平台登录、地区和会员权限仍由平台及 yt-dlp 决定。

- **YouTube**：`youtube.com/live/...` 或 `youtube.com/live`；选择「追开播」时使用 `--live-from-start` 尝试从直播开始处录制，其他模式按对应策略处理。
- **Bilibili**：`live.bilibili.com/<房间号>`，按直播流持续录制，直播链接不会触发视频分 P 选择。
- **Twitch**：主播频道页 `twitch.tv/<主播名>`；`/videos/` 和 `/clips/` 会按回放或剪辑处理。
- **Niconico**：`live.nicovideo.jp/watch/lv...`、`live2.nicovideo.jp/...` 或 `nicovideo.jp/watch/lv...`；保留 yt-dlp 的 Timeshift 语义，不强制追加 `--live-from-start`。
- **NicoChannel**：`nicochannel.jp/<频道>/live/sm...`，需要 `nicochannel.zip` 插件及 Firefox 登录令牌。
- **TwitCasting**：主播页 `twitcasting.tv/<主播名>`；密码或会员限定内容可在设置中提供密码，m3u8 异常会自动执行直连、Firefox Cookie 和 FFmpeg 回退。

TwitCasting 成功验证的录播密码会按完整链接保存到程序根目录的 `twitcasting_passwords.xlsx`，表格包含“链接、密码、时间”三列，列宽默认分别为 60、15、20；表头上方会显示“除非获得明确授权，请勿发送给其他人”的警告。工作簿会冻结表头、启用筛选并按日期格式显示时间。旧版本的 `twitcasting_passwords.csv` 或 `download/` 下的密码表会在首次读取时自动迁移。下次下载同一链接时会先自动尝试已保存密码；如果密码失效，程序会删除该条记录并重新弹窗输入，验证成功后更新记录。密码以明文保存在本机，请勿将此文件分享给他人。
- **Twitter/X Spaces**：`x.com/i/spaces/...` 或 `twitter.com/i/spaces/...`，通常需要登录 Cookie，平台未保留回放时无法录制。
- **Withny**：选择 Withny 后使用“选择配置并录制”，由 `withny-dl` YAML 配置执行频道监控。

Fantia 当前仅接入帖子/媒体下载，项目没有稳定的直播 URL 形状，因此不会把普通 Fantia 页面误判为直播。

直播录制期间会显示 LIVE、时长、大小、速度和分片状态；点击“停止”结束当前录制。平台登录、地区、会员权限和直播是否提供回放仍由平台及 yt-dlp 决定。

「下载任务」页面的「本次 yt-dlp 参数」在左、「直播录制设置」在右，两个按钮并排显示，分别打开对应的设置小窗口。

点击「直播录制设置」可选择直播录制模式：

- **蹲开播**：任务保持运行，按检测间隔轮询直播状态，检测到开播后自动开始录制；适合还未开播的频道。
- **追开播**：直播已开始时，使用 `--live-from-start` 尝试从直播起点追录；如果平台返回没有可回溯分片，程序会自动降级为从当前分片录制。
- **加入时开录**：不追溯，直接从提交链接时能获取到的当前分片开始录制。

蹲开播的检测间隔可设置为 5–600 秒，停止任务会立即取消等待。Withny 的 YAML 监控仍由 `withny-dl` 独立负责。

### TwitCasting 直播录制 / 录播下载
粘贴主播页 URL（如 `https://twitcasting.tv/主播名`）即可录制直播，起点由「直播录制模式」决定（蹲开播、追开播或加入时开录）；文件保存到 `download/TwitCasting/主播名/直播/` 目录。单条录播使用 `/movie/数字ID` 链接，历史直播列表使用 `/show` 或 `/archive` 链接。密码保护或会员限定内容可在「设置」页填写「TwitCasting 密码」后下载。

### Bilibili 下载
粘贴 Bilibili 视频或直播链接后程序会自动识别。多 P 视频可按设置下载全部分集或弹出分集选择器；1080P 及以上画质通常需要在程序目录配置 `cookies.txt`。

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

工具箱的「生成 Cookie 模板」只创建空白 Netscape 格式模板，不含登录凭证；真实 Cookie 仍需从已登录浏览器导出。已有 `cookies.txt` 不会被覆盖，也不会自动转换格式。文件首行应为 `# Netscape HTTP Cookie File`，每条 Cookie 的 7 个字段须用实际 TAB 分隔，不能用空格或字面量 `\t` 代替。

> ⚠️ **注意**：Fantia仅支持cookies.txt文件模式，不支持浏览器提取。Cookie仅传递登录态，不能绕过付费墙。

## 📂 目录结构

```
工具目录/
├── 视频下载工具v2.6.0-GUI.py  # 当前源码入口
├── video_downloader/          # 程序模块
├── resource/                  # WebUI 模板与静态资源
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
- 🍪 **生成Cookie模板** - 创建不含登录凭证的空白 Netscape 模板和配置说明；已有 cookies.txt 不覆盖
- 🔄 **更新yt-dlp** - 一键更新下载核心到最新版本
- 🗑️ **清理临时文件** - 清理下载产生的.part/.ytdl等临时文件
- 🎵 **WAV转MP3** - 批量音频转换，支持比特率选择
- 📂 **打开下载目录** - 在资源管理器中打开下载文件夹
- 📋 **打开日志目录** - 在资源管理器中打开日志文件夹
- **单独下载字幕** - 输入一个或多个链接，仅下载指定类型和语言的字幕
- 🖼️ **下载视频封面** - 输入一个或多个链接，只下载封面并转换为 JPG；保存目录和文件名沿用当前视频输出模板，不写入下载归档，不影响之后的正式下载。Fantia、Withny 及未识别平台暂不支持此工具

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
> A: 关闭旧程序后下载 GitHub Release 中的 v2.6.0 正式版，按说明替换主程序并补齐 `dependency/`；原有配置和下载记录保留。源码用户也可以替换主脚本、`video_downloader/` 与 `resource/` 后运行。

## 📚 详细文档

更多详细说明请查看 `docs/` 目录下的文档：

- [📖 完整使用教程](docs/使用教程.txt) - 从安装到高级功能的完整指南
- [📦 Withny HAR 指南](docs/withny_har_guide.txt) - 获取包含内容 HAR、下载和隐私安全说明
- [🍪 Cookie配置指南](docs/cookies问题答疑.txt) - Cookie配置详细说明和常见问题
- [❓ 常见问题答疑](docs/常见问题答疑.txt) - 常见问题的解决方案
- [⚠️ 错误码说明手册](docs/错误码.txt) - 下载错误码详解和排查流程
- [📋 更新日志](RELEASE_NOTES.md) - 版本更新历史

## 📋 版本更新

v2.6.0 的完整更新内容和升级说明请查看：

- [发布说明](RELEASE_NOTES.md)

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
- v2.6.0 各平台直播入口识别、直播录制策略、断流处理与实时状态展示；任务页「本次 yt-dlp 参数」和「直播录制设置」两个按钮及相关设置功能、Cookie 模板修复、TwitCasting 密码表及失效记录清理、HLS 回退、`.ytdl` 清理、回归测试与相关文档：[猫猫葉汐A_spy（GitHub：@maomaoyexi）](https://github.com/maomaoyexi)
- v2.6.0 PR #15 下载归档选择、独立批量封面及 PO Token Provider 启动改进：[ErgouTree（GitHub：@ergou10086）](https://github.com/ergou10086)

## 致谢

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - 强大的视频下载引擎
- [FFmpeg](https://ffmpeg.org/) - 音视频处理工具

---

**如果这个工具对您有帮助，欢迎给个Star ⭐**
