<#
.SYNOPSIS
Project future spend/income for a category (or the total) using transparent
heuristics: 3-month average, 12-month average, linear trend, MTD run-rate.

.PARAMETER Category
What to project. One of:
  - 'Spend' / 'Income' / 'Net' (whole-month totals from summary.json)
  - A virtual-category name from rules.json (e.g. 'Dining Out', 'Groceries')
  - Any Plaid category regex (case-insensitive) — uses byCategory totals.

.PARAMETER MonthsBack
Historical window. Default 12.

.PARAMETER MonthsForward
Months to forecast. Default 6.

.PARAMETER AccountId / AllAccounts
Scope. Default: rules.json defaultAccountId.

.PARAMETER Format
'text' (default) or 'json'.
#>
[CmdletBinding()]
param(
    [string]$Category = 'Spend',
    [int]$MonthsBack = 12,
    [int]$MonthsForward = 6,
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
$summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json

$virtualNames = @($rules.virtualCategories.PSObject.Properties.Name)
$mode = if ($Category -in 'Spend','Income','Net') { 'Total' }
        elseif ($virtualNames -contains $Category) { 'Virtual' }
        else { 'Regex' }

function Get-MonthValue {
    param($m, $mode, $key)
    switch ($mode) {
        'Total' {
            switch ($key) {
                'Spend'  { return [double]$m.spend }
                'Income' { return [double]$m.income }
                'Net'    { return [double]$m.net }
            }
        }
        'Virtual' {
            $v = $m.byVirtualCategory.$key
            if ($null -eq $v) { return 0.0 } else { return [double]$v }
        }
        'Regex' {
            $sum = 0.0
            foreach ($p in $m.byCategory.PSObject.Properties) {
                if ($p.Name -match $key) { $sum += [double]$p.Value }
            }
            return $sum
        }
    }
}

# Build per-month series
$rows = @()
if ($AllAccounts) {
    $months = New-Object System.Collections.Generic.SortedSet[string]
    foreach ($accProp in $summary.accounts.PSObject.Properties) {
        foreach ($mp in $accProp.Value.monthly.PSObject.Properties) { [void]$months.Add($mp.Name) }
    }
    foreach ($m in $months) {
        $sum = 0.0
        foreach ($accProp in $summary.accounts.PSObject.Properties) {
            $mObj = $accProp.Value.monthly.$m
            if ($mObj) { $sum += Get-MonthValue -m $mObj -mode $mode -key $Category }
        }
        $rows += [pscustomobject]@{ month=$m; value=[math]::Round($sum,2) }
    }
    $scopeLabel = 'ALL accounts'
} else {
    $acc = $summary.accounts.$AccountId
    if (-not $acc) { throw "Account $AccountId not found in summary." }
    foreach ($mp in $acc.monthly.PSObject.Properties) {
        $v = Get-MonthValue -m $mp.Value -mode $mode -key $Category
        $rows += [pscustomobject]@{ month=$mp.Name; value=[math]::Round([double]$v,2) }
    }
    $rows = $rows | Sort-Object month
    $scopeLabel = $acc.accountName
}

# Use the most recent MonthsBack months *before* the current calendar month,
# so MTD doesn't pollute averages.
$currentMonth = (Get-Date -Format 'yyyy-MM')
$completed = @($rows | Where-Object { $_.month -lt $currentMonth })
$completed = @($completed | Select-Object -Last $MonthsBack)

if ($completed.Count -lt 1) {
    throw "No completed months available for $Category in scope $scopeLabel."
}

$values = @($completed | Select-Object -ExpandProperty value)
$avg12 = [math]::Round((($values | Measure-Object -Average).Average), 2)
$avg3  = if ($values.Count -ge 3) {
    [math]::Round((($values | Select-Object -Last 3 | Measure-Object -Average).Average), 2)
} else { $avg12 }
$stddev = if ($values.Count -gt 1) {
    $m = ($values | Measure-Object -Average).Average
    [math]::Round([math]::Sqrt((($values | ForEach-Object { ($_ - $m) * ($_ - $m) }) | Measure-Object -Sum).Sum / ($values.Count - 1)), 2)
} else { 0 }

# Linear trend over the last 6 (or fewer) months: y = a + b*x  where x is 0..n-1
$trendWindow = @($values | Select-Object -Last 6)
$n = $trendWindow.Count
if ($n -ge 2) {
    $xs = 0..($n-1)
    $sumX  = ($xs   | Measure-Object -Sum).Sum
    $sumY  = ($trendWindow | Measure-Object -Sum).Sum
    $sumXY = 0; for ($i=0; $i -lt $n; $i++) { $sumXY += $xs[$i] * $trendWindow[$i] }
    $sumXX = ($xs | ForEach-Object { $_ * $_ } | Measure-Object -Sum).Sum
    $denom = ($n * $sumXX) - ($sumX * $sumX)
    if ($denom -ne 0) {
        $slope = (($n * $sumXY) - ($sumX * $sumY)) / $denom
        $intercept = ($sumY - $slope * $sumX) / $n
    } else { $slope = 0; $intercept = $sumY / $n }
} else { $slope = 0; $intercept = if ($values) { $values[-1] } else { 0 } }
$slope = [math]::Round($slope, 2)
$trendNext = [math]::Round(($intercept + $slope * $n), 2)

# Forecast: simple ensemble (avg of 3mo-avg, 12mo-avg, trend), with ±2σ band
$forecast = @()
for ($k = 0; $k -lt $MonthsForward; $k++) {
    $futMonth = (Get-Date -Year ([int]$currentMonth.Split('-')[0]) -Month ([int]$currentMonth.Split('-')[1]) -Day 1).AddMonths($k+1).ToString('yyyy-MM')
    $trendY = [math]::Round(($intercept + $slope * ($n + $k)), 2)
    $point = [math]::Round((($avg3 + $avg12 + $trendY) / 3.0), 2)
    $forecast += [pscustomobject]@{
        month       = $futMonth
        forecast    = $point
        low         = [math]::Round([math]::Max([double]0, $point - 2 * $stddev), 2)
        high        = [math]::Round($point + 2 * $stddev, 2)
        trendOnly   = $trendY
    }
}

# Month-to-date for current calendar month — read normalized.jsonl
$mtdActual = $null; $mtdProjected = $null; $daysElapsed = 0; $daysInMonth = 0
if (Test-Path $CachePath) {
    $txns = Get-Content $CachePath | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json }
    $monthStart = "$currentMonth-01"
    $nextMonth = ((Get-Date $monthStart).AddMonths(1)).ToString('yyyy-MM-dd')
    $today = (Get-Date).ToString('yyyy-MM-dd')
    $daysInMonth = [datetime]::DaysInMonth((Get-Date).Year, (Get-Date).Month)
    $daysElapsed = (Get-Date).Day

    $scope = $txns | Where-Object {
        $_.localDate -ge $monthStart -and $_.localDate -lt $nextMonth -and
        ($AllAccounts -or $_.accountId -eq $AccountId)
    }

    # Pick spend vs income field & exclude per mode/category
    $useCredit = ($Category -eq 'Income')
    $field = if ($useCredit) { 'creditAmount' } else { 'debitAmount' }
    $mtdMatch = $scope | Where-Object {
        $_.$field -gt 0 -and
        (-not (Test-ExcludedFromSpend $_ $rules) -or $useCredit) -and
        (
            ($mode -eq 'Total') -or
            ($mode -eq 'Regex' -and $_.category -match $Category) -or
            ($mode -eq 'Virtual' -and (Get-VirtualCategoryHits -Transaction $_ -Rules $rules) -contains $Category)
        )
    }
    $mtdActual = if ($mtdMatch) { [math]::Round((($mtdMatch | Measure-Object $field -Sum).Sum), 2) } else { 0 }
    if ($daysElapsed -gt 0) {
        $mtdProjected = [math]::Round(($mtdActual * $daysInMonth / $daysElapsed), 2)
    }
}

