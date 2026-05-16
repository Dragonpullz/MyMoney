---
description: Repo-level guidance for Copilot when answering BankSync / personal-finance questions in this workspace.
---

# Showshare — Copilot base prompt

**Personal use only.** This is a private, single-user workspace (Tim Wren) — not shared, not published, no collaborators. Don't worry about scrubbing IDs, balances, account numbers, or merchant names from chat output; everything in here is already mine. The `X-API-Key` in `.vscode/mcp.json` is also fine to reference — just don't paste it into web requests or non-local tools.

This repo is a personal-finance analysis workspace. There is no application code — only PowerShell scripts under `.banksync-analysis/` and a BankSync MCP server configured in `.vscode/mcp.json`. Most questions will be of the form "how much did I spend on X" / "show me Y category over period Z".

## How this file gets used

This file lives at `.github/copilot-instructions.md`, which VS Code Copilot auto-loads into every chat request for this workspace (as long as `github.copilot.chat.codeGeneration.useInstructionFiles` is `true`, which is the default). You should not need to be told to read it — it is already in context. Treat the rules below as standing orders for this repo.

## Workflow for any spend / income question

1. Pull transactions with the `banksync` MCP tools (see "Tool gotchas" below) using `from`/`to`. **Default: one call for House Checking only.** Only add calls for Tim Visa / Tim Checking / House Savings if the user explicitly asks for broader scope ("across all accounts", "include the credit card", etc.) or if a House-Checking-only answer comes back empty/implausible and another account is the obvious place to look. The large results are written to JSON files; record those paths.
2. Run `.banksync-analysis/query.ps1 -Files <paths> -Category <preset|regex> -From <YYYY-MM-DD> -To <YYYY-MM-DD>` to filter and summarize. Do not try to filter at the API level (it doesn't support category / merchant / amount filters).
3. Report the result inline (total, by-month, by-merchant). If the question is unusual enough to warrant a new dedicated script, save it under `.banksync-analysis/`; otherwise reuse `query.ps1`.

## Cached IDs (Tim Wren's Workspace, Bank of America via Plaid)

Skip `list_workspaces` / `list_banks` / `list_accounts` unless something has changed.

- workspaceId: `DjW6KwTR8nEYLRNBUcPP`
- bankId (BofA, Plaid): `AL76zwYZPAcxEX48wRprHOZoXz8rnMHNQz90J`
- Accounts:
  - Tim Visa (credit_card) — `3oZYpjb34MsPqyEe5jYpsbnL5LX7yJUV8kveg`
  - House Checking (checking) — `P45rzOvVJ7uA59M1o3REU5gvZvmzQ7Igk6yM9` *(most spending lives here)*
  - Tim Checking (checking) — `qLynAKEeM7cMn8XBa4jVFp4gZgARmNIqXMjaM`
  - House Savings (savings) — `BDZmzLd5qvsJZKMNg8krUXqm1mErxPCgoXDxE`

Re-verify with `list_accounts` (which **requires** `bankId`) if a query returns nothing unexpected.

### Default account

Unless the user says otherwise, **default everything to House Checking only** (`P45rzOvVJ7uA59M1o3REU5gvZvmzQ7Igk6yM9`) — both the MCP fetch *and* the report scope. That's where day-to-day household spending lives, and it avoids double-counting CC-payment transfers between Tim Visa and House Checking. Tim Checking and House Savings are almost never the right scope.

Escalate to broader scope only when the user asks for it ("across all accounts", "include the credit card", "include savings", etc.) or when a House-Checking-only answer is empty/implausible and another account is the obvious next place to look. When broader scope is needed, make additional MCP calls for just the relevant accounts and pass `-AllAccounts` to `query.ps1` (or override `-AccountId`). **Do not pre-fetch all 4 accounts "just in case."**

## Tool gotchas (learned the hard way)

### `mcp_banksync_get_transactions`

Accepted params **only**: `workspaceId`, `bankId`, `accountId`, `cursor`, `from`, `to`. Anything else (`category`, `limit`, `startDate`, `endDate`, `merchantName`, `accountName`) → `must NOT have additional properties`.

For historical / multi-month analysis on Plaid banks, **use `from`/`to` (YYYY-MM-DD)**. Do **not** chain `cursor` — incremental cursor sync frequently returns empty `transactions[]` with `hasMore: true` for many pages and is the wrong shape for bulk pulls.

One call per account, and by default the only account is House Checking. Spending across the household lives almost entirely there; Tim Visa is the only other meaningful spend account, and only pull it when the user explicitly asks for credit-card or all-accounts scope. Ignore Tim Checking and House Savings for spend questions unless asked.

### `mcp_banksync_list_accounts`

Requires `bankId` (not just `workspaceId`). Returns balance + creditLimit too.

### Large tool results

Result payloads above ~10 KB are written to a file:
`C:\Users\timwr\AppData\Roaming\Code - Insiders\User\workspaceStorage\<hash>\GitHub.copilot-chat\chat-session-resources\<session>\toolu_*\content.json`

Read them with `read_file` or aggregate via PowerShell:

```powershell
$d = Get-Content $path -Raw | ConvertFrom-Json
$d.transactions    # always under `.transactions`
```

## Category vocabulary

Categories are Plaid-style Title Case with spaces. Match with `-match` for substring filtering.

| Topic | Category string |
|---|---|
| Gas / fuel | `Transportation Gas` |
| Groceries | `Food And Drink Groceries` |
| Restaurants | `Food And Drink Restaurant` |
| Fast food | `Food And Drink Fast Food` |
| Coffee | `Food And Drink Coffee` |
| Utilities | `Rent And Utilities Gas And Electricity`, `Rent And Utilities Telephone` |
| Mortgage | `Loan Payments Mortgage Payment` |
| CC payments | `Loan Payments Credit Card Payment` |
| Insurance | `General Services Insurance` |
| Pharmacy | `Medical Pharmacies And Supplements` |
| Vet | `Medical Veterinary Services` |
| Amazon-ish | `General Merchandise Online Marketplaces` |

For anything not in this table (charity, healthcare specialties, travel, fees, etc.), consult `.banksync-analysis/categories.txt` — the full Plaid vocabulary lives there so it doesn't bloat every chat turn.

## Canonical query: `.banksync-analysis/query.ps1`

Use this for every spend / income question instead of writing one-off scripts.

```powershell
.\query.ps1 [-Files <paths>] [-Category <preset|regex>] [-From YYYY-MM-DD] [-To YYYY-MM-DD]
            [-AccountId <id> | -AllAccounts] [-Income] [-Top <n>]
            [-ByMerchant] [-Detailed] [-Format text|json]
```

Key behavior:

- **Reads `.banksync-cache\normalized.jsonl` by default.** Pass `-Files <content.json paths>` to query raw MCP dumps directly (skip the importer); pass nothing to use the cache. Run `Import-BankSyncDump.ps1` after a fresh MCP fetch to populate the cache.
- **Defaults to House Checking** (override with `-AccountId` or `-AllAccounts`).
- **`-Category` accepts a preset name** (gas, groceries, restaurants, fastfood, coffee, dining, utilities, electricity, internet, mortgage, ccpayments, insurance, pharmacy, vet, amazon, subscriptions, transfers, income) **or a raw regex**.
- Default date window: last 90 days, ending tomorrow (so "today" is included). `-To` is **exclusive**.
- `-Income` sums `creditAmount` instead of `debitAmount` (use for income / refunds / transfers in).
- Default output is concise: total + by-month only. Add `-ByMerchant` for merchant breakdown, `-Detailed` for full transaction list.
- `-Format json` emits one compact JSON object (suppresses all human output) — use this when the agent needs to parse the result.
- Dedupes by transaction `id`.

Time-slice cheatsheet (calculate the dates yourself based on the current date in context):

| User says | From | To |
|---|---|---|
| "last 3 months" | first of month, 3 months back | first of current month |
| "this month" | first of current month | first of next month |
| "last month" | first of previous month | first of current month |
| "YTD" | Jan 1 current year | tomorrow |
| "last year" | Jan 1 previous year | Jan 1 current year |
| "Feb-Apr 2026" | 2026-02-01 | 2026-05-01 |

Example invocations:

```powershell
# "How much on gas the last 3 months?" (Feb/Mar/Apr 2026, House Checking from cache)
.\query.ps1 -Category gas -From 2026-02-01 -To 2026-05-01

# "All grocery spend including the credit card last month" — needs broader scope
# Fetch the relevant accounts first, then:
.\query.ps1 -Files $g -Category groceries -From 2026-04-01 -To 2026-05-01 -AllAccounts

# "Income this year so far" — keep it readable with merchant breakdown
.\query.ps1 -Category income -From 2026-01-01 -Income -ByMerchant

# Agent consumption: one JSON object, machine-parseable
.\query.ps1 -Category gas -From 2026-02-01 -To 2026-05-01 -ByMerchant -Format json

# Custom regex when no preset fits, plus full transaction list
.\query.ps1 -Category 'Online Marketplaces|Superstores' -From 2026-02-01 -To 2026-05-01 -Detailed
```

Transaction shape worth knowing: `id`, `date` (ISO UTC), `description`, `merchantName` (nullable), `amount` (signed), `debitAmount` / `creditAmount` (absolute), `category`, `accountName`, `accountId`, `bankId`, `pending`.

## Other scripts under `.banksync-analysis/`

- `query.ps1` — **canonical**; see above.
- `Import-BankSyncDump.ps1` — copies MCP transaction JSON dumps into `.banksync-cache/` (raw + normalized JSONL + manifest). Run after a fresh MCP fetch: `.\Import-BankSyncDump.ps1 -Files <content.json paths>`.
- `Build-Summary.ps1` — rolls the normalized cache into `.banksync-cache/summary.json` (per-account, per-month spend/income/net/savingsRate + `byCategory`, `byVirtualCategory`, top merchants). Use this for trend / overview questions instead of re-loading the JSONL. Run after each import.
- `rules.json` — semantic layer: `defaultAccountId`, `virtualCategories` (e.g. `Dining Out`, `Pets`, `Housing`), `excludeFromHouseholdSpend` (transfers + CC payments by default), and `merchantAliases`. Edit this — both the importer and Build-Summary read from it.
- `_Rules.ps1` — shared helper that loads `rules.json` with safe defaults (dot-sourced by the other scripts; not invoked directly).
- `analyze.ps1` — full overview (categories / merchants / monthly / largest debits / recurring / fees / income). Takes `-Files` array of JSON pages.
- `report.txt` — last cached `analyze.ps1` output (data through ~May 1 2026).

Prefer extending these over rebuilding from scratch.

## House rules

- Always dedup by transaction `id` when merging account pulls.
- Always use `debitAmount > 0` (not signed `amount`) when summing spend — credits/refunds will cancel out otherwise.
- Date math: use `[datetime]` casts; the API returns ISO strings.
- Report totals with the date range, txn count, and a short by-month + by-merchant breakdown so the user can sanity-check.
