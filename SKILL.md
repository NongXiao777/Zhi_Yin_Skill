---
name: zhiying-cli
description: Inspect 智慧跨境/智赢跨境 interfaces and summarize Amazon traffic reports with compact local commands. Use for low-token CLI investigation and Amazon natural-traffic workflows without computer use.
---

Use `scripts/zhiying.py` with the available Python runtime. It uses only the standard library and returns compact JSON.

Commands:
- `status`: installed executable, running processes, app-owned listening ports, extension version.
- `launch`: start the existing executable, or report that it is already running.
- `routes --match amazon --limit 10`: inspect extension route definitions without HTTP requests.
- `traffic-summary --file report.json --limit 10`: summarize a supplied Sales and Traffic JSON report.

Default installation: `D:\ZYing`; extension: `%LOCALAPPDATA%\ZYing\zying-ext.crx`. Override with `--app` or `--extension` before the subcommand.

The executable is a WinForms/CefSharp client. Its first argument is an internal startup identifier; do not pass arbitrary CLI flags. HTTP commands exist, but authentication and signing are required. Route discovery does not establish payload schemas or read-only behavior. This helper does not execute business commands.

For authenticated automation, read [references/amazon-organic.md](references/amazon-organic.md); use [references/interfaces.md](references/interfaces.md) for app details. Current focus is Amazon natural traffic. Sales/Traffic reports measure all page traffic; revenue is not net profit. Business writes and stop-loss decisions need verified permissions, costs and user rules. Return only needed fields and bounded rows.
