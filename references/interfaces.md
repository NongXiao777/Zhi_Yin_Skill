# Verified interface notes, 2026-11-25

The installed application is 智赢跨境. The earlier chat called it 智慧跨境. The on-host client uses `%LOCALAPPDATA%\Programs\ZYing\ZYing.exe` and was observed at normal Windows elevation. Older installations used `D:\ZYing\ZYing.exe`. Use `--app` before the subcommand to select an installation. The application is .NET 6 WinForms with CefSharp, not an Electron app.

## Native startup

Static metadata and method-body inspection found `ZYing.Program.Main` calling `ZYing.Global.Start`. `Global.Start` reads the process argument array and passes its first extra argument to the startup form, where it flows into an internal token field. An internal overload launches this executable with a GUID argument. A `--BasePath` utility setting exists, but business CLI commands were not established. `Program.ReadLine` reads a supplied stream; a standard-input command loop was not established. Do not guess `--help` or Chromium debug flags on this executable.

## Explicit window diagnostics

`window-status` reports existing visible windows for the selected executable. Use `window-focus` only when the user explicitly asks to activate one, and pass `--window` when multiple handles match. Window commands are independent of login, permissions and collected-product operations.

## HTTP commands

Installed Chrome extension `zying-ext.crx`, version 5.2.1, contains `assets/js/chunk-common.js` and `assets/js/background.js` with request definitions such as:

| Base | Command | Method | Evidence level |
|---|---|---|---|
| `https://seller.zying.net/api` | `plugin.select` | POST | Request definition only |
| `https://seller.zying.net/api` | `plugin.detail` | POST | Request definition only |
| `https://erp.zying.net/api` | `order.view` | POST | Request definition only |
| `https://erp.zying.net/api` | `users.detail` | POST | Request definition only |
| `https://erp.zying.net/api` | `shipper.shippers` | POST | Request definition only |

Path format is `/CmdHandler?cmd=<command>`. The transport serializes `data` with `JSON.stringify` and includes `token`, `appclient`, `timestamp`, `signature`, `version`, and `client_identify` headers. The signing helper is called with appClient `3` and version `v1.1`. Payload schemas and authenticated behavior were not validated. Command names alone do not establish whether an operation is read-only.

These client-internal endpoints were identified through static inspection. The `routes` command reads their source definitions locally. The separate Amazon commands use the official [SP-API](sp-api.md).

Extension 5.2.4 identifies `plugin.detail` as a procurement order operation and exposes collection creation/import routes. The installed 5.2.4 package did not surface the desktop `spider.detail` and `spider.update` commands. The desktop client uses internal binary TCP RPC. See [the collected-product API notes](collected-product-api.md).

For live integration, establish a vendor-supported or otherwise authorized transport, validate one existing-record read, then validate an authorized write by reading it back.

## Public web entrypoints

Public unauthenticated GET checks on 2026-11-20 returned HTTP 200 for `https://www.zying.net`, `https://erp.zying.net`, and `https://seller.zying.net`. The latter two expose separate web apps built with Umi JavaScript bundles. Access to the existing desktop collection data remains unverified.

The extension's localhost:1717 HTTP/WebSocket references are inside developer hot-reload code guarded by isDev/false conditions. They are not a production desktop control API. A CefSharp or Chrome/Edge CDP endpoint must be observed before claiming attach support; passing a guessed debugging flag to this executable is insufficient. A no-argument command-line launch was attempted on 2026-11-20; the initial inspection observed ZYing and no app-owned listening port. A later status check found no remaining process under the installation directory. Startup can be requested from the CLI, but a persistent, usable client session was not validated. This does not establish a CDP endpoint after login or after opening an embedded browser.

## Chrome 浏览器工作方式

完整默认顺序见 [默认浏览器流程](browser-workflow.md)：发现普通 Chrome → 请求并等待远程调试许可（已有许可复用）→ 提醒或尝试前台 → 选品和插件取数。未启用时，在同一 Chrome 的 `chrome://inspect/#remote-debugging` 由用户允许该实例远程调试；连接使用实际观察到的端点或 existing-browser / `--autoConnect`。

- 默认连接用户日常使用的普通 Chrome，复用现有窗口、登录状态和匹配标签。调用可能自动启动浏览器的 MCP 工具前，先确认它会连接该普通窗口。
- 没有运行中的普通 Chrome 时，按正常方式启动 Chrome，沿用用户的常规配置，再连接这个窗口。使用可用的浏览器连接器、`--autoConnect` 或已观察到的调试端点；遇到 Chrome 自身的接入确认时由用户处理。连接后复用同一会话，只有缺少匹配标签时才新开标签。
- 只有用户明确要求独立浏览器时，才可使用 MCP 启动的独立 Chrome、专用配置或 `--isolated` 临时浏览器。连接失败、没有调试端点或审批受阻时，说明具体阻碍，不自行切换到独立浏览器。
- 简短说明实际使用的 Chrome 窗口。如需登录或额外验证，请用户直接在选定窗口内完成。
- 连接后提醒用户保持 Chrome 打开，选品、采集和界面核验时默认尝试将目标标签带到前台。窗口最小化时尝试恢复，失败才提醒用户恢复。普通 API 读取无需持续将窗口置于前台。

## 浏览器产品脚本（默认）

默认方案和备选缺点见 [默认浏览器流程](browser-workflow.md)。插件 `extension-read` 调用在实际 `background.js` worker 的 `serviceWorkerId` 执行，不使用商品 `pageId`，不点弹窗或导出。链接或 JSON 导入见 [导入流程](aliexpress-import.md)，五个英文文案字段和批量加价见 [浏览器编辑](browser-product-edit.md)。`browser_call.py` 生成完整函数文件；保存后检查 `ok && verified`。

## 从浏览器采集到智赢

未指定平台时，商品选择和采集均默认速卖通。用户给出了其他平台的商品或链接时按该商品处理。先对照当前商品标题及来源 SKU、ASIN 或速卖通 ID。使用浏览器快照定位可见控件，只有用户授权将该商品采集入库后才点击会提交数据的控件。

- 亚马逊商品页的智赢 5.2.5 面板中有「采集到智赢」。单击会进行防重检查并直接尝试写入采集列表。收到成功提示后，在智赢「产品 → 产品采集 → 采集列表」核对来源商品和智赢编号。已采集提示应先读现有记录。需要进入「我的产品」时才执行另一个「导入主库」动作。
- 速卖通默认使用本 skill 的采集助手 0.2.0 后台 API，直接取得 JSON 后填写网页 New 或按授权创建服务器采集产品；不依赖厂商扩展是否注入采集按钮。只有选择 exe 内嵌浏览器备选时，才通过「单个采集」打开同一链接并按 [缓存读取](collection-cache.md) 读 New 的来源数据。New 尚无真实编号，上传后必须从同源服务器读回数字 ID。

## 网页表单备用方式

默认使用 [浏览器编辑](browser-product-edit.md) 的生成器及 read/preview/apply/verify。确实需要操作脚本尚未覆盖的控件时，在同一已登录标签按编号筛选并打开唯一匹配商品，核对抽屉的真实产品编号，再用当前页面快照定位控件。五个英文文案字段和批量变体加价已经由脚本覆盖，无需手工拼接旧 helper。

页面操作前提醒或尝试前台，保留其他语言和全部变体。遇到无关必填项时说明该表单方式的限制，优先回到已有脚本支持的方案；保存后仍通过同源数字编号读回，不能只凭页面提示确认。没有保存编号的 New 按导入流程处理。
