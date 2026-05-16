<#
.SYNOPSIS
Find unusual transactions: outliers vs. merchant baseline, duplicate charges,
fees, large new-merchant charges, suspicious refund/charge pairs.

.PARAMETER WindowMonths
Baseline lookback. Default 6 months.

.PARAMETER OutlierSigma
Threshold for merchant-level outliers (charge > mean + N * stddev). Default 2.

.PARAMETER MinNewMerchantAmount
Only flag a new-merchant charge above this dollar amount. Default 100.

.PARAMETER AccountId, AllAccounts
Scope. Default: rules.json defaultAccountId.

.PARAMETER Format
'text' or 'json'.
#>
[CmdletBinding()]
param(
    [int]$WindowMonths = 6,
    [double]$OutlierSigma = 2,
    [double]$MinNewMerchantAmount = 100,
    [string]$AccountId,
    [switch]$AllAccounts,
    [ValidateSet('text','json')][string]$Format = 'text',
    [string]$CachePath = (Join-Path $PSScriptRoot '..\.banksync-cache\normalized.jsonl')
)

. (Join-Path $PSScriptRoot '_Rules.ps1')
$rules = Get-BankSyncRules
if (-not $AccountId) { $AccountId = $rules.defaultAccountId }

if (-not (Test-Path $CachePath)) { throw "Cache not found at $CachePath." }
$txns = Get-Content $CachePath | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json }
$txns = $txns | Sort-Object id -Unique

$today = Get-Date
$winFrom = (Get-Date -Year $today.Year -Month $today.Month -Day 1).AddMonths(-($WindowMonths-1)).ToString('yyyy-MM-dd')
$winTo   = (Get-Date -Year $today.Year -Month $today.Month -Day 1).AddMonths(1).ToString('yyyy-MM-dd')

# Recent month for "new merchant" comparisons
$recentFrom = (Get-Date -Year $today.Year -Month $today.Month -Day 1).ToString('yyyy-MM-dd')

$scope = $txns | Where-Object {
    $_.localDate -ge $winFrom -and $_.localDate -lt $winTo -and
    ($AllAccounts -or $_.accountId -eq $AccountId)
}

foreach ($t in $scope) {
    $k = if ($t.normalizedMerchant) { $t.normalizedMerchant } elseif ($t.merchantName) { $t.merchantName } else { '(none)' }
    Add-Member -InputObject $t -NotePropertyName _merchantKey -NotePropertyValue $k -Force
}

$findings = New-Object System.Collections.ArrayList

# Rule 1: merchant outlier — charge > mean + sigma * stddev for that merchant
foreach ($g in ($scope | Where-Object { $_.debitAmount -gt 0 } | Group-Object _merchantKey)) {
    if ($g.Count -lt 3) { continue }
    $amounts = @($g.Group | Select-Object -ExpandProperty debitAmount)
    $mean = ($amounts | Measure-Object -Average).Average
    $stddev = if ($amounts.Count -gt 1) {
        [math]::Sqrt((($amounts | ForEach-Object { ($_ - $mean) * ($_ - $mean) }) | Measure-Object -Sum).Sum / ($amounts.Count - 1))
    } else { 0 }
    $threshold = $mean + $OutlierSigma * $stddev
    foreach ($t in $g.Group) {
        if ($t.debitAmount -gt $threshold -and $t.debitAmount -gt $mean * 1.2) {
            [void]$findings.Add([pscustomobject]@{
                severity = 'medium'
                date     = $t.localDate
                merchant = $g.Name
                amount   = [math]::Round($t.debitAmount, 2)
                reason   = ("Charge {0:N2} exceeds merchant baseline (mean {1:N2}, threshold {2:N2})" -f $t.debitAmount, $mean, $threshold)
                action   = 'Verify the charge with the merchant.'
                id       = $t.id
            })
        }
    }
}

# Rule 2: duplicate charges — same merchant + amount on same day
$dupGroups = $scope | Where-Object { $_.debitAmount -gt 0 } |
    Group-Object _merchantKey, localDate, debitAmount | Where-Object Count -gt 1
