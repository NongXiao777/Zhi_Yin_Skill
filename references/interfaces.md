# Verified interface notes, 2026-11-20

The installed application is 智赢跨境. The earlier chat called it 智慧跨境. The shortcut targets `D:\ZYing\ZYing.exe` with working directory `D:\ZYing` and no arguments. The application is .NET 6 WinForms with CefSharp, not an Electron app.

## Native startup

Static metadata and method-body inspection found `ZYing.Program.Main` calling `ZYing.Global.Start`. `Global.Start` reads the process argument array and passes its first extra argument to the startup form, where it flows into an internal token field. An internal overload launches this executable with a GUID argument. A `--BasePath` utility setting exists, but business CLI commands were not established. `Program.ReadLine` reads a supplied stream; a standard-input command loop was not established. Do not guess `--help` or Chromium debug flags on this executable.

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

For actual business automation, first verify one intended operation and its payload/response through the application's legitimate authenticated client. Prefer a supported API where available. A browser session can preserve its normal request signing without exposing a token to the model. Build one deterministic command per verified operation and cap both fields and rows in its response. Do not invent a generic POST wrapper that assumes unsigned requests work.

## Browser fallback

Public unauthenticated GET checks on 2026-11-20 returned HTTP 200 for `https://www.zying.net`, `https://erp.zying.net`, and `https://seller.zying.net`. The latter two expose web app entrypoints with Umi JavaScript bundles, so browser/DOM automation may support web-visible workflows. Equivalence with all desktop ERP functions is unverified.

The extension's localhost:1717 HTTP/WebSocket references are inside developer hot-reload code guarded by isDev/false conditions. They are not a production desktop control API. A CefSharp or Chrome/Edge CDP endpoint must be observed before claiming attach support; passing a guessed debugging flag to this executable is insufficient. A no-argument command-line launch was attempted on 2026-11-20; the initial inspection observed ZYing and no app-owned listening port. A later status check found no remaining process under the installation directory. Startup can be requested from the CLI, but a persistent, usable client session was not validated. This does not establish a CDP endpoint after login or after opening an embedded browser.

If browser automation is needed, a short local skill can use Microsoft `@playwright/cli` directly from PowerShell. The OpenAI Playwright skill is the smallest entrypoint among the three candidates inspected. Its bundled Bash wrapper needs adaptation for Windows. Avoid automatically installing unrelated browser skills or loading complete Electron guides for this CefSharp application.
