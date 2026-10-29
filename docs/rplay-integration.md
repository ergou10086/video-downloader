# Rplay 集成记录

## 范围与证据（2026-10-29）

首版实现公开单点播 HLS 下载与只读直播状态检查。账号授权、DASH、直播录制、WAIT 和评论尚未通过真实验收，对应入口不开放。没有新增运行时依赖，也没有替换官方 yt-dlp。

依据为平台实际响应与以下原作者实现，均非官方稳定 API 合同：

| 来源 | 本次使用的事实 | 边界 |
| --- | --- | --- |
| [RPlay 官方 content 接口](https://api.rplay.live/content?contentOid=682065da13ed2c564c77d8f7&status=published&requestCanView=true&lang=en) | `_id`、`drm`、`canView.canView/url/mediaType`、时长与创作者 | 只使用明确允许观看的播放响应；URL 不持久化 |
| [RPlay 官方直播详情](https://api.rplay.live/live/play?creatorOid=667adc9e9aa7f739a2158ff3&lang=en) | `creatorOid`、`streamState`、`accessible`、`allowAnonymous`、`streamStartTime` | 真实样本仅覆盖 offline；空直播列表不作为具体频道离线证据 |
| [yt-dlp 的 RPlay 接入 PR #10693](https://github.com/yt-dlp/yt-dlp/pull/10693)及[作者提取器](https://github.com/c-basalt/yt-dlp/blob/rplay-native/yt_dlp/extractor/rplaylive.py) | `/play/{OID}`、`/live/{creatorOid}`、点播响应与 HLS 解析方式；原作者报告令牌接口多次变更 | 本次核对时 PR 未合并；只参考接口语义，独立实现公开内容适配 |
| [rplay-live-dl 客户端](https://github.com/Zhen-Bo/rplay-live-dl/blob/main/core/rplay.py) | 刷新令牌与 key2 流程、脱敏异常处理实践 | MIT 项目；未移植代码，未调用刷新令牌、key2 接口 |
| [avtdl RPlay 实现](https://github.com/15532th/avtdl/blob/master/avtdl/plugins/rplay/rplay.py) | 频道与内容 ID、原生/转播分类、Origin/Referer | 不引入其账号认证、调度或通知实现 |
| [yt-dlp 官方插件接口](https://github.com/yt-dlp/yt-dlp#plugins) | 独立命名空间插件、既有代理/HLS/格式选择与 FFmpeg 后处理 | 插件随 resource 资源发现，沿用现有源码及冻结程序路径 |

当前两个公开点播样本的 `drm=false`、`encrypted=true`，HLS 声明 `METHOD=AES-128,KEYFORMAT="identity"`；不能把 `encrypted=true` 直接等同 DRM。本实现只接受 NONE/AES-128 identity，DRM、SAMPLE-AES、未知加密和未经取样的媒体类型均拒绝。

## 架构与设置

`rplay.py` 是独立 yt-dlp 提取策略。请求层和媒体下载复用 yt-dlp；现有下载执行器继续负责队列、限速、历史、音频处理和输出文件。平台协议没有进入 UI 或任务调度器。

- 平台名统一为 `Rplay`，目录为 `download/Rplay`，平台验证和历史筛选沿用现有注册表。
- 画质、音频、容器、代理、封面复用现有设置。Cookie 文件和浏览器 Cookie 不用于这个公开内容适配器；RPlay 的账号令牌并不在 Cookie 中。
- 单 URL 不扩展 `playlist` 参数；自定义频道别名、列表和未知路径明确失败。非 HTTPS 主站链接不能开启任务。
- 不支持片段身份确认前的断点续传，缺片必须报错；不把过期地址重新解析后直接追加到旧 `.part`。
- RPlay 的画质上限按视频短边选择（竖屏 720×1280 对应 720 档），每个回退分支保留上限；无符合格式时报错。编解码器偏好可回退，但不会因此放宽画质。合并 HLS 的独立音画分离尚未实现，提交前明确拒绝该组合。
- 不读取全局 yt-dlp 配置，不保存包含签名播放地址的 info JSON。下载、字幕、封面与探测的错误输出进入日志/SSE 前去除签名查询和凭据字段。
- `canView=false` 时即使存在 URL 也不下载，避免把预览误报为完整视频。DRM 缺失或非 false 时拒绝。
- 直播检查只使用 `live/play`；不取直播 key、媒体、聊天或转播 URL。在播状态必须有可验证的起始时间，场次键使用创作者与起始时间组合。
- 录制模式、命令构造、检查结果和 WAIT 服务分别设门槛；禁用能力不能通过 AUTO、直接命令或直接 HTTP WAIT 请求绕过。
- 不添加登录开关、凭据配置或说明性 UI 文案，避免出现无实现的设置。未来账号适配需先实现安全凭据保存与独立验收。

## 测试与样本

`tests/platforms/fixtures/rplay` 是官方响应的字段白名单投影：只保留测试所需的公开元数据、权限布尔值与类型；标题、昵称和简介匿名化，播放 URL 替换为测试占位，未保留令牌、完整播放响应、用户清单、聊天地址或直播密钥。

| 实际检查 | 结果 |
| --- | --- |
| 点播 `682065da13ed2c564c77d8f7` | 可匿名观看，API 时长 11.483 秒；标准 yt-dlp 完整下载，ffprobe 检出 H.264/AAC、1080×1920，封装时长 11.516333 秒 |
| 点播 `669203d25223214e67579dc3` | `canView=true`，读取到普通 AES-128 identity HLS 主清单；未下载整场 |
| 用户指定点播 `690e66fbcd5bc730495d1285` | API 时长 377.2 秒，`canView=false` 且无授权播放 URL；插件返回需登录/订阅，不宣称已下载 |
| 创作者 `667adc9e9aa7f739a2158ff3` 与 `64d483add2c96306099ef734` | 官方详情均为 offline；`accessible` 与 `allowAnonymous` 各不相同，不能用权限标志代替直播状态 |
| 项目实际 `yt-dlp.exe` 加载新插件 | 公开点播识别到 3 档格式；用户样本拒绝；直播只读返回 `not_live`，无媒体格式 |
| 应用命令构造器 + 720 档 + 中文空格目录 | 实际 720×1280 H.264/AAC，11.516333 秒；FFmpeg 整段解码退出 0，无解码错误；再次执行归档跳过，只有一份视频 |
| 只输出 MP3 + 默认元数据/封面 | 实际生成 MP3 与 JPEG，音频时长 11.498667 秒；未留下中间 MP4 |
| 同时输出音频的既有执行器 | 从上述视频成功导出有效 MP3 音频副本 |
| UI 与后端 URL 路由 | 执行实际 app.js 路由函数，核对直播、点播、列表、额外路径与仿冒域名；平台入口复用现有芯片与历史筛选 |
| 冻结程序资源路径 | 临时模拟 `_MEIPASS` 并检查插件发现；不等同实际冻结 EXE 发布验收 |

合成在播数据只验证字段映射、身份和禁用边界，不能代替真实直播。未验收项目：账号授权与续期、真实在播状态、30 分钟/2 小时录制、断网恢复、真实 WAIT 开播、评论时间轴、完整冻结程序发布。以上未验收项目不能标为已支持。

质量门槛：新增插件行覆盖率至少 90%，现有直播模块维持 85%；覆盖率与真实媒体验证分别记录。每阶段提交前运行适用回归，最后清除本轮生成的媒体、原始响应和临时工具。

最终检查：全量回归 719 通过、1 跳过、51 个子测试通过；最后收紧 URL 边界后，相关回归再验证 111 通过。RPlay 插件与应用策略行覆盖率 133/133（100%），直播模块整体 3407/3886（87.67%）。JavaScript 语法、实际 UI 路由函数及仓库目录检查通过。测试运行时将临时目录放在项目 `temp`；需要本机 HTTP 的集成测试在允许回环连接的环境执行。

后续推进顺序：先用用户可授权观看的账号样本实现进程内认证与安全存储，完成指定点播完整下载，再取得真实在播样本验收录制/停止/重连与 WAIT；评论必须取得真实协议和时间锚点后再开放。当前阶段不能视为设计计划 R0–R5 全部完成。