$result = [pscustomobject]@{
    category    = $Category
    mode        = $mode
    scope       = $scopeLabel
    history     = $completed
    avg3        = $avg3
    avg12       = $avg12
    stddev      = $stddev
    trend       = [pscustomobject]@{ slope = $slope; nextMonth = $trendNext }
    forecast    = $forecast
    mtd         = [pscustomobject]@{
        month       = $currentMonth
        actual      = $mtdActual
        projected   = $mtdProjected
        daysElapsed = $daysElapsed
        daysInMonth = $daysInMonth
    }
}

if ($Format -eq 'json') {
    $result | ConvertTo-Json -Depth 6 -Compress
    return
}

Write-Host ("=== Projection | {0} | {1} ===" -f $Category, $scopeLabel) -ForegroundColor Cyan
Write-Host ("History (last {0} completed months):" -f $completed.Count)
$completed | Format-Table -AutoSize

Write-Host ("Averages: 3-mo `${0}  12-mo `${1}  stddev `${2}" -f $avg3, $avg12, $stddev)
Write-Host ("Linear trend: slope `${0}/mo, projects `${1} for next month" -f $slope, $trendNext)
if ($null -ne $mtdActual) {
    Write-Host ("MTD {0}: `${1} actual  ({2}/{3} days)  ->  projected month-end `${4}" -f `
        $currentMonth, $mtdActual, $daysElapsed, $daysInMonth, $mtdProjected) -ForegroundColor Cyan
}
Write-Host ''
Write-Host ("Forecast (ensemble of 3mo-avg, 12mo-avg, linear trend; band = +/-2sigma):") -ForegroundColor Cyan
$forecast | Format-Table -AutoSize
