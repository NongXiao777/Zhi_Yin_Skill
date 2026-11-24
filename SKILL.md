---
name: zhiying-cli
description: Diagnose 智赢跨境, preview product and pricing drafts from local data, and run compact Amazon seller commands.
---

Run `scripts/zhiying.py` with Python 3.9+ and use `<command> --help` for flags. Return only the fields and rows needed.

- Local app diagnostics and launch use `status`, `launch`, or `routes`. Read [interfaces.md](references/interfaces.md) for client details.
- For local ERP product tables, use `erp-product-get` to select by product number and `erp-draft-preview` to review package fields and variant prices. Read [erp-products.md](references/erp-products.md) for columns and rules.
- A downloaded Sales and Traffic JSON uses `traffic-summary --file report.json`. Filter by `--asin` or `--sku`, or use `--by date` for the report's date aggregates.
- Online Amazon operations use `listing-get`, `listing-preview`, `fba-inventory`, `report-create`, `report-status`, or `report-summary`. Read [sp-api.md](references/sp-api.md) for credentials, roles and examples. Preview validates a draft without publishing. Create a report only when asked to request new data.

For traffic interpretation or connector research, read [amazon-organic.md](references/amazon-organic.md). Sales and Traffic covers all page traffic. Profit and stop-loss decisions require costs, fees and the seller's thresholds.
