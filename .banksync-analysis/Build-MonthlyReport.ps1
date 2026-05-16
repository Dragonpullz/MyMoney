<#
.SYNOPSIS
Build a Markdown monthly report combining cashflow, categories, merchants,
subscriptions, anomalies, and a projection update for the chosen month.

.PARAMETER Month
Report month, YYYY-MM. Default: most recent completed month present in the
summary (so today's MTD doesn't pollute it).

.PARAMETER AccountId / AllAccounts
Scope. Default: rules.json defaultAccountId.

.PARAMETER OutDir
Where to write the report. Default: .banksync-analysis/reports/.
#>
[CmdletBinding()]
param(
    [string]$Month,
    [string]$AccountId,
    [switch]$AllAccounts,
    [string]$OutDir = (Join-Path $PSScriptRoot 'reports'),
    [string]$SummaryPath = (Join-Path $PSScriptRoot '..\.banksync-cache\summary.json'),
    [string]$CachePath   = (Join-Path $PSScriptRoot '..\.banksync-cache\normalized.jsonl')
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_Rules.ps1')
$rules = Get-BankSyncRules
if (-not $AccountId) { $AccountId = $rules.defaultAccountId }

if (-not (Test-Path $SummaryPath)) { throw "Summary not found at $SummaryPath. Run Build-Summary.ps1 first." }
$summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json

# Resolve scope label and per-month index
$months = @()
if ($AllAccounts) {
    $set = New-Object System.Collections.Generic.SortedSet[string]
    foreach ($a in $summary.accounts.PSObject.Properties) {
        foreach ($m in $a.Value.monthly.PSObject.Properties) { [void]$set.Add($m.Name) }
    }
    $months = @($set)
    $scopeLabel = 'ALL accounts'
} else {
    $acc = $summary.accounts.$AccountId
    if (-not $acc) { throw "Account $AccountId not found in summary." }
    $months = @($acc.monthly.PSObject.Properties.Name | Sort-Object)
    $scopeLabel = $acc.accountName
}

$currentMonth = (Get-Date -Format 'yyyy-MM')
$completedMonths = @($months | Where-Object { $_ -lt $currentMonth })
if (-not $Month) {
    if (-not $completedMonths) { throw "No completed months available. Wait for next month, or pass -Month explicitly." }
    $Month = $completedMonths[-1]
}
if ($months -notcontains $Month) { throw "Month $Month not found in summary." }

# Aggregate monthly data for the selected month
function Get-MonthValuesForScope {
    param($month)
    if ($AllAccounts) {
        $agg = [pscustomobject]@{
            spend=0.0; income=0.0; net=0.0; txnCount=0; spendTxnCount=0
            byCategory=@{}; byVirtualCategory=@{}; topMerchants=@{}
        }
        foreach ($a in $summary.accounts.PSObject.Properties) {
            $m = $a.Value.monthly.$month
            if (-not $m) { continue }
            $agg.spend         += [double]$m.spend
            $agg.income        += [double]$m.income
            $agg.net           += [double]$m.net
            $agg.txnCount      += [int]$m.txnCount
            $agg.spendTxnCount += [int]$m.spendTxnCount
            foreach ($p in $m.byCategory.PSObject.Properties)        { if (-not $agg.byCategory.ContainsKey($p.Name)) { $agg.byCategory[$p.Name]=0.0 }; $agg.byCategory[$p.Name] += [double]$p.Value }
            foreach ($p in $m.byVirtualCategory.PSObject.Properties) { if (-not $agg.byVirtualCategory.ContainsKey($p.Name)) { $agg.byVirtualCategory[$p.Name]=0.0 }; $agg.byVirtualCategory[$p.Name] += [double]$p.Value }
            foreach ($tm in $m.topMerchants) {
                if (-not $agg.topMerchants.ContainsKey($tm.merchant)) { $agg.topMerchants[$tm.merchant] = @{ total=0.0; count=0 } }
                $agg.topMerchants[$tm.merchant].total += [double]$tm.total
                $agg.topMerchants[$tm.merchant].count += [int]$tm.count
            }
        }
        return $agg
    }
    $m = $summary.accounts.$AccountId.monthly.$month
    if (-not $m) { return $null }
    $cat = @{}; foreach ($p in $m.byCategory.PSObject.Properties)        { $cat[$p.Name] = [double]$p.Value }
    $vc  = @{}; foreach ($p in $m.byVirtualCategory.PSObject.Properties) { $vc[$p.Name]  = [double]$p.Value }
    $tm  = @{}; foreach ($t in $m.topMerchants)                          { $tm[$t.merchant] = @{ total=[double]$t.total; count=[int]$t.count } }
    return [pscustomobject]@{
        spend=[double]$m.spend; income=[double]$m.income; net=[double]$m.net
        txnCount=[int]$m.txnCount; spendTxnCount=[int]$m.spendTxnCount
        byCategory=$cat; byVirtualCategory=$vc; topMerchants=$tm
    }
}

$cur = Get-MonthValuesForScope $Month

# 3-month trailing average (excluding the report month)
$priorMonths = @($completedMonths | Where-Object { $_ -lt $Month } | Select-Object -Last 3)
$priorData = @($priorMonths | ForEach-Object { Get-MonthValuesForScope $_ })
function Average-CategoryMap { param($prior, $field)
    $sums = @{}; $count = $prior.Count
    if ($count -eq 0) { return $sums }
    foreach ($p in $prior) {
        foreach ($k in $p.$field.Keys) {
            if (-not $sums.ContainsKey($k)) { $sums[$k] = 0.0 }
            $sums[$k] += [double]$p.$field[$k]
        }
    }
    $avg = @{}; foreach ($k in $sums.Keys) { $avg[$k] = [math]::Round($sums[$k] / $count, 2) }
    return $avg
}
$priorCatAvg = Average-CategoryMap $priorData 'byCategory'
$priorVCAvg  = Average-CategoryMap $priorData 'byVirtualCategory'

# Category deltas vs prior average
$catDeltas = @()
$allCats = @{}
foreach ($k in $cur.byCategory.Keys) { $allCats[$k] = $true }
foreach ($k in $priorCatAvg.Keys)    { $allCats[$k] = $true }
foreach ($k in $allCats.Keys) {
    $now  = [double]$cur.byCategory[$k]
    $base = [double]$priorCatAvg[$k]
    if ($now -eq 0 -and $base -eq 0) { continue }
    $catDeltas += [pscustomobject]@{
        category = $k
        current  = [math]::Round($now, 2)
        priorAvg = [math]::Round($base, 2)
        delta    = [math]::Round(($now - $base), 2)
        pct      = if ($base -gt 0) { [math]::Round((($now - $base) / $base) * 100, 1) } else { $null }
    }
}
$catDeltas = $catDeltas | Sort-Object { [math]::Abs($_.delta) } -Descending | Select-Object -First 10

# Top merchants table
$topMerchants = @($cur.topMerchants.GetEnumerator() | ForEach-Object {
    [pscustomobject]@{ merchant=$_.Key; total=[math]::Round($_.Value.total,2); count=$_.Value.count }
} | Sort-Object total -Descending | Select-Object -First 10)

# Pull subscriptions, anomalies (use the JSON outputs from sibling scripts)
function Invoke-JsonScript {
    param([string]$Script, $Args)
    try {
        $raw = & $Script @Args -Format json 2>$null
        if ([string]::IsNullOrWhiteSpace($raw)) { return @() }
        return ($raw | ConvertFrom-Json)
    } catch { return @() }
}

$accountArgs = @{ AccountId = $AccountId }
if ($AllAccounts) { $accountArgs = @{ AllAccounts = $true } }

$subs = Invoke-JsonScript (Join-Path $PSScriptRoot 'Find-Subscriptions.ps1') (
    $accountArgs + @{ MonthsBack = 6; MinMonths = 3 }
)
$anoms = Invoke-JsonScript (Join-Path $PSScriptRoot 'Find-Anomalies.ps1') (
    $accountArgs + @{ WindowMonths = 3 }
)
$proj  = Invoke-JsonScript (Join-Path $PSScriptRoot 'Project-Spend.ps1') (
    $accountArgs + @{ Category = 'Spend'; MonthsBack = 12; MonthsForward = 3 }
)
$opps  = Invoke-JsonScript (Join-Path $PSScriptRoot 'Find-Opportunities.ps1') (
    $accountArgs + @{ LookbackMonths = 6 }
)

# --- Render markdown ---------------------------------------------------------
$lines = @()
$lines += "# Monthly Report - $Month"
$lines += ""
$lines += "_Scope: **$scopeLabel** | Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm')_"
$lines += ""

# Cashflow
$savingsRate = if ($cur.income -gt 0) { '{0:P1}' -f ($cur.net / $cur.income) } else { 'n/a' }
$lines += '## Cashflow'
$lines += ''
$lines += '| Income | Spend | Net | Savings Rate | Txn Count |'
$lines += '|---:|---:|---:|---:|---:|'
$lines += ('| ${0:N2} | ${1:N2} | ${2:N2} | {3} | {4} |' -f $cur.income, $cur.spend, $cur.net, $savingsRate, $cur.txnCount)
$lines += ''
if ($priorData) {
    $avgIncome = [math]::Round((($priorData | Measure-Object income -Average).Average), 2)
    $avgSpend  = [math]::Round((($priorData | Measure-Object spend  -Average).Average), 2)
    $avgNet    = [math]::Round((($priorData | Measure-Object net    -Average).Average), 2)
    $lines += ('_Trailing {0}-month avg - income ${1:N2}, spend ${2:N2}, net ${3:N2}._' -f $priorData.Count, $avgIncome, $avgSpend, $avgNet)
    $lines += ''
}

# Category deltas
$lines += '## Top Category Changes vs. Prior Avg'
$lines += ''
if (-not $catDeltas) {
    $lines += '_No prior months available for comparison._'
} else {
    $lines += '| Category | This Month | Prior Avg | Delta | % |'
    $lines += '|---|---:|---:|---:|---:|'
    foreach ($d in $catDeltas) {
        $pct = if ($null -eq $d.pct) { 'n/a' } else { ('{0:N1}%' -f $d.pct) }
        $lines += ('| {0} | ${1:N2} | ${2:N2} | ${3:N2} | {4} |' -f $d.category, $d.current, $d.priorAvg, $d.delta, $pct)
    }
}
$lines += ''

# Virtual categories
$lines += '## Virtual Categories'
$lines += ''
if (-not $cur.byVirtualCategory.Keys) {
    $lines += '_No virtual categories defined or matched._'
} else {
    $lines += '| Category | Spend | Prior Avg |'
    $lines += '|---|---:|---:|'
    foreach ($k in ($cur.byVirtualCategory.Keys | Sort-Object { -[double]$cur.byVirtualCategory[$_] })) {
        $now  = [double]$cur.byVirtualCategory[$k]
        $base = [double]$priorVCAvg[$k]
        $lines += ('| {0} | ${1:N2} | ${2:N2} |' -f $k, $now, $base)
    }
}
$lines += ''

# Top merchants
$lines += '## Top Merchants'
$lines += ''
if (-not $topMerchants) {
    $lines += '_No merchant data._'
} else {
    $lines += '| Merchant | Total | Count |'
    $lines += '|---|---:|---:|'
    foreach ($m in $topMerchants) {
        $lines += ('| {0} | ${1:N2} | {2} |' -f $m.merchant, $m.total, $m.count)
    }
}
$lines += ''

# Subscriptions
$lines += '## Subscription Audit'
$lines += ''
if (-not $subs -or @($subs).Count -eq 0) {
    $lines += '_No recurring merchants detected in the trailing window._'
} else {
    $lines += '| Merchant | Months | Avg/mo | Annualized | Price Jump |'
    $lines += '|---|---:|---:|---:|:---:|'
    foreach ($s in (@($subs) | Select-Object -First 15)) {
        $lines += ('| {0} | {1} | ${2:N2} | ${3:N2} | {4} |' -f $s.merchant, $s.months, $s.avgMonthly, $s.annualized, ($(if ($s.priceJump) { 'yes' } else { '' })))
    }
}
$lines += ''

# Anomalies
$lines += '## Anomalies'
$lines += ''
if (-not $anoms -or @($anoms).Count -eq 0) {
    $lines += '_No anomalies detected._'
} else {
    $lines += '| Sev | Date | Merchant | Amount | Reason |'
    $lines += '|---|---|---|---:|---|'
    foreach ($a in (@($anoms) | Select-Object -First 20)) {
        $lines += ('| {0} | {1} | {2} | ${3:N2} | {4} |' -f $a.severity, $a.date, $a.merchant, [double]$a.amount, ($a.reason -replace '\|','\|'))
    }
}
$lines += ''

# Projection
$lines += '## Projection (Spend, next 3 months)'
$lines += ''
if ($null -eq $proj -or -not $proj.forecast) {
    $lines += '_Not enough history to project._'
} else {
    $lines += ('Averages - 3-mo **${0:N2}**, 12-mo **${1:N2}**, stddev **${2:N2}**. Trend slope **${3:N2}/mo**.' -f $proj.avg3, $proj.avg12, $proj.stddev, $proj.trend.slope)
    if ($proj.mtd.daysElapsed -gt 0) {
        $lines += ('MTD {0}: **${1:N2}** ({2}/{3} days), projected end-of-month **${4:N2}**.' -f $proj.mtd.month, [double]$proj.mtd.actual, $proj.mtd.daysElapsed, $proj.mtd.daysInMonth, [double]$proj.mtd.projected)
    }
    $lines += ''
    $lines += '| Month | Forecast | Low (-2s) | High (+2s) |'
    $lines += '|---|---:|---:|---:|'
    foreach ($f in $proj.forecast) {
        $lines += ('| {0} | ${1:N2} | ${2:N2} | ${3:N2} |' -f $f.month, [double]$f.forecast, [double]$f.low, [double]$f.high)
    }
}
$lines += ''

# Opportunities / suggested actions
$lines += '## Suggested Actions'
$lines += ''
if (-not $opps -or @($opps).Count -eq 0) {
    $lines += '_No notable opportunities flagged._'
} else {
    foreach ($o in (@($opps) | Select-Object -First 6)) {
        $impact = '{0:N2}' -f [double]$o.estimatedMonthlyImpact
        $lines += ('- **${0}/mo · {1}** — {2}' -f $impact, $o.confidence, $o.opportunity)
        $lines += ('  - Evidence: {0}' -f $o.evidence)
        $lines += ('  - Next: {0}' -f $o.suggestedNextAction)
    }
}
$lines += ''

# Mermaid: 6-month spend/income trend
$lastMonths = @($completedMonths | Where-Object { $_ -le $Month } | Select-Object -Last 6)
if ($lastMonths.Count -ge 2) {
    $lines += '## Trend (last 6 months)'
    $lines += ''
    $lines += '```mermaid'
    $lines += 'xychart-beta'
    $lines += ('  title "Spend vs Income - {0}"' -f $scopeLabel)
    $lines += ('  x-axis [{0}]' -f (($lastMonths | ForEach-Object { '"' + $_ + '"' }) -join ', '))
    $lines += '  y-axis "USD"'
    $spendSeries  = @($lastMonths | ForEach-Object { (Get-MonthValuesForScope $_).spend })
    $incomeSeries = @($lastMonths | ForEach-Object { (Get-MonthValuesForScope $_).income })
    $lines += ('  bar    [{0}]' -f (($spendSeries  | ForEach-Object { '{0:N2}' -f [double]$_ }) -join ', '))
    $lines += ('  line   [{0}]' -f (($incomeSeries | ForEach-Object { '{0:N2}' -f [double]$_ }) -join ', '))
    $lines += '```'
    $lines += ''
}

# Mermaid: category mix for the report month
if ($cur.byVirtualCategory.Keys) {
    $lines += '## Category Mix'
    $lines += ''
    $lines += '```mermaid'
    $lines += 'pie showData'
    $lines += ('  title "{0} - virtual category spend"' -f $Month)
    foreach ($k in ($cur.byVirtualCategory.Keys | Sort-Object { -[double]$cur.byVirtualCategory[$_] } | Select-Object -First 8)) {
        $v = [double]$cur.byVirtualCategory[$k]
        if ($v -le 0) { continue }
        $lines += ('  "{0}" : {1:N2}' -f $k, $v)
    }
    $lines += '```'
    $lines += ''
}

# Write
$null = New-Item -ItemType Directory -Force -Path $OutDir
$outFile = Join-Path $OutDir ("{0}.md" -f $Month)
$lines -join "`r`n" | Set-Content -Path $outFile -Encoding utf8
Write-Host ("Report written: {0}" -f $outFile) -ForegroundColor Green
