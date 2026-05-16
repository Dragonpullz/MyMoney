<#
.SYNOPSIS
Build .banksync-cache/summary.json from normalized transactions.

.DESCRIPTION
Reads `.banksync-cache/normalized.jsonl` and writes a `summary.json` with
per-account, per-month rollups (spend / income / net / savings rate, top
categories, top merchants). Intended for fast answers without re-loading
the full transaction set.

.PARAMETER CacheRoot
Cache directory. Defaults to `<repo>/.banksync-cache`.

.PARAMETER TopMerchants
Number of top merchants to include per account-month. Default 10.
#>
[CmdletBinding()]
param(
    [string]$CacheRoot = (Join-Path $PSScriptRoot '..\.banksync-cache'),
    [int]$TopMerchants = 10
)

$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot '_Rules.ps1')
$rules = Get-BankSyncRules

$cachePath = Join-Path $CacheRoot 'normalized.jsonl'
if (-not (Test-Path $cachePath)) {
    throw "Cache not found at $cachePath. Run Import-BankSyncDump.ps1 first."
}

$txns = Get-Content $cachePath | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json }
$txns = $txns | Sort-Object id -Unique
Write-Host ("Loaded {0} transactions from cache" -f $txns.Count) -ForegroundColor DarkGray

function Get-MerchantKey {
    param($t)
    if ($t.normalizedMerchant) { return $t.normalizedMerchant }
    if ($t.merchantName)       { return $t.merchantName }
    return '(none)'
}

# Default scope (House Checking, from rules.json)
$defaultAccountId = $rules.defaultAccountId
$defaultAccount = $txns | Where-Object accountId -EQ $defaultAccountId | Select-Object -First 1

$accounts = [ordered]@{}
foreach ($accGroup in ($txns | Group-Object accountId | Sort-Object Name)) {
    $accId = $accGroup.Name
    $accTxns = $accGroup.Group
    $first = $accTxns | Select-Object -First 1

    $monthly = [ordered]@{}
    foreach ($monthGroup in ($accTxns | Group-Object month | Sort-Object Name)) {
        $month = $monthGroup.Name
        $rows = $monthGroup.Group

        $spendTxns  = $rows | Where-Object { $_.debitAmount  -gt 0 -and -not (Test-ExcludedFromSpend $_ $rules) }
        $incomeTxns = $rows | Where-Object { $_.creditAmount -gt 0 -and -not $_.isTransfer }

        $spend  = if ($spendTxns)  { [math]::Round((($spendTxns  | Measure-Object debitAmount  -Sum).Sum), 2) } else { 0 }
        $income = if ($incomeTxns) { [math]::Round((($incomeTxns | Measure-Object creditAmount -Sum).Sum), 2) } else { 0 }
        $net    = [math]::Round(($income - $spend), 2)
        $savingsRate = if ($income -gt 0) { [math]::Round(($net / $income), 4) } else { $null }

        $byCategory = [ordered]@{}
        foreach ($catGroup in ($spendTxns | Group-Object category |
                Sort-Object @{Expression = { ($_.Group | Measure-Object debitAmount -Sum).Sum }} -Descending)) {
            $byCategory[$catGroup.Name] = [math]::Round((($catGroup.Group | Measure-Object debitAmount -Sum).Sum), 2)
        }

        # Virtual categories (rules.json) — a txn may match multiple buckets.
        $vcTotals = @{}
        foreach ($t in $spendTxns) {
            $hits = Get-VirtualCategoryHits -Transaction $t -Rules $rules
            foreach ($h in $hits) {
                if (-not $vcTotals.ContainsKey($h)) { $vcTotals[$h] = 0.0 }
                $vcTotals[$h] += [double]$t.debitAmount
            }
        }
        $byVirtualCategory = [ordered]@{}
        foreach ($k in ($vcTotals.Keys | Sort-Object { -$vcTotals[$_] })) {
            $byVirtualCategory[$k] = [math]::Round($vcTotals[$k], 2)
        }

        foreach ($t in $spendTxns) {
            Add-Member -InputObject $t -NotePropertyName _merchantKey -NotePropertyValue (Get-MerchantKey $t) -Force
        }
        $merchGroups = $spendTxns | Group-Object -Property _merchantKey
        $topMerch = @($merchGroups |
            Sort-Object -Property @{Expression = { ($_.Group | Measure-Object debitAmount -Sum).Sum }} -Descending |
            Select-Object -First $TopMerchants | ForEach-Object {
                [pscustomobject]@{
                    merchant = $_.Name
                    total    = [math]::Round((($_.Group | Measure-Object debitAmount -Sum).Sum), 2)
                    count    = $_.Count
                }
            })

        $monthly[$month] = [pscustomobject]@{
            spend             = $spend
            income            = $income
            net               = $net
            savingsRate       = $savingsRate
            txnCount          = $rows.Count
            spendTxnCount     = @($spendTxns).Count
            byCategory        = $byCategory
            byVirtualCategory = $byVirtualCategory
            topMerchants      = $topMerch
        }
    }

    $localDates = $accTxns | ForEach-Object localDate | Sort-Object -Unique
    $accounts[$accId] = [pscustomobject]@{
        accountId   = $accId
        accountName = $first.accountName
        bankId      = $first.bankId
        txnCount    = $accTxns.Count
        firstSeen   = $localDates[0]
        lastSeen    = $localDates[-1]
        monthly     = $monthly
    }
}

$allDates = $txns | ForEach-Object localDate | Sort-Object -Unique
$summary = [pscustomobject]@{
    generatedAt    = (Get-Date).ToString('o')
    source         = (Resolve-Path $cachePath).Path
    txnCount       = $txns.Count
    range          = [pscustomobject]@{ from = $allDates[0]; to = $allDates[-1] }
    scopeDefaults  = [pscustomobject]@{
        accountId   = $defaultAccountId
        accountName = if ($defaultAccount) { $defaultAccount.accountName } elseif ($rules.defaultAccountName) { $rules.defaultAccountName } else { $null }
    }
    rules          = [pscustomobject]@{
        excludeFromHouseholdSpend = $rules.excludeFromHouseholdSpend
        virtualCategories         = @($rules.virtualCategories.PSObject.Properties.Name)
    }
    accounts       = $accounts
}

$outPath = Join-Path $CacheRoot 'summary.json'
$summary | ConvertTo-Json -Depth 10 | Set-Content -Path $outPath -Encoding utf8

$accCount = $accounts.Keys.Count
$monthsForDefault = if ($accounts.Contains($defaultAccountId)) { @($accounts[$defaultAccountId].monthly.Keys).Count } else { 0 }
Write-Host ("Summary written: {0}" -f $outPath) -ForegroundColor Green
Write-Host ("  Accounts: {0}  |  Default-account months: {1}  |  Txn total: {2}" -f $accCount, $monthsForDefault, $txns.Count)
