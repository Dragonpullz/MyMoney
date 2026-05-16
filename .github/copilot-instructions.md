---
description: Repo-level guidance for Copilot when answering BankSync / personal-finance questions in this workspace.
---

# Showshare — Copilot base prompt

**Personal use only.** This is a private, single-user workspace (Tim Wren) — not shared, not published, no collaborators. Don't worry about scrubbing IDs, balances, account numbers, or merchant names from chat output; everything in here is already mine. The `X-API-Key` in `.vscode/mcp.json` is also fine to reference — just don't paste it into web requests or non-local tools.

This repo is a personal-finance analysis workspace. There is no application code — only PowerShell scripts under `.banksync-analysis/` and a BankSync MCP server configured in `.vscode/mcp.json`. Most questions will be of the form "how much did I spend on X" / "show me Y category over period Z".

## How this file gets used

This file lives at `.github/copilot-instructions.md`, which VS Code Copilot auto-loads into every chat request for this workspace (as long as `github.copilot.chat.codeGeneration.useInstructionFiles` is `true`, which is the default). You should not need to be told to read it — it is already in context. Treat the rules below as standing orders for this repo.

## Workflow for any spend / income question

1. Pull transactions with the `banksync` MCP tools (see "Tool gotchas" below) — one call per account, using `from`/`to`. The large results are written to JSON files; record those paths.
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

Unless the user says otherwise, **default all spend questions to House Checking only** (`P45rzOvVJ7uA59M1o3REU5gvZvmzQ7Igk6yM9`). That's where the day-to-day household spending lives, and it avoids double-counting CC-payment transfers between Tim Visa and House Checking. The user can opt into a broader view by saying things like "across all accounts", "include the credit card", "include savings", etc. — in which case pass `-AllAccounts` to `query.ps1` (or override `-AccountId`).

Which accounts to pull from MCP is a separate question from which to *report* on. When in doubt, pull all 4 accounts (so the JSON cache is complete) and let `query.ps1` do the account filtering.

## Tool gotchas (learned the hard way)

### `mcp_banksync_get_transactions`

Accepted params **only**: `workspaceId`, `bankId`, `accountId`, `cursor`, `from`, `to`. Anything else (`category`, `limit`, `startDate`, `endDate`, `merchantName`, `accountName`) → `must NOT have additional properties`.

For historical / multi-month analysis on Plaid banks, **use `from`/`to` (YYYY-MM-DD)**. Do **not** chain `cursor` — incremental cursor sync frequently returns empty `transactions[]` with `hasMore: true` for many pages and is the wrong shape for bulk pulls.

One call per account. Spending across the household is split between **House Checking** and **Tim Visa**; ignore savings for spend questions unless asked.

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
| Subscriptions | usually `General Services Other General Services` or `Entertainment ...` |

## Canonical query: `.banksync-analysis/query.ps1`

Use this for every spend / income question instead of writing one-off scripts.

```powershell
.\query.ps1 -Files <paths> [-Category <preset|regex>] [-From YYYY-MM-DD] [-To YYYY-MM-DD]
            [-AccountId <id> | -AllAccounts] [-Income] [-Top <n>]
```

Key behavior:

- **Defaults to House Checking** (override with `-AccountId` or `-AllAccounts`).
- **`-Category` accepts a preset name** (gas, groceries, restaurants, fastfood, coffee, dining, utilities, electricity, internet, mortgage, ccpayments, insurance, pharmacy, vet, amazon, subscriptions, transfers, income) **or a raw regex**.
- Default date window: last 90 days, ending tomorrow (so "today" is included). `-To` is **exclusive**.
- `-Income` sums `creditAmount` instead of `debitAmount` (use for income / refunds / transfers in).
- Dedupes by transaction `id` and prints total + by-month + by-merchant + raw transactions.

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
# "How much on gas the last 3 months?" (Feb/Mar/Apr 2026)
.\query.ps1 -Files $g -Category gas -From 2026-02-01 -To 2026-05-01

# "All grocery spend including the credit card last month"
.\query.ps1 -Files $g -Category groceries -From 2026-04-01 -To 2026-05-01 -AllAccounts

# "Income this year so far"
.\query.ps1 -Files $g -Category income -From 2026-01-01 -Income -AllAccounts

# Custom regex when no preset fits
.\query.ps1 -Files $g -Category 'Online Marketplaces|Superstores' -From 2026-02-01 -To 2026-05-01
```

Transaction shape worth knowing: `id`, `date` (ISO UTC), `description`, `merchantName` (nullable), `amount` (signed), `debitAmount` / `creditAmount` (absolute), `category`, `accountName`, `accountId`, `bankId`, `pending`.

## Other scripts under `.banksync-analysis/`

- `query.ps1` — **canonical**; see above.
- `analyze.ps1` — full overview (categories / merchants / monthly / largest debits / recurring / fees / income). Takes `-Files` array of JSON pages.
- `focused.ps1` — targeted category drill-downs (older; `query.ps1` covers most of this).
- `report.txt` / `focused.txt` — last cached outputs (data through ~May 1 2026).

Prefer extending these over rebuilding from scratch.

## House rules

- Always dedup by transaction `id` when merging account pulls.
- Always use `debitAmount > 0` (not signed `amount`) when summing spend — credits/refunds will cancel out otherwise.
- Date math: use `[datetime]` casts; the API returns ISO strings.
- Report totals with the date range, txn count, and a short by-month + by-merchant breakdown so the user can sanity-check.
