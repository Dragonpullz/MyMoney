<#
.SYNOPSIS
Shows budget progress by virtual category for one month.

.DESCRIPTION
Reads .banksync-analysis/budgets.json and .banksync-cache/summary.json, then compares
monthly spend by virtual category against configured monthly caps.

.PARAMETER Month
Month to report in yyyy-MM. Defaults to the current month.

.PARAMETER AccountId, AllAccounts
Defaults to rules.json default account (House Checking). Use -AllAccounts to aggregate every account in the cache.

.PARAMETER Format
text or json. JSON emits one compact object for agent consumption.
#>
[CmdletBinding()]
param(
    [string]$Month = (Get-Date -Format 'yyyy-MM'),
    [string]$AccountId,
    [switch]$AllAccounts,
    [ValidateSet('text','json')][string]$Format = 'text',
    [string]$BudgetPath = (Join-Path $PSScriptRoot 'budgets.json'),
    [string]$SummaryPath = (Join-Path $PSScriptRoot '..\.banksync-cache\summary.json')
)

. (Join-Path $PSScriptRoot '_Rules.ps1')
$rules = Get-BankSyncRules
if (-not $AccountId) { $AccountId = $rules.defaultAccountId }

if ($Month -notmatch '^\d{4}-\d{2}$') {
    throw "Month must be yyyy-MM, got '$Month'."
}
if (-not (Test-Path $BudgetPath)) {
    throw "Budget file not found at $BudgetPath. Create budgets.json first."
}
if (-not (Test-Path $SummaryPath)) {
    throw "Summary not found at $SummaryPath. Run Build-Summary.ps1 first."
}

$budgets = Get-Content $BudgetPath -Raw | ConvertFrom-Json
$summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
if (-not $budgets.monthly) {
    throw "Budget file has no 'monthly' object."
}

$monthStart = [datetime]::ParseExact(($Month + '-01'), 'yyyy-MM-dd', $null)
$daysInMonth = [datetime]::DaysInMonth($monthStart.Year, $monthStart.Month)
$today = Get-Date
if ($today.ToString('yyyy-MM') -eq $Month) {
    $daysElapsed = [math]::Min($daysInMonth, [math]::Max(1, $today.Day))
} elseif ($monthStart -lt ([datetime]::ParseExact(($today.ToString('yyyy-MM') + '-01'), 'yyyy-MM-dd', $null))) {
    $daysElapsed = $daysInMonth
} else {
    $daysElapsed = 1
}

function Add-CategoryAmounts {
    param(
        [hashtable]$Target,
        $MonthValue
    )
    if ($null -eq $MonthValue -or $null -eq $MonthValue.byVirtualCategory) { return }
    foreach ($vc in $MonthValue.byVirtualCategory.PSObject.Properties) {
        if (-not $Target.ContainsKey($vc.Name)) { $Target[$vc.Name] = 0.0 }
        $Target[$vc.Name] += [double]$vc.Value
    }
}

$actuals = @{}
$priorActuals = @{}
$scopeLabel = ''
$priorMonth = $monthStart.AddMonths(-1).ToString('yyyy-MM')

if ($AllAccounts) {
    $scopeLabel = 'ALL accounts'
    foreach ($accProp in $summary.accounts.PSObject.Properties) {
        Add-CategoryAmounts -Target $actuals -MonthValue $accProp.Value.monthly.$Month
        Add-CategoryAmounts -Target $priorActuals -MonthValue $accProp.Value.monthly.$priorMonth
    }
} else {
    $acc = $summary.accounts.$AccountId
    if (-not $acc) { throw "Account $AccountId not found in summary." }
    $scopeLabel = $acc.accountName
    Add-CategoryAmounts -Target $actuals -MonthValue $acc.monthly.$Month
    Add-CategoryAmounts -Target $priorActuals -MonthValue $acc.monthly.$priorMonth
}

$validVirtualCategories = @{}
if ($rules.virtualCategories) {
    foreach ($vc in $rules.virtualCategories.PSObject.Properties) { $validVirtualCategories[$vc.Name] = $true }
}

