<#
.SYNOPSIS
Rank potential savings / spending-improvement opportunities by estimated
monthly impact, using summary.json + normalized.jsonl.

.DESCRIPTION
Each opportunity carries Evidence, EstimatedMonthlyImpact, Confidence
(low/medium/high), and a SuggestedNextAction. Heuristic, deliberately
explainable — not a black-box model.

.PARAMETER LookbackMonths
How many months to use as a baseline. Default 6.

.PARAMETER AccountId, AllAccounts
Scope. Default: rules.json defaultAccountId.

.PARAMETER Format
'text' or 'json'.
#>
[CmdletBinding()]
param(
    [int]$LookbackMonths = 6,
    [string]$AccountId,
    [switch]$AllAccounts,
    [ValidateSet('text','json')][string]$Format = 'text',
    [string]$SummaryPath = (Join-Path $PSScriptRoot '..\.banksync-cache\summary.json'),
    [string]$CachePath   = (Join-Path $PSScriptRoot '..\.banksync-cache\normalized.jsonl')
)

. (Join-Path $PSScriptRoot '_Rules.ps1')
$rules = Get-BankSyncRules
if (-not $AccountId) { $AccountId = $rules.defaultAccountId }

if (-not (Test-Path $SummaryPath)) { throw "Summary not found at $SummaryPath." }
if (-not (Test-Path $CachePath))   { throw "Cache not found at $CachePath." }

$summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
$txns    = Get-Content $CachePath | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json }
$txns    = $txns | Sort-Object id -Unique

# Pull per-month rows for the requested scope
$rows = @()
if ($AllAccounts) {
    $byMonth = @{}
    foreach ($accProp in $summary.accounts.PSObject.Properties) {
        foreach ($mProp in $accProp.Value.monthly.PSObject.Properties) {
            $m = $mProp.Name; $v = $mProp.Value
            if (-not $byMonth.ContainsKey($m)) {
                $byMonth[$m] = [pscustomobject]@{ month=$m; spend=0.0; income=0.0; byVirtualCategory=@{} }
            }
            $byMonth[$m].spend  += [double]$v.spend
            $byMonth[$m].income += [double]$v.income
            foreach ($vc in $v.byVirtualCategory.PSObject.Properties) {
                $key = $vc.Name
                if (-not $byMonth[$m].byVirtualCategory.ContainsKey($key)) { $byMonth[$m].byVirtualCategory[$key] = 0.0 }
                $byMonth[$m].byVirtualCategory[$key] += [double]$vc.Value
            }
        }
    }
    $rows = $byMonth.Values | Sort-Object month
} else {
    $acc = $summary.accounts.$AccountId
    if (-not $acc) { throw "Account $AccountId not found in summary." }
    foreach ($mProp in $acc.monthly.PSObject.Properties) {
        $vcHash = @{}
        foreach ($vc in $mProp.Value.byVirtualCategory.PSObject.Properties) { $vcHash[$vc.Name] = [double]$vc.Value }
        $rows += [pscustomobject]@{
            month             = $mProp.Name
            spend             = [double]$mProp.Value.spend
            income            = [double]$mProp.Value.income
            byVirtualCategory = $vcHash
        }
    }
    $rows = $rows | Sort-Object month
}

$rows = @($rows | Select-Object -Last $LookbackMonths)
if ($rows.Count -lt 2) { Write-Warning "Need at least 2 months for opportunities. Run more imports."; return }

$opps = New-Object System.Collections.ArrayList
$current  = $rows[-1]
$baseline = $rows[0..($rows.Count - 2)]   # everything except the latest month

# Heuristic 1: any virtual category where the latest month > 1.25 * trailing average
$vcAll = New-Object System.Collections.Generic.HashSet[string]
foreach ($r in $rows) { foreach ($k in $r.byVirtualCategory.Keys) { [void]$vcAll.Add($k) } }
foreach ($vc in $vcAll) {
    $latest = [double]($current.byVirtualCategory[$vc]); if (-not $latest) { continue }
    $hist = @($baseline | ForEach-Object { [double]($_.byVirtualCategory[$vc]) })
    if (-not $hist) { continue }
    $avg = ($hist | Measure-Object -Average).Average
    if ($avg -le 0) { continue }
    if ($latest -gt $avg * 1.25 -and ($latest - $avg) -ge 25) {
        $delta = [math]::Round(($latest - $avg), 2)
        [void]$opps.Add([pscustomobject]@{
            opportunity            = ("Trim {0} spend back to baseline" -f $vc)
            evidence               = ("{0} this month vs. {1:N2}/mo trailing avg" -f $latest, $avg)
            estimatedMonthlyImpact = $delta
            confidence             = if ($rows.Count -ge 4) { 'medium' } else { 'low' }
            suggestedNextAction    = ("Open this category in query.ps1: .\query.ps1 -Category '{0}' -ByMerchant" -f $vc)
        })
    }
}

