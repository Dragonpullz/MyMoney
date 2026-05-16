# Showshare Improvement Plan

This repo is currently a personal-finance analysis workspace, not a full app yet. It has:

- BankSync MCP config in `.vscode/mcp.json`
- Repo guidance in `.github/copilot-instructions.md`
- PowerShell analysis scripts in `.banksync-analysis/`
- Generated text snapshots: `report.txt` and `focused.txt`
- A reusable query script: `query.ps1`

The product intent is bigger than ad-hoc spend questions: analyze spending patterns, find improvement opportunities, project future spend, create useful visualizations, and surface odd transactions or patterns. The plan below is ordered to improve token efficiency first, then analytical quality, then presentation.

## Key Corrections From Repo Review

1. **PowerShell cannot call MCP tools directly.** The BankSync MCP tools are available to the AI agent, not to local PowerShell scripts. Any plan that says `Refresh-Cache.ps1` will call `mcp_banksync_get_transactions` directly is wrong unless a separate local BankSync API client is added later.
2. **The right split is agent fetch -> local import.** The agent should fetch transactions with MCP and save/record result JSON paths. Local scripts should import those JSON files into a persistent cache, normalize, summarize, query, and report.
3. **House Checking is the default reporting scope.** This is already in `.github/copilot-instructions.md` and `query.ps1`. Future tooling should preserve that default unless the user asks for all accounts or a specific account.
4. **`query.ps1` is useful but too chatty.** It always prints merchant and transaction details, which is good for debugging but expensive for normal answers.
5. **Generated snapshots should not become the data source.** `report.txt` and `focused.txt` are useful historical outputs, but future scripts should use cached normalized transactions and generated summaries.

## North-Star Workflows

The repo should converge on these repeatable workflows:

1. **Refresh data:** agent fetches BankSync transactions, local script imports them into `.banksync-cache/`.
2. **Answer quick spend questions:** use small pre-aggregated summary files when possible; fall back to `query.ps1` for details.
3. **Run monthly digest:** cashflow, savings rate, category drift, subscriptions, anomalies, projections, and recommendations.
4. **Investigate:** drill from summary -> category -> merchant -> transaction list.
5. **Visualize:** generate Markdown/HTML reports with charts from cached summaries.

## Phase 1: Persistent Cache and Import Pipeline

### Goal

Stop re-pulling and re-reading giant VS Code session JSON files for every question.

### Proposed Files

```text
.banksync-cache/                 # gitignored
  manifest.json                  # accounts, covered ranges, fetch timestamps
  raw/
    <accountId>/<fetchId>.json   # raw MCP result files copied from chat-session-resources
  normalized.jsonl               # deduped, normalized, one txn per line
  summary.json                   # compact rollups for fast answers
```

### Correct Implementation Shape

The AI agent does the MCP-only part:

1. Call `mcp_banksync_get_transactions` with `workspaceId`, `bankId`, `accountId`, `from`, and `to`.
2. Record the resulting `content.json` paths.
3. Run a local import script with those paths.

Local PowerShell does the repeatable part:

```powershell
.\.banksync-analysis\Import-BankSyncDump.ps1 -Files <content.json paths> -FetchLabel 2026-05-16
.\.banksync-analysis\Build-Summary.ps1
```

`Import-BankSyncDump.ps1` should:

- Copy raw MCP JSON files into `.banksync-cache/raw/`.
- Normalize transactions into a stable schema.
- Dedup by `id`.
- Preserve `accountId`, `accountName`, `bankId`, `pending`, `merchantName`, `category`, `debitAmount`, `creditAmount`, and original raw date.
- Add derived fields: `localDate`, `month`, `year`, `direction`, `normalizedMerchant`, `isTransfer`, `isCcPayment`.

### Token Win

Once the cache exists, most questions can use `.banksync-cache/summary.json` or a small filtered JSON response from `query.ps1`, instead of pulling fresh MCP results or reading raw transaction dumps into chat.

