---
name: zhiying-cli
description: Inspect 智赢跨境 interfaces, find or activate its existing Windows client window, and summarize Amazon traffic reports with compact local commands. Use for CLI investigation and Amazon natural-traffic workflows.
---

Use `scripts/zhiying.py` with the available Python runtime. It uses only the standard library and returns compact JSON.

Commands:
- `status`: installed executable, running processes, app-owned listening ports, extension version.
- `launch`: start the existing executable, or report that it is already running.
- `window-status`: find existing windows belonging to the selected executable and report foreground state.
- `window-focus`: activate one existing client window and verify its response and foreground state.
- `routes --match amazon --limit 10`: inspect extension route definitions without HTTP requests.
- `traffic-summary --file report.json --limit 10`: summarize a supplied Sales and Traffic JSON report.

Default installation: `D:\ZYing`; extension: `%LOCALAPPDATA%\ZYing\zying-ext.crx`. Override with `--app` or `--extension` before the subcommand.

If multiple windows match, choose a handle from `window-status` with `window-focus --window <integer handle>`; this option follows the subcommand.

The executable is a WinForms/CefSharp client. Its first argument is an internal startup identifier; do not pass arbitrary CLI flags. HTTP commands exist, but authentication and signing are required. Route discovery does not establish payload schemas or read-only behavior.

Window activation does not establish login, product permissions or a callable business API. For collected-product details or variant surcharge, read [references/collected-product-api.md](references/collected-product-api.md). Product reads and writes are not implemented; keep `money` (variant surcharge), `sale_cost` (cost) and `sale_price` (distribution price) distinct.

For Amazon workflows, read [references/amazon-organic.md](references/amazon-organic.md); use [references/interfaces.md](references/interfaces.md) for app details. Sales/Traffic reports measure all page traffic; revenue is not net profit. Business writes and stop-loss decisions need verified permissions, costs and user rules. Return only needed fields and bounded rows.
