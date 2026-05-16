<#
.SYNOPSIS
Monthly cashflow / savings-rate report from .banksync-cache/summary.json.

.PARAMETER Months
How many trailing months to include. Default 12.

.PARAMETER AccountId
Which account's monthly rollup to show. Default: rules.json defaultAccountId
(House Checking). Use -AllAccounts to aggregate every account in the cache.

.PARAMETER AllAccounts
Sum spend / income across every account in the cache.

.PARAMETER Format
'text' (default) or 'json'.

.PARAMETER SummaryPath
Override the summary file. Default: ../.banksync-cache/summary.json.
#>
[CmdletBinding()]
param(
    [int]$Months = 12,
    [string]$AccountId,
    [switch]$AllAccounts,
    [ValidateSet('text','json')][string]$Format = 'text',
    [string]$SummaryPath = (Join-Path $PSScriptRoot '..\.banksync-cache\summary.json')
)

. (Join-Path $PSScriptRoot '_Rules.ps1')
$rules = Get-BankSyncRules
if (-not $AccountId) { $AccountId = $rules.defaultAccountId }

if (-not (Test-Path $SummaryPath)) {
    throw "Summary not found at $SummaryPath. Run Build-Summary.ps1 first."
}
$summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json

# Collect monthly rows
$rowsByMonth = @{}
$scopeLabel = ''
if ($AllAccounts) {
    $scopeLabel = 'ALL accounts'
    foreach ($accProp in $summary.accounts.PSObject.Properties) {
        foreach ($mProp in $accProp.Value.monthly.PSObject.Properties) {
            $m = $mProp.Name; $v = $mProp.Value
            if (-not $rowsByMonth.ContainsKey($m)) {
                $rowsByMonth[$m] = [pscustomobject]@{ month=$m; spend=0.0; income=0.0; net=0.0 }
            }
            $rowsByMonth[$m].spend  += [double]$v.spend
            $rowsByMonth[$m].income += [double]$v.income
        }
    }
} else {
    $acc = $summary.accounts.$AccountId
    if (-not $acc) { throw "Account $AccountId not found in summary." }
    $scopeLabel = $acc.accountName
    foreach ($mProp in $acc.monthly.PSObject.Properties) {
        $rowsByMonth[$mProp.Name] = [pscustomobject]@{
            month  = $mProp.Name
            spend  = [double]$mProp.Value.spend
            income = [double]$mProp.Value.income
            net    = [double]$mProp.Value.net
        }
    }
}

$rows = $rowsByMonth.Values | Sort-Object month
foreach ($r in $rows) {
    $r.spend = [math]::Round($r.spend, 2)
    $r.income = [math]::Round($r.income, 2)
    $r.net = [math]::Round(($r.income - $r.spend), 2)
    $rate = if ($r.income -gt 0) { [math]::Round(($r.net / $r.income), 4) } else { $null }
    Add-Member -InputObject $r -NotePropertyName savingsRate -NotePropertyValue $rate -Force
}

# Trim to last $Months
$rows = @($rows | Select-Object -Last $Months)

# 3-month trailing averages
for ($i = 0; $i -lt $rows.Count; $i++) {
    $window = $rows[[math]::Max(0, $i-2)..$i]
    $avgS = [math]::Round((($window | Measure-Object spend -Average).Average), 2)
    $avgI = [math]::Round((($window | Measure-Object income -Average).Average), 2)
    $avgN = [math]::Round((($window | Measure-Object net -Average).Average), 2)
    Add-Member -InputObject $rows[$i] -NotePropertyName spend3mAvg  -NotePropertyValue $avgS -Force
    Add-Member -InputObject $rows[$i] -NotePropertyName income3mAvg -NotePropertyValue $avgI -Force
    Add-Member -InputObject $rows[$i] -NotePropertyName net3mAvg    -NotePropertyValue $avgN -Force
}

# YTD totals for the latest year in the rows
$latestYear = if ($rows) { ($rows[-1].month).Substring(0,4) } else { $null }
$ytd = $rows | Where-Object { $_.month.StartsWith($latestYear) }
$ytdTotals = if ($ytd) {
    [pscustomobject]@{
        year   = $latestYear
        spend  = [math]::Round((($ytd | Measure-Object spend  -Sum).Sum), 2)
        income = [math]::Round((($ytd | Measure-Object income -Sum).Sum), 2)
        net    = [math]::Round((($ytd | Measure-Object net    -Sum).Sum), 2)
    }
} else { $null }

if ($Format -eq 'json') {
    [pscustomobject]@{
        scope    = $scopeLabel
        months   = $rows
        ytd      = $ytdTotals
    } | ConvertTo-Json -Depth 6 -Compress
    return
}

Write-Host ("=== Cashflow | {0} | last {1} months ===" -f $scopeLabel, $rows.Count) -ForegroundColor Cyan
$rows | Select-Object month, income, spend, net, savingsRate, spend3mAvg, net3mAvg | Format-Table -AutoSize

if ($ytdTotals) {
    Write-Host ("YTD {0}: income=`${1}  spend=`${2}  net=`${3}" -f `
        $ytdTotals.year, $ytdTotals.income, $ytdTotals.spend, $ytdTotals.net) -ForegroundColor Cyan
}
