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

- 默认连接用户日常使用的普通 Chrome，复用现有窗口、登录状态和匹配标签。调用可能自动启动浏览器的 MCP 工具前，先确认它会连接该普通窗口。
- 没有运行中的普通 Chrome 时，按正常方式启动 Chrome，沿用用户的常规配置，再连接这个窗口。使用可用的浏览器连接器、`--autoConnect` 或已观察到的调试端点；遇到 Chrome 自身的接入确认时由用户处理。连接后复用同一会话，只有缺少匹配标签时才新开标签。
- 只有用户明确要求独立浏览器时，才可使用 MCP 启动的独立 Chrome、专用配置或 `--isolated` 临时浏览器。连接失败、没有调试端点或审批受阻时，说明具体阻碍，不自行切换到独立浏览器。
- 简短说明实际使用的 Chrome 窗口。如需登录或额外验证，请用户直接在选定窗口内完成。
- 连接后告知用户在浏览器任务完成前保持选定的 Chrome 窗口打开。助手复用同一连接和窗口；需要界面操作或可视核验时，提醒用户保持窗口显示、不要最小化。普通 API 读取无需持续将窗口置于前台。
