<#
.SYNOPSIS
Detect recurring (subscription-like) charges from .banksync-cache/normalized.jsonl.

.DESCRIPTION
Groups debit transactions by normalized merchant. Reports merchants charged in
at least -MinMonths of the last -MonthsBack months. Outputs monthly average,
annualized cost, last charge, and a coarse cadence guess.

.PARAMETER MonthsBack
Lookback window. Default 6.

.PARAMETER MinMonths
Minimum distinct months a merchant must appear in to be considered recurring.
Default 3.

.PARAMETER AccountId
Scope to one account. Default: rules.json defaultAccountId. -AllAccounts to ignore.

.PARAMETER AllAccounts
Aggregate across every account in the cache.

.PARAMETER MinTotal
Hide merchants with total spend below this in the window. Default 5.

.PARAMETER Format
'text' or 'json'.
#>
[CmdletBinding()]
param(
    [int]$MonthsBack = 6,
    [int]$MinMonths = 3,
    [string]$AccountId,
    [switch]$AllAccounts,
    [double]$MinTotal = 5,
    [ValidateSet('text','json')][string]$Format = 'text',
    [string]$CachePath = (Join-Path $PSScriptRoot '..\.banksync-cache\normalized.jsonl')
)

. (Join-Path $PSScriptRoot '_Rules.ps1')
$rules = Get-BankSyncRules
if (-not $AccountId) { $AccountId = $rules.defaultAccountId }

if (-not (Test-Path $CachePath)) { throw "Cache not found at $CachePath." }

$txns = Get-Content $CachePath | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json }
$txns = $txns | Sort-Object id -Unique

# Window: trailing MonthsBack months, ending at today.
$today = Get-Date
$from = (Get-Date -Year $today.Year -Month $today.Month -Day 1).AddMonths(-($MonthsBack-1)).ToString('yyyy-MM-dd')
$to   = (Get-Date -Year $today.Year -Month $today.Month -Day 1).AddMonths(1).ToString('yyyy-MM-dd')

$scope = $txns | Where-Object {
    $_.debitAmount -gt 0 -and
    -not (Test-ExcludedFromSpend $_ $rules) -and
    $_.localDate -ge $from -and $_.localDate -lt $to -and
    ($AllAccounts -or $_.accountId -eq $AccountId)
}

if (-not $scope) {
    if ($Format -eq 'json') { '[]' } else { Write-Host "No transactions in window." -ForegroundColor Yellow }
    return
}

foreach ($t in $scope) {
    $k = if ($t.normalizedMerchant) { $t.normalizedMerchant } elseif ($t.merchantName) { $t.merchantName } else { '(none)' }
    Add-Member -InputObject $t -NotePropertyName _merchantKey -NotePropertyValue $k -Force
}

$rows = @()
foreach ($g in ($scope | Group-Object _merchantKey)) {
    $distinctMonths = @($g.Group | Select-Object -ExpandProperty month -Unique)
    if ($distinctMonths.Count -lt $MinMonths) { continue }

    $total = [math]::Round((($g.Group | Measure-Object debitAmount -Sum).Sum), 2)
    if ($total -lt $MinTotal) { continue }

    $avgMonthly = [math]::Round(($total / $distinctMonths.Count), 2)
    $annualized = [math]::Round(($avgMonthly * 12), 2)
    $lastTxn = $g.Group | Sort-Object localDate -Descending | Select-Object -First 1
    $amounts = @($g.Group | Select-Object -ExpandProperty debitAmount)
    $avgTxn = [math]::Round((($amounts | Measure-Object -Average).Average), 2)
    $maxTxn = [math]::Round((($amounts | Measure-Object -Maximum).Maximum), 2)
    $minTxn = [math]::Round((($amounts | Measure-Object -Minimum).Minimum), 2)

    # Cadence guess: ratio of charge count to months covered.
    $charges = $g.Group.Count
    $ratio = $charges / $distinctMonths.Count
    $cadence = if ($ratio -ge 3.5) { 'weekly?' }
               elseif ($ratio -ge 1.5) { 'multiple/mo' }
               else { 'monthly' }

    # Price-increase flag: latest charge > 1.10 * first charge.
    $sorted = $g.Group | Sort-Object localDate
    $first = $sorted[0].debitAmount
    $last  = $sorted[-1].debitAmount
    $priceJump = ($first -gt 0) -and ($last / $first -ge 1.10)

    $rows += [pscustomobject]@{
        merchant      = $g.Name
        months        = $distinctMonths.Count
        charges       = $charges
        total         = $total
        avgMonthly    = $avgMonthly
        annualized    = $annualized
        avgCharge     = $avgTxn
        minCharge     = $minTxn
        maxCharge     = $maxTxn
        cadence       = $cadence
        priceJump     = $priceJump
        lastCharge    = $lastTxn.localDate
        category      = $lastTxn.category
    }
}

$rows = $rows | Sort-Object annualized -Descending

if ($Format -eq 'json') {
    $rows | ConvertTo-Json -Depth 4 -Compress
    return
}

$scopeLabel = if ($AllAccounts) { 'ALL accounts' } else { ($scope | Select-Object -First 1).accountName }
Write-Host ("=== Subscriptions | {0} | {1} -> {2} ===" -f $scopeLabel, $from, $to) -ForegroundColor Cyan
if (-not $rows) { Write-Host "No recurring merchants found." -ForegroundColor Yellow; return }
$rows | Select-Object merchant, months, charges, avgMonthly, annualized, cadence, priceJump, lastCharge, category | Format-Table -AutoSize

$total = [math]::Round((($rows | Measure-Object annualized -Sum).Sum), 2)
Write-Host ("Estimated total annualized recurring spend: `${0}" -f $total) -ForegroundColor Cyan
