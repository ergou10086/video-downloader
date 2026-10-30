# Rplay 集成记录

## 范围与证据（2026-10-29 至 2026-10-30）

接入单点播 HLS、Firefox 站点登录态、BytePlus 签名 FLV 直播、Twitch 转播、LIVE_EDGE 和 WAIT，复用官方 yt-dlp、FFmpeg 与现有录制生命周期。没有新增 RPlay 运行时依赖。DASH、DRM、YouTube 转播、列表和 DVR 保持关闭；未知媒体明确拒绝。

接口没有官方稳定版本合同。当前官方前端与实际授权响应优先，旧开源实现仅用于交叉验证，不能替代真实验收。

| 来源 | 使用的事实与边界 |
| --- | --- |
| [RPlay 官方站点](https://rplay.live/)与当前前端 [index-BdHhza60.js](https://rplay.live/assets/index-BdHhza60.js)、[CjKIycbabY.js](https://rplay.live/js/CjKIycbabY.js) | IndexedDB 会话、BytePlus play-urls、聊天令牌、转播与评论字段。资源版本可能变化。 |
| [官方点播详情](https://api.rplay.live/content?contentOid=682065da13ed2c564c77d8f7&status=published&requestCanView=true&lang=en)与[直播详情](https://api.rplay.live/live/play?creatorOid=685be2fb451781775ad8f88f&lang=en) | 身份、权限、状态和开播 UTC 分别核验；不把预览或权限错误当成功。 |
| [rplay-live-dl 客户端](https://github.com/Zhen-Bo/rplay-live-dl/blob/main/core/rplay.py)与[avtdl 适配](https://github.com/15532th/avtdl/blob/master/avtdl/plugins/rplay/rplay.py) | 刷新、key2、来源分类、Origin/Referer 和脱敏实践；独立实现，不移植调度器，不承诺永久续期。 |
| [yt-dlp 插件接口](https://github.com/yt-dlp/yt-dlp#plugins)与[RPlay 原作者 PR](https://github.com/yt-dlp/yt-dlp/pull/10693) | 保留主版本，以资源目录插件接入，复用代理、格式选择和后处理。 |
| [Google Firefox 解码实现](https://github.com/google/dfindexeddb/blob/main/dfindexeddb/indexeddb/firefox/gecko.py)与[Snappy 规范](https://github.com/google/snappy/blob/main/format_description.txt) | 独立实现有大小、深度和节点上限的会话解码子集，不执行反序列化对象。 |
| [Windows DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata) | 当前系统用户保护、应用专用 entropy、密文原子写入。 |
| [AWS IVS 消息格式](https://docs.aws.amazon.com/ivs/latest/chatmsgapireference/actions-message-subscribe.html)与[单次令牌提供器](https://docs.aws.amazon.com/ivs/latest/ChatUserGuide/chat-js-using-sdk.html) | 服务端消息 ID、发送 UTC；重连重新申请令牌，只接收，不发送评论或奖励心跳。 |

## 认证与隔离

本轮 cookies.txt 没有所需账号令牌。经用户明确授权，只读 Firefox 的 https://rplay.live IndexedDB `rplay-account-session/records/session`；不读取其他站点或密码库。SQLite 只读连接备份至内存，包含现有 WAL，不导出原始会话。

普通配置只有 `RPLAY_AUTH_SOURCE=none/firefox` 与 `RPLAY_FIREFOX_PROFILE`，不含秘密。WebUI 和 RPlay CLI 读取相同设置；界面只增加有标签的控件，没有协议说明段落。

账号令牌留在插件或评论 worker 内存。跨进程共享续期使用按账号和浏览器会话指纹隔离的 Windows DPAPI 密文缓存，退出后清理。线程锁和文件锁串行刷新；仅临近过期或 401 时续期，401 最多重试一次，403 不刷新；保留服务端轮换后的刷新令牌。浏览器退出登录后不能依赖旧缓存继续访问。非 Windows 平台明确拒绝受保护登录模式。

认证请求仅允许 api.rplay.live HTTPS，禁用重定向，复用代理/TLS。错误不带响应正文或认证头。BytePlus 签名 FLV 地址只保存在插件内存，FFmpeg 通过随机路径的本机回环转发器读取；上游沿用 yt-dlp 代理，回环绕过代理。禁止页面转储、流量打印和 info JSON；执行器与 CLI 输出先脱敏。配置、历史、会话、报告、SSE 和测试快照不保存账号秘密。

## 媒体与恢复

平台协议集中在资源目录提取器，`platforms/rplay.py` 管理格式策略和会话生命周期，`live/engines/rplay.py` 只补充源状态与同场校验。队列、预检、超时、停止、磁盘和无增长监控、分段及完整性报告由既有执行器承担。

点播仅接受 `drm=false`、明确 `canView=true` 的已验证 HLS。`encrypted=true` 不直接等同 DRM：公开样本是 AES-128 identity。SAMPLE-AES、未知密钥格式、缺失 DRM 标志、预览和未知媒体均拒绝。单 URL 不展开列表，不把重新解析的资源追加到旧半成品。

画质按短边筛选，每个回退分支保留上限；转播格式补充同一字段，未知尺寸不绕过上限。复用合并、仅音频、音频副本和封面处理；未验证的独立音画分离组合提前拒绝。没有字幕轨时不制造字幕。

原生真实房间采用官方前端的 `/live/bytedance/play-urls` 签名 FLV。其旧 HLS 地址出现过 HTTP 500 和几秒即 EOF，不能据此报告完整结束。进程返回 0 后仍检查源状态；仍在播则按上限重新解析。

每次恢复核对权限和服务端开播 UTC；实际媒体元数据再核对 ID 与开始时间，防止转播源重开后误拼。新尝试写独立目录，无连续证据就保留分段并报告缺口。暂时性探测错误有界退避；权限撤销、身份变化与不支持协议停止。

FFmpeg 仅设置有界读取超时，重连由 LiveRunner 统一管理。真实 FFmpeg 有限流测试说明，下载器透明重连可能反复读取同一成功响应，无法保证在单个文件内仍属同一场；因此 EOF 或网络中断后先重新鉴权和校验，再写新分段。FLV 参数不传给转播 HLS。

完整性同时核对解码时间 DTS 和呈现时间 PTS。正常 B 帧重排允许，已确认的前向媒体缺口继续报告 gaps；DTS 正常但 PTS 跳变或延迟异常时明确拒绝，不能仅凭容器可打开就报成功。依据为[FFmpeg AVPacket 的 PTS/DTS 定义](https://ffmpeg.org/doxygen/trunk/structAVPacket.html)。

Twitch 转播仅使用官方响应的合法频道名构造规范 URL，既有 Twitch 提取器独立核验公开源权限；不转交 RPlay 认证头或返回的 Twitch 令牌。原生与转播分别验收。

WAIT 复用 SQLite、原子认领、取消与重启，不伪造预定时间；场次键使用创作者和开播 UTC。没有足够 DVR 证据，AUTO 落到 LIVE_EDGE，显式追播拒绝。

## 评论与时间轴

独立 AWS IVS source 复用 httpx、WebSocket、JSONL/SQLite 去重、匿名化和 SRT/ASS 导出。单次聊天令牌通过 WebSocket 子协议传递，不放 URL；仅允许已核验的 IVS TLS 域名。

保留消息 ID、源 UTC、接收 UTC 和时间来源；普通消息读取 `Content.m`，礼物依据官方事件类型。没有昵称时留空，不额外查询用户资料。真实 chatUrl 尾部含空白，连接前只去首尾空白，内部控制字符仍拒绝。

重连重新取单次令牌并标记可能缺口，没有已验证的历史补发协议。媒体与评论分别报告，评论失败不终止录制。未知同步误差保持 null，无媒体时钟证据时仅作估算，允许微调和重导出。

用户指定点播 `6ad04991820b0db59527a4c5` 的 `/content/comments` 返回 3 条页面评论，没有媒体相对时间，不能按序号制造字幕，也不能替代直播弹幕验收。未保存其评论正文或用户资料。

## 真实验收

| 场景 | 结果 |
| --- | --- |
| 公开点播 `682065da13ed2c564c77d8f7` | 完整下载 H.264/AAC、1080×1920、11.516333 秒。720 档在中文空格目录输出 720×1280，整段解码无错误；MP3/JPEG、音频副本和归档跳过均通过。 |
| 授权点播 `690e66fbcd5bc730495d1285` | 登录前正确拒绝；授权后完整下载 25,944,927 字节，854×480、H.264/AAC、377.233 秒，全片解码退出 0、零诊断。 |
| 实际登录与续期 | Firefox IndexedDB 接入成功，访问令牌过期后实际续期成功；不升级成长期或永久续期保证。 |
| 原生直播 `685be2fb451781775ad8f88f` | 免费订阅后可观看，LD/SD/HD 实测为 360/540/720 档。主动停止的 177.086 秒样本音视频有效、无媒体警告。 |
| 原生较长样本 | 会话被中断，FLV 包时间覆盖约 1276 秒；不算 30 分钟验收或正常收尾通过。 |
| 原生评论连接 | 修复地址尾部空白后连接成功；短样本接收 0 条、重连 0、错误 0，不能宣称真实消息与同步验收完成。 |
| Twitch 转播 `6804c3b412eae6149c9ad9c5` | 连续录制按 30 分钟超时收尾，142,691,245 字节；DTS 覆盖约 1806 秒，但最大 PTS/DTS 偏移为 3593.866 秒。旧检查未识别，新检查正确拒绝，不能计作完整性通过。其后源频道下播。 |
| 转播受控进程中断 | 仅终止测试子进程，不修改系统网络；恢复后保留独立分段，退出码 1/0，原报告为 gaps。复查同样发现 PTS 异常，不能把恢复机制通过等同媒体完整性通过。 |
| 原装 yt-dlp 对照 | 同一 Twitch 源 20 秒片段有效；更长对照开始前源已下播。不能据此把长场异常归因于特定广告、源站或工具链，也不盲目重写时间戳。 |
| 真实状态与 WAIT | 原生离线房间保持 waiting，转播在播房间 triggered；重复 tick 只认领一次。这不是同一频道真实离线到开播转换。 |
| 新点播评论 | 3 条普通页面评论，无媒体时间位置，不伪造成弹幕。 |
| 冻结程序 | Windows EXE 实际构建及会话解码、DPAPI、评论依赖自检通过；中文空格独立便携目录完整下载上述授权点播，377.233 秒、全片解码零诊断。最终冻结直播检查时源已下播，没有媒体，不能记作冻结直播正常录制通过。 |

## 自动化质量与交付边界

合成凭据测试覆盖 Snappy/structured clone、SQLite WAL、DPAPI、跨进程单次刷新、401/403、域名和签名隔离、真实 FFmpeg FLV EOF、同场检查、WAIT 权限、评论断线/去重/时间来源、设置实际加载保存，以及 CLI 取消与 Unicode 输出。

全量回归 820 通过、1 跳过、51 个子测试通过；最终参数边界与实际 FFmpeg 专项另有 261 通过、7 个子测试通过。RPlay 协议行覆盖率 749/767（97.65%），直播整体 3568/4073（87.60%），分别超过 90% 与 85% 门槛。JavaScript 语法、实际设置加载保存和仓库目录检查通过。源码和冻结 EXE 分开验证。

仍需单独验收：原生连续 30 分钟正常收尾、2 小时长场、60–90 秒真实断网、真实离线到开播 WAIT 转换，以及真实事件的多锚点评论同步。两个房间连接期间都没有收到真实消息；按用户“没有就不强求”的要求保留此边界。合成测试、页面评论和转播不能替代这些结果，不承诺全平台小于 2 秒误差；不能把设计 R0–R5 全部标成已验收。

每阶段使用中文 Conventional Commits，README 不改动。已清除本轮媒体、原始前端资源、临时脚本、缓存、打包工具、测试构建目录与源码字节码；用户设计文档和原有模板改动保留。仓库只新增维护测试与脱敏验收记录。