## Phase 2: Tighten `query.ps1`

### Current State

`query.ps1` already handles:

- Category presets and regex matching
- Date windows
- House Checking default account
- `-AllAccounts`
- `-Income`
- Deduping by transaction `id`
- Total, by-month, by-merchant, and transaction output

### Recommended Changes

Add output controls:

```powershell
.\query.ps1 -Category gas -From 2026-02-01 -To 2026-05-01
.\query.ps1 -Category gas -From 2026-02-01 -To 2026-05-01 -ByMerchant
.\query.ps1 -Category gas -From 2026-02-01 -To 2026-05-01 -Detailed
.\query.ps1 -Category gas -From 2026-02-01 -To 2026-05-01 -Format Json
```

Default output should be concise:

- Total
- Transaction count
- Date range
- Account scope
- By-month breakdown

Only print merchants with `-ByMerchant`, and only print raw transactions with `-Detailed`. `-Format Json` should return a compact object the agent can parse without table formatting.

Also allow cache defaults:

```powershell
param(
    [string[]]$Files,
    [string]$CachePath = '.\.banksync-cache\normalized.jsonl'
)
```

If `-Files` is omitted and the cache exists, use the cache. This makes normal calls shorter and less error-prone.

## Phase 3: Semantic Layer

Plaid categories are useful but not enough for household analysis. Add a small rules file that defines virtual categories and exclusions.

### Proposed File

`.banksync-analysis/rules.json`

```json
{
  "defaultAccountId": "P45rzOvVJ7uA59M1o3REU5gvZvmzQ7Igk6yM9",
  "virtualCategories": {
    "Dining Out": ["Food And Drink Restaurant", "Food And Drink Fast Food", "Food And Drink Coffee"],
    "Groceries": ["Food And Drink Groceries"],
    "Gas": ["Transportation Gas"],
    "Pets": ["Medical Veterinary Services", "General Merchandise Pet Supplies"],
    "Housing": ["Loan Payments Mortgage Payment", "Rent And Utilities", "Home Improvement"]
  },
  "excludeFromHouseholdSpend": [
    "Loan Payments Credit Card Payment",
    "Transfer In",
    "Transfer Out"
  ],
  "merchantAliases": {
    "AMAZON MKTPL": "Amazon",
    "IC* INSTACART": "Instacart",
    "SHELL": "Shell"
  }
}
```

Why this matters:

- Enables meaningful categories like `Dining Out`, `Pets`, `House`, `Subscriptions`, and `Discretionary`.
- Stops one-off regex logic from spreading across scripts.
- Makes projections and anomaly detection compare like with like.

## Phase 4: Summary Files for Fast Answers

Generate `.banksync-cache/summary.json` from normalized transactions.

Suggested shape:

```jsonc
{
  "generatedAt": "2026-05-16T18:00:00-07:00",
  "range": { "from": "2025-08-01", "to": "2026-05-16" },
  "scopeDefaults": { "accountId": "P45rzOvVJ7uA59M1o3REU5gvZvmzQ7Igk6yM9", "accountName": "House Checking" },
  "monthly": {
    "2026-04": {
      "spend": 10494.82,
      "income": 14548.52,
      "net": 4053.70,
      "savingsRate": 0.2786,
      "byCategory": { "Transportation Gas": 308.84 },
      "byVirtualCategory": { "Dining Out": 980.22 },
      "topMerchants": [{ "merchant": "Chevron", "total": 152.15, "count": 1 }]
    }
  },
  "recurring": [],
  "anomalies": []
}
```

Answering strategy:

- Use `summary.json` for totals, trend questions, and quick comparisons.
- Use `query.ps1 -Format Json -Detailed` only when the user asks for transactions.
- Use MCP only when the cache is missing or stale.

## Phase 5: Analysis Features

### Cashflow and Savings Rate

