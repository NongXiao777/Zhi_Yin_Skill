# Verified interface notes, 2026-11-25

The installed application is 智赢跨境. The earlier chat called it 智慧跨境. The first inspected shortcut targeted `D:\ZYing\ZYing.exe` with working directory `D:\ZYing` and no arguments. A later running installation used `G:\ZYing\ZYing.exe`; use the configurable `--app` path. The application is .NET 6 WinForms with CefSharp, not an Electron app.

## Native startup

Static metadata and method-body inspection found `ZYing.Program.Main` calling `ZYing.Global.Start`. `Global.Start` reads the process argument array and passes its first extra argument to the startup form, where it flows into an internal token field. An internal overload launches this executable with a GUID argument. A `--BasePath` utility setting exists, but business CLI commands were not established. `Program.ReadLine` reads a supplied stream; a standard-input command loop was not established. Do not guess `--help` or Chromium debug flags on this executable.

## Existing window control

`window-status` finds visible top-level windows owned by the selected executable. `window-focus` activates an existing window with Windows APIs and verifies the foreground handle. Cross-thread activation is asynchronous, so a harmless `WM_NULL` message synchronizes with the target, followed by a bounded observation of foreground completion. Activation is issued once.

On 2026-11-25, an existing client window was successfully activated and returned `foreground=true` and `window_responding=true`. This does not verify login permissions or product calls, and it does not establish a CDP or application-specific control endpoint. The existing `launch` command's earlier startup observations remain separate from this activation check.

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

The subsequent 5.2.4 extension inspection established that `common.getPluginOrderDetail` calls `plugin.detail` at `https://erp.zying.net/api` for procurement/order details (`root`, `items`, `buys`). That operation is not a collected-product detail call. New collection uses `spider.insert` and `spider.ins` at `https://seller.zying.net/api`; Mercado Libre collection also has `MeliBest/Spider` and `MeliBest/SpiderUP`. These are creation/import routes, not verified existing-product updates. Earlier 5.2.1 definitions above are version-specific observations, not interchangeable endpoint mappings.

The 5.2.4 registered actions and dynamic-command whitelist did not expose `spider.detail` or `spider.update`. The confirmed desktop collected-product chain uses private TCP binary RPC. See [collected-product-api.md](collected-product-api.md) for exact field meanings, encoding and the remaining invocation boundary.

These are client-internal endpoints, not a confirmed public integration API. No credentials, cookies, business databases or authenticated API responses were read. The supplied script inspects source definitions and never sends a business API request.

For actual business automation, first verify one intended operation and its payload/response through the application's legitimate authenticated client. Prefer a supported API where available. A browser session can preserve its normal request signing without exposing a token to the model. Build one deterministic command per verified operation and cap both fields and rows in its response. Do not invent a generic POST wrapper that assumes unsigned requests work.

## Browser fallback

Public unauthenticated GET checks on 2026-11-20 returned HTTP 200 for `https://www.zying.net`, `https://erp.zying.net`, and `https://seller.zying.net`. The latter two expose web app entrypoints with Umi JavaScript bundles, so browser/DOM automation may support web-visible workflows. Equivalence with all desktop ERP functions is unverified.

The extension's localhost:1717 HTTP/WebSocket references are inside developer hot-reload code guarded by isDev/false conditions. They are not a production desktop control API. A CefSharp or Chrome/Edge CDP endpoint must be observed before claiming attach support; passing a guessed debugging flag to this executable is insufficient. A no-argument command-line launch was attempted on 2026-11-20; the initial inspection observed ZYing and no app-owned listening port. A later status check found no remaining process under the installation directory. Startup can be requested from the CLI, but a persistent, usable client session was not validated. This does not establish a CDP endpoint after login or after opening an embedded browser.

If browser automation is needed, a short local skill can use Microsoft `@playwright/cli` directly from PowerShell. The OpenAI Playwright skill is the smallest entrypoint among the three candidates inspected. Its bundled Bash wrapper needs adaptation for Windows. Avoid automatically installing unrelated browser skills or loading complete Electron guides for this CefSharp application.