foreach ($g in $dupGroups) {
    $t = $g.Group | Select-Object -First 1
    [void]$findings.Add([pscustomobject]@{
        severity = 'high'
        date     = $t.localDate
        merchant = $t._merchantKey
        amount   = [math]::Round($t.debitAmount, 2)
        reason   = ("Same merchant + amount {0} times on {1}" -f $g.Count, $t.localDate)
        action   = 'Possible duplicate charge — review and request refund if confirmed.'
        id       = ($g.Group | Select-Object -ExpandProperty id) -join ','
    })
}

# Rule 3: bank fees / interest
foreach ($t in ($scope | Where-Object { $_.debitAmount -gt 0 -and $_.category -like 'Bank Fees*' })) {
    [void]$findings.Add([pscustomobject]@{
        severity = 'low'
        date     = $t.localDate
        merchant = $t._merchantKey
        amount   = [math]::Round($t.debitAmount, 2)
        reason   = ("Bank fee / interest charge ({0})" -f $t.category)
        action   = 'Avoidable — investigate whether a different account/card avoids this.'
        id       = $t.id
    })
}

# Rule 4: large charge from a new merchant (first appearance in the window)
$firstSeen = @{}
foreach ($t in ($scope | Where-Object { $_.debitAmount -gt 0 } | Sort-Object localDate)) {
    if (-not $firstSeen.ContainsKey($t._merchantKey)) { $firstSeen[$t._merchantKey] = $t.localDate }
}
foreach ($t in ($scope | Where-Object { $_.debitAmount -gt $MinNewMerchantAmount -and $_.localDate -ge $recentFrom })) {
    if ($firstSeen[$t._merchantKey] -ge $recentFrom) {
        [void]$findings.Add([pscustomobject]@{
            severity = 'medium'
            date     = $t.localDate
            merchant = $t._merchantKey
            amount   = [math]::Round($t.debitAmount, 2)
            reason   = ("First charge from {0} this window; amount > `${1}" -f $t._merchantKey, $MinNewMerchantAmount)
            action   = 'Confirm this is an intended purchase.'
            id       = $t.id
        })
    }
}

# Rule 5: refund/charge pair — same merchant, same absolute amount, debit & credit within 7 days
$bm = $scope | Where-Object { $_.debitAmount  -gt 0 } | Group-Object _merchantKey
$cm = $scope | Where-Object { $_.creditAmount -gt 0 } | Group-Object _merchantKey
$cmHash = @{}
foreach ($g in $cm) { $cmHash[$g.Name] = $g.Group }
foreach ($g in $bm) {
    if (-not $cmHash.ContainsKey($g.Name)) { continue }
    foreach ($d in $g.Group) {
        foreach ($c in $cmHash[$g.Name]) {
            if ([math]::Abs($d.debitAmount - $c.creditAmount) -lt 0.01) {
                $delta = [math]::Abs(([datetime]$d.localDate - [datetime]$c.localDate).TotalDays)
                if ($delta -le 7) {
                    [void]$findings.Add([pscustomobject]@{
                        severity = 'low'
                        date     = $c.localDate
                        merchant = $g.Name
                        amount   = [math]::Round($d.debitAmount, 2)
                        reason   = ("Refund of `${0} matched a debit on {1}" -f $d.debitAmount, $d.localDate)
                        action   = 'Refund or failed-charge pattern — typically benign.'
                        id       = "$($d.id),$($c.id)"
                    })
                }
            }
        }
    }
}

$findings = $findings | Sort-Object @{Expression={
    switch ($_.severity) { 'high' {0} 'medium' {1} 'low' {2} default {3} }
}}, date -Descending

if ($Format -eq 'json') {
    ,$findings | ConvertTo-Json -Depth 4 -Compress
    return
}

$scopeLabel = if ($AllAccounts) { 'ALL accounts' } else { ($scope | Select-Object -First 1).accountName }
Write-Host ("=== Anomalies | {0} | {1} -> {2} ===" -f $scopeLabel, $winFrom, $winTo) -ForegroundColor Cyan
if (-not $findings) { Write-Host "No anomalies detected." -ForegroundColor Green; return }
$findings | Select-Object severity, date, merchant, amount, reason, action | Format-Table -AutoSize -Wrap