Add `Get-MonthlyCashflow.ps1` or a cmdlet in a module:

```powershell
Get-MonthlyCashflow -Months 12 [-AllAccounts] [-Household]
```

Output:

- Month
- Income
- Spend
- Net
- Savings rate
- 3-month rolling averages
- YTD totals

This should become the default "how are we doing?" view.

### Subscription Audit

Promote the recurring-charge heuristic from `analyze.ps1` into `Find-Subscriptions.ps1`.

Detect:

- Monthly recurring merchants
- Annualized cost
- Price increases
- Dormant subscriptions
- Duplicate overlapping services

### Opportunity Finder

Create `Find-Opportunities.ps1` that ranks potential improvements by estimated annual impact.

Examples:

- Restaurants/fast food/coffee above recent baseline
- Instacart vs. in-store grocery delta
- Expensive recurring telecom/insurance/utilities
- Bank fees or interest charges
- Gas merchant comparison
- Merchants with rising average ticket size

Output should be practical: `Opportunity`, `Evidence`, `EstimatedMonthlyImpact`, `Confidence`, `SuggestedNextAction`.

### Projections

Create `Project-Spend.ps1`:

```powershell
Project-Spend -Category dining -MonthsBack 12 -MonthsForward 6
Project-Spend -Total -MonthsForward 12
```

Methods:

- 3-month average
- 12-month average where history exists
- Simple linear trend over the last 6 months
- Confidence band: mean +/- 2 standard deviations
- Month-to-date run-rate projection for current month

Keep it explainable. For household finance, a transparent forecast is more useful than a black-box model.

### Anomaly Detection

Create `Find-Anomalies.ps1` with rules:

| Rule | Why it matters |
|---|---|
| Merchant charge > merchant average + 2 standard deviations | Price jump or unusual purchase |
| Same merchant and amount on same day | Possible duplicate charge |
| First charge from a new merchant over threshold | Worth reviewing |
| Recurring charge increased by >10% | Subscription or bill hike |
| Day total above normal day average + 2 standard deviations | Unusual spending burst |
| Any bank fee or interest charge | Avoidable cost |
| Refund/charge pair within 7 days | Return or failed transaction pattern |

Each anomaly should include `severity`, `date`, `merchant`, `amount`, `reason`, and `suggested action`.

### Household Spend Reconciliation

Defaulting to House Checking avoids double-counting credit-card payments, but it hides Visa-category spend when the card is actually used for purchases. Build a real household-spend view:

- Include checking debits except credit-card payments and transfers.
- Include credit-card purchase debits.
- Exclude credit-card payment credits.
- Keep savings transfers out of spend by default.

This lets future reports use all accounts accurately instead of relying on House Checking as a proxy.

## Phase 6: Visualizations and Reports

### Option A: Markdown Reports With Mermaid

Add `Build-MonthlyReport.ps1`:

```powershell
Build-MonthlyReport -Month 2026-04
```

Output: `.banksync-analysis/reports/2026-04.md`

Sections:

- Cashflow summary
- Top category changes vs. 3-month average
- Top merchants
- Subscription audit
- Anomalies
- Projection update
- Suggested actions
- Mermaid charts for monthly spend and category mix

This is the fastest visualization path with no dependencies.

### Option B: Local HTML Dashboard

If this becomes more app-like, generate `reports/dashboard.html` from `summary.json` using static HTML + Chart.js. No server required, good charts, easy to open locally.

Recommended charts:

- Monthly income/spend/net lines
- Stacked category spend by month
- Dining/grocery/gas sparklines
- Subscription annualized-cost table
- Anomaly timeline
- Calendar heatmap of daily spend

### Option C: Python Charts

Python/matplotlib or Plotly is useful if the dashboard needs PNG exports or richer statistical charts. Defer until the cache and summaries are stable.

## Phase 7: Repo Hygiene

### Add `.gitignore`

```gitignore
.banksync-cache/
.banksync-analysis/reports/
*.session.json
```