# Heuristic 2: dining-out vs grocery ratio (dining > 75% of groceries is a flag)
$diningAvg = ($rows | ForEach-Object { [double]($_.byVirtualCategory['Dining Out']) } | Measure-Object -Average).Average
$grocAvg   = ($rows | ForEach-Object { [double]($_.byVirtualCategory['Groceries']) }   | Measure-Object -Average).Average
if ($grocAvg -gt 0 -and $diningAvg / $grocAvg -gt 0.75) {
    $cut = [math]::Round(($diningAvg * 0.2), 2)
    [void]$opps.Add([pscustomobject]@{
        opportunity            = 'Shift some dining-out spend to groceries'
        evidence               = ("Dining out averages `${0:N2}/mo vs. groceries `${1:N2}/mo (ratio {2:N2})" -f $diningAvg, $grocAvg, ($diningAvg/$grocAvg))
        estimatedMonthlyImpact = $cut
        confidence             = 'low'
        suggestedNextAction    = 'Target a 20% reduction in restaurant/fast-food spend for one month.'
    })
}

# Heuristic 3: bank fees in the lookback window
$winFrom = $rows[0].month + '-01'
$winTo   = ((Get-Date ($rows[-1].month + '-01')).AddMonths(1)).ToString('yyyy-MM-dd')
$fees = $txns | Where-Object {
    $_.debitAmount -gt 0 -and $_.category -like 'Bank Fees*' -and
    $_.localDate -ge $winFrom -and $_.localDate -lt $winTo -and
    ($AllAccounts -or $_.accountId -eq $AccountId)
}
if ($fees) {
    $monthlyFees = [math]::Round((($fees | Measure-Object debitAmount -Sum).Sum / $rows.Count), 2)
    [void]$opps.Add([pscustomobject]@{
        opportunity            = 'Eliminate recurring bank fees'
        evidence               = ("{0} fee transactions totaling `${1} in window" -f $fees.Count, [math]::Round((($fees | Measure-Object debitAmount -Sum).Sum), 2))
        estimatedMonthlyImpact = $monthlyFees
        confidence             = 'high'
        suggestedNextAction    = 'Run Find-Anomalies.ps1 to list each fee; switch products or call to waive.'
    })
}

# Heuristic 4: subscription-style recurring spend (delegates to the same heuristic)
$subFinder = Join-Path $PSScriptRoot 'Find-Subscriptions.ps1'
if (Test-Path $subFinder) {
    $subsJson = & $subFinder -MonthsBack $LookbackMonths -MinMonths ([math]::Max(2, $LookbackMonths - 2)) `
                             -AccountId $AccountId -AllAccounts:$AllAccounts -Format json 2>$null
    if ($subsJson) {
        try {
            $subs = $subsJson | ConvertFrom-Json
            $bigSubs = $subs | Where-Object { $_.annualized -ge 120 } | Sort-Object annualized -Descending | Select-Object -First 3
            foreach ($s in $bigSubs) {
                [void]$opps.Add([pscustomobject]@{
                    opportunity            = ("Audit subscription: {0}" -f $s.merchant)
                    evidence               = ("`${0}/mo avg, `${1}/yr annualized over {2} months" -f $s.avgMonthly, $s.annualized, $s.months)
                    estimatedMonthlyImpact = [math]::Round([double]$s.avgMonthly, 2)
                    confidence             = if ($s.months -ge 4) { 'high' } else { 'medium' }
                    suggestedNextAction    = 'Confirm you still use it; consider downgrading or canceling.'
                })
            }
        } catch { }
    }
}

$opps = $opps | Sort-Object estimatedMonthlyImpact -Descending

if ($Format -eq 'json') {
    ,$opps | ConvertTo-Json -Depth 4 -Compress
    return
}

$scopeLabel = if ($AllAccounts) { 'ALL accounts' } else { $summary.accounts.$AccountId.accountName }
Write-Host ("=== Opportunities | {0} | last {1} months ===" -f $scopeLabel, $rows.Count) -ForegroundColor Cyan
if (-not $opps) { Write-Host "No notable opportunities found." -ForegroundColor Green; return }
$opps | Select-Object @{n='Impact/mo';e={('$' + ('{0:N2}' -f $_.estimatedMonthlyImpact))}},
                      confidence,
                      opportunity,
                      evidence,
                      suggestedNextAction |
    Format-Table -AutoSize -Wrap

$totalImpact = [math]::Round((($opps | Measure-Object estimatedMonthlyImpact -Sum).Sum), 2)
Write-Host ("Combined estimated monthly impact: `${0}" -f $totalImpact) -ForegroundColor Cyan