$rows = @()
$invalidBudgetKeys = @()
foreach ($budgetProp in $budgets.monthly.PSObject.Properties) {
    $category = $budgetProp.Name
    if ($validVirtualCategories.Count -gt 0 -and -not $validVirtualCategories.ContainsKey($category)) {
        $invalidBudgetKeys += $category
    }

    $budget = [double]$budgetProp.Value
    if ($budget -le 0) { continue }

    $actual = 0.0
    if ($actuals.ContainsKey($category)) { $actual = [double]$actuals[$category] }
    $priorActual = 0.0
    if ($priorActuals.ContainsKey($category)) { $priorActual = [double]$priorActuals[$category] }

    $pctConsumed = if ($budget -gt 0) { $actual / $budget } else { $null }
    $projected = if ($daysElapsed -gt 0) { $actual / $daysElapsed * $daysInMonth } else { $actual }
    $projectedPct = if ($budget -gt 0) { $projected / $budget } else { $null }
    $remaining = $budget - $actual

    $status = if ($actual -gt $budget) {
        'over'
    } elseif ($projected -gt $budget) {
        'on-pace-over'
    } else {
        'under'
    }

    $rows += [pscustomobject]@{
        category      = $category
        budget        = [math]::Round($budget, 2)
        actual        = [math]::Round($actual, 2)
        remaining     = [math]::Round($remaining, 2)
        pctConsumed   = if ($null -ne $pctConsumed) { [math]::Round($pctConsumed, 4) } else { $null }
        projected     = [math]::Round($projected, 2)
        projectedPct  = if ($null -ne $projectedPct) { [math]::Round($projectedPct, 4) } else { $null }
        priorMonth    = [math]::Round($priorActual, 2)
        status        = $status
    }
}

$rows = @($rows | Sort-Object @{ Expression = { if ($_.status -eq 'over') { 0 } elseif ($_.status -eq 'on-pace-over') { 1 } else { 2 } } }, @{ Expression = 'projectedPct'; Descending = $true }, category)
$totalBudget = [math]::Round((($rows | Measure-Object budget -Sum).Sum), 2)
$totalActual = [math]::Round((($rows | Measure-Object actual -Sum).Sum), 2)
$totalProjected = [math]::Round((($rows | Measure-Object projected -Sum).Sum), 2)
$totalPrior = [math]::Round((($rows | Measure-Object priorMonth -Sum).Sum), 2)

if ($Format -eq 'json') {
    [pscustomobject]@{
        scope             = $scopeLabel
        month             = $Month
        daysElapsed       = $daysElapsed
        daysInMonth       = $daysInMonth
        totals            = [pscustomobject]@{
            budget    = $totalBudget
            actual    = $totalActual
            projected = $totalProjected
            priorMonth = $totalPrior
        }
        invalidBudgetKeys = $invalidBudgetKeys
        categories        = $rows
    } | ConvertTo-Json -Depth 6 -Compress
    return
}

Write-Host ("=== Budget Status | {0} | {1} ({2}/{3} days) ===" -f $scopeLabel, $Month, $daysElapsed, $daysInMonth) -ForegroundColor Cyan
if ($invalidBudgetKeys) {
    Write-Warning ("Budget keys not found in rules.json virtualCategories: {0}" -f ($invalidBudgetKeys -join ', '))
}
if (-not $rows) {
    Write-Host "No active monthly budgets configured." -ForegroundColor Yellow
    return
}

$rows |
    Select-Object category, budget, actual, remaining,
        @{ Name = 'pct'; Expression = { $_.pctConsumed } },
        projected,
        @{ Name = 'projPct'; Expression = { $_.projectedPct } },
        @{ Name = 'prior'; Expression = { $_.priorMonth } },
        status |
    Format-Table -AutoSize

Write-Host ("Totals: budget=`${0}  actual=`${1}  projected=`${2}  priorMonth=`${3}" -f $totalBudget, $totalActual, $totalProjected, $totalPrior) -ForegroundColor Cyan
