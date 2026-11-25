---
name: zhiying-cli
description: Use compact commands to inspect 智赢跨境, activate its Windows client, debug native product reads and variant surcharge plans, or summarize Amazon reports. Native writes require a validated session and an explicit product change.
---

Use `scripts/zhiying.py` with the available Python runtime. It returns compact JSON. Native session export requires PowerShell 7 and supplied Microsoft ClrMD dependencies; Brotli responses need the optional `brotli` package.

Commands:
- `status`: installed executable, running processes, app-owned listening ports, extension version.
- `launch`: start the existing executable, or report that it is already running.
- `window-status`: find existing windows belonging to the selected executable and report foreground state.
- `window-focus`: activate one existing client window and verify its response and foreground state.
- `routes --match amazon --limit 10`: inspect extension route definitions without HTTP requests.
- `traffic-summary --file report.json --limit 10`: summarize a supplied Sales and Traffic JSON report.
- Native product commands: `session-export`, `product-detail`, `product-plan`, `product-apply`, `product-restore`. Read [references/native-cli.md](references/native-cli.md) before using them.

Default installation: `D:\ZYing`; extension: `%LOCALAPPDATA%\ZYing\zying-ext.crx`. Override with `--app` or `--extension` before the subcommand.

If multiple windows match, choose a handle from `window-status` with `window-focus --window <integer handle>`; this option follows the subcommand.

The executable is a WinForms/CefSharp client. Its first argument is an internal startup identifier; do not pass arbitrary CLI flags. HTTP commands exist, but authentication and signing are required. Route discovery does not establish payload schemas or read-only behavior.

Window activation does not establish product permissions. Native product code is implemented, but the live detail request returned server error `-9`; successful product retrieval and saves remain unverified. Choose `sale` for the product list and `spider` for the collection list. Keep `money` (variant surcharge), `sale_cost` (cost), `sale_price` (distribution price), and final platform price distinct. Title is `sale_title`; description is `sale_intro`, both language JSON string columns. Read [references/collected-product-api.md](references/collected-product-api.md) for encoding evidence.

Keep session files and full product plans local. Apply only the specific change authorized in chat. A `write_attempted` plan may have reached the server; inspect or restore it instead of replaying. Preserve other variants and languages. Re-export the session after normal client login changes.

For Amazon workflows, read [references/amazon-organic.md](references/amazon-organic.md); use [references/interfaces.md](references/interfaces.md) for app details. Sales/Traffic reports measure all page traffic; revenue is not net profit. Business writes and stop-loss decisions need verified permissions, costs and user rules. Return only needed fields and bounded rows.
