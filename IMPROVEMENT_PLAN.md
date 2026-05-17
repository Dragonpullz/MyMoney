# MyMoney Improvement Plan

This repo is a private personal-finance analysis workspace. It is not a full app yet. The active implementation is Python-first and centered on BankSync transaction data, a local cache, and repeatable command-line reports.

## Current Components

- BankSync MCP configuration in `.vscode/mcp.json`; VS Code prompts for the API key and sends it as `X-API-Key`.
- Copilot operating guidance in `.github/copilot-instructions.md`; default fetch and reporting scope is House Checking.
- Python analysis tools under `.banksync-analysis/`.
- Shared Python package under `.banksync-analysis/banksync_analysis/`.
- Semantic rules in `.banksync-analysis/rules.json`.
- Optional monthly budgets in `.banksync-analysis/budgets.json`.
- Ignored local cache under `.banksync-cache/`.

## Operating Model

The agent does the MCP-only part:

1. Fetch BankSync transactions with `workspaceId`, `bankId`, `accountId`, `from`, and `to`.
2. Default to House Checking only unless the question explicitly asks for broader scope or the result is clearly implausible.
3. Record the generated `content.json` paths.

Local Python does the repeatable part:

```bash
python3 .banksync-analysis/Import-BankSyncDump.py -Files <content.json paths> -FetchLabel 2026-05-16
python3 .banksync-analysis/Build-Summary.py
```

Most follow-up questions should use the cache instead of fetching fresh data:

```bash
python3 .banksync-analysis/query.py -Category gas -From 2026-02-01 -To 2026-05-01
python3 .banksync-analysis/query.py -Category groceries -From 2026-04-01 -To 2026-05-01 -ByMerchant
python3 .banksync-analysis/Get-MonthlyCashflow.py -Months 6
python3 .banksync-analysis/Get-BudgetStatus.py -Month 2026-05
```

Use `-Format json` when another script or the agent needs compact machine-readable output.

## Implemented Command Surface

- `query.py`: category/regex/date/account queries over cached transactions or raw MCP dumps.
- `Import-BankSyncDump.py`: copies raw MCP dumps into `.banksync-cache/raw/`, normalizes, dedupes, and writes `normalized.jsonl` plus `manifest.json`.
- `Build-Summary.py`: builds `.banksync-cache/summary.json` with monthly cashflow, virtual categories, and top merchants.
- `Get-MonthlyCashflow.py`: monthly spend, income, net, savings rate, rolling averages, and YTD totals.
- `Get-BudgetStatus.py`: current/prior/projected spend against configured monthly budgets.
- `Find-Subscriptions.py`: recurring merchant detection.
- `Find-Anomalies.py`: outlier, duplicate, fee, new-merchant, and refund/charge checks.
- `Find-Opportunities.py`: ranks estimated savings opportunities.
- `Project-Spend.py`: projects spend/income/net or category trends.
- `Build-MonthlyReport.py`: writes a Markdown monthly report.
- `analyze.py`: raw-dump overview for ad hoc inspection.

## Current Gaps

1. The local cache is still tiny fixture-style data: House Checking only, 5 transactions, April 2026. Subscription, anomaly, opportunity, and projection output will not be meaningful until real multi-month data is imported.
2. There is no local BankSync sync client yet. Fresh data still requires the agent to call MCP, then local Python imports the resulting dump.
3. `query.py -Files` reads raw dumps directly and assumes the fields needed for querying are present. The preferred path is still import first, query cache second.
4. `banksync_analysis/commands.py` still contains renamed `_legacy_*` implementations from the Python conversion. They no longer shadow public functions, but should be removed once the active functions have broader parity coverage.

## Next Work

1. Refresh real House Checking data for a useful date range, import it, rebuild summary, and rerun all smoke commands.
2. Add a small smoke test that imports fixture data into a temp cache, builds summary, and validates the key CLI wrappers.
3. Remove the `_legacy_*` implementations from `commands.py` after the smoke test protects current behavior.
4. Add broader real-data parity checks for all-accounts mode and Tim Visa when explicitly requested.
5. Stretch: build a local BankSync sync client so the agent fetch step is no longer required.