### Treat Output Files as Generated

Decide whether `report.txt` and `focused.txt` should stay tracked. If they are just snapshots, either:

- Move them under `.banksync-analysis/reports/`, or
- Keep one canonical example and gitignore future generated reports.

### README

Add a short `README.md` for human usage:

- What this repo is
- How Copilot uses `.github/copilot-instructions.md`
- How to refresh data with the agent
- How to import MCP dumps
- Common queries
- How to generate monthly reports

### Secret Handling

The repo is personal-use only, but `.vscode/mcp.json` contains a live API key. It is acceptable for local use, but future-proofing options are:

- Move the key to a VS Code input variable.
- Read from an environment variable if MCP config supports it.
- Keep as-is but avoid publishing the repo.

Do not spend time here before the cache/reporting work unless sharing or backup risk changes.

### PowerShell Module

Once scripts stabilize, extract common functions into `.banksync-analysis/BankSync.Analysis.psm1`:

- `Read-BankSyncTransactions`
- `ConvertTo-NormalizedTransaction`
- `Resolve-CategoryPreset`
- `Get-CategorySpend`
- `Get-MonthlyCashflow`
- `Find-Subscriptions`
- `Find-Anomalies`

This reduces duplication across `query.ps1`, `analyze.ps1`, and future reports.

### Validation

Add `Test-BankSyncData.ps1`:

- Detect duplicate IDs.
- Confirm required fields exist.
- Warn on missing `merchantName`, missing category, negative debit/credit values.
- Check whether expected months/accounts are represented.
- Report stale cache age.

Balance reconciliation is nice later, but may be hard because transaction windows and posted balances do not always line up cleanly.

### Timezone Normalization

The API returns UTC timestamps like `2026-04-23T00:00:00.000Z`. Normalize to local date once during import to avoid month-boundary surprises.

## Helpful Ideas Not Yet in the Repo

- **Decision log:** track actions like canceling a subscription or changing grocery habits. Reports can then explain why spending changed.
- **What-if calculator:** estimate annual savings from cutting a merchant, reducing a category by X%, or switching from delivery to in-store grocery.
- **Lifestyle creep metric:** discretionary spend as a percentage of income over time.
- **Merchant normalization:** collapse `Instacart Instacart.comca`, raw descriptions, and merchant aliases into stable names.
- **Pet and house sub-ledgers:** virtual categories for recurring household themes that Plaid categories split across many buckets.
- **Bill renegotiation watchlist:** telecom, insurance, utilities, and subscriptions where the monthly charge is high or rising.
- **Tax/export view:** yearly CSV grouped by category and merchant, with a blank `TaxNote` column for manual annotation.
- **Monthly digest prompt:** `.github/prompts/monthly-digest.prompt.md` that instructs Copilot to refresh if needed, build the report, and summarize the top findings.

## Recommended Execution Order

1. **Add `.gitignore`.** Protect cache and generated reports from accidental commits.
2. **Build `Import-BankSyncDump.ps1`.** Copy MCP JSON dumps into `.banksync-cache/`, normalize, dedup, and write `normalized.jsonl`.
3. **Update `query.ps1`.** Default to cache, add `-Format Json`, `-ByMerchant`, and `-Detailed`.
4. **Build `Build-Summary.ps1`.** Generate `summary.json` for fast answers.
5. **Add semantic rules.** Create `rules.json` for virtual categories, exclusions, merchant aliases, and default account behavior.
6. **Build core analytics.** Cashflow, subscriptions, anomalies, and opportunities.
7. **Build projections.** Category and total-spend forecasts using transparent averages/trends.
8. **Build monthly report.** Markdown first; dashboard later if useful.
9. **Extract module functions.** Refactor once patterns stabilize.

This order keeps each step useful on its own and attacks the biggest friction first: re-fetching large transaction dumps and making the agent reason over raw data instead of compact summaries.
