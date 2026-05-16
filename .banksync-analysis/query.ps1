<#
.SYNOPSIS
General BankSync spend query — filter the normalized transaction cache
(or raw MCP JSON dumps) by category, date range, and account.

.DESCRIPTION
By default reads `.banksync-cache\normalized.jsonl` (produced by
Import-BankSyncDump.ps1). Pass -Files to query raw MCP dumps instead.

.PARAMETER Files
Optional. One or more JSON files produced by `mcp_banksync_get_transactions`.
When omitted, the script reads `.banksync-cache\normalized.jsonl`.

.PARAMETER Category
Regex (case-insensitive) matched against transaction `category`, OR a preset
name. Default '.' (everything). Presets:
  gas, groceries, restaurants, fastfood, coffee, dining, utilities,
  electricity, internet, mortgage, ccpayments, insurance, pharmacy, vet,
  amazon, subscriptions, transfers, income.

.PARAMETER From
Inclusive start date, YYYY-MM-DD. Default: 90 days ago.

.PARAMETER To
Exclusive end date, YYYY-MM-DD. Default: tomorrow (so "today" is included).

.PARAMETER AccountId
Limit to a single accountId. Default: House Checking
(P45rzOvVJ7uA59M1o3REU5gvZvmzQ7Igk6yM9), per repo convention.
Use -AllAccounts to bypass this filter.

.PARAMETER AllAccounts
Aggregate across every account present in the input.

.PARAMETER Top
Rows in the by-merchant table. Default 20.

.PARAMETER Income
Sum creditAmount (money in) instead of debitAmount (money out).

.PARAMETER ByMerchant
Show the by-merchant breakdown (off by default to keep output concise).

.PARAMETER Detailed
Show the full transaction list (off by default).

.PARAMETER Format
'text' (default) for human-readable output, or 'json' for a single compact
JSON object on stdout (suppresses all other output — for agent consumption).
#>
[CmdletBinding()]
param(
    [string[]]$Files,
    [string]$Category = '.',
    [string]$From,
    [string]$To,
    [string]$AccountId = 'P45rzOvVJ7uA59M1o3REU5gvZvmzQ7Igk6yM9',
    [switch]$AllAccounts,
    [int]$Top = 20,
    [switch]$Income,
    [switch]$ByMerchant,
    [switch]$Detailed,
    [ValidateSet('text','json')][string]$Format = 'text'
)

$isJson = $Format -eq 'json'
function Log { param($msg, $color = 'Gray') if (-not $isJson) { Write-Host $msg -ForegroundColor $color } }

$presets = @{
    gas           = 'Transportation Gas'
    groceries     = 'Food And Drink Groceries'
    restaurants   = 'Food And Drink Restaurant'
    fastfood      = 'Food And Drink Fast Food'
    coffee        = 'Food And Drink Coffee'
    dining        = 'Food And Drink (Restaurant|Fast Food|Coffee)'
    utilities     = 'Rent And Utilities'
    electricity   = 'Rent And Utilities Gas And Electricity'
    internet      = 'Rent And Utilities Telephone|Rent And Utilities Internet'
    mortgage      = 'Loan Payments Mortgage Payment'
    ccpayments    = 'Loan Payments Credit Card Payment'
    insurance     = 'General Services Insurance'
    pharmacy      = 'Medical Pharmacies And Supplements'
    vet           = 'Medical Veterinary Services'
    amazon        = 'General Merchandise Online Marketplaces'
    subscriptions = 'General Services Other General Services|Entertainment'
    transfers     = 'Transfer (In|Out)'
    income        = 'Income |Transfer In'
}

$key = $Category.ToLower()
if ($presets.ContainsKey($key)) {
    $catRegex = $presets[$key]
    Log ("Category preset '{0}' -> /{1}/" -f $Category, $catRegex) 'DarkGray'
}
else {
    $catRegex = $Category
}

if (-not $From) { $From = (Get-Date).AddDays(-90).ToString('yyyy-MM-dd') }
if (-not $To) { $To = (Get-Date).AddDays(1).ToString('yyyy-MM-dd') }

# --- Load transactions -------------------------------------------------------
$txns = @()
if ($Files) {
    foreach ($f in $Files) {
        if (-not (Test-Path $f)) { Write-Warning "Missing file: $f"; continue }
        $d = Get-Content $f -Raw | ConvertFrom-Json
        if ($d.transactions) {
            $txns += $d.transactions
            Log ("Loaded {0,4} txns from {1}" -f $d.transactions.Count, (Split-Path $f -Leaf))
        }
    }
}
else {
    $cache = Join-Path $PSScriptRoot '..\.banksync-cache\normalized.jsonl'
    if (-not (Test-Path $cache)) {
        throw "No -Files specified and cache not found at $cache. Run Import-BankSyncDump.ps1 first or pass -Files."
    }
    $txns = Get-Content $cache | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json }
    Log ("Loaded {0} txns from cache" -f $txns.Count)
}
$txns = $txns | Sort-Object id -Unique

# Ensure localDate + month exist (raw MCP dumps lack them)
foreach ($t in $txns) {
    if (-not $t.localDate) {
        $ld = ([string]$t.date).Substring(0,10)
        Add-Member -InputObject $t -NotePropertyName localDate -NotePropertyValue $ld -Force
        Add-Member -InputObject $t -NotePropertyName month -NotePropertyValue $ld.Substring(0,7) -Force
    }
}

# --- Filter ------------------------------------------------------------------
$amountField = if ($Income) { 'creditAmount' } else { 'debitAmount' }
$direction = if ($Income) { 'IN' } else { 'OUT' }

$hits = $txns | Where-Object {
    $_.category -match $catRegex -and
    $_.$amountField -gt 0 -and
    $_.localDate -ge $From -and
    $_.localDate -lt $To -and
    ($AllAccounts -or -not $AccountId -or $_.accountId -eq $AccountId)
}

$total = if ($hits) { [math]::Round((($hits | Measure-Object $amountField -Sum).Sum), 2) } else { 0 }
$count = @($hits).Count

$scope = if ($AllAccounts -or -not $AccountId) { 'ALL accounts' }
else {
    $name = ($txns | Where-Object accountId -EQ $AccountId | Select-Object -First 1).accountName
    if (-not $name) { $AccountId } else { $name }
}

# --- Aggregate ---------------------------------------------------------------
$byMonth = @($hits | Group-Object month | Sort-Object Name | ForEach-Object {
    [pscustomobject]@{
        month = $_.Name
        count = $_.Count
        total = [math]::Round((($_.Group | Measure-Object $amountField -Sum).Sum), 2)
    }
})

foreach ($t in $hits) {
    $m = if ($t.normalizedMerchant) { $t.normalizedMerchant }
         elseif ($t.merchantName)   { $t.merchantName }
         else                       { '(none)' }
    Add-Member -InputObject $t -NotePropertyName _merchantKey -NotePropertyValue $m -Force
}
$groups = $hits | Group-Object -Property _merchantKey
$ranked = $groups | Sort-Object -Property @{Expression = { ($_.Group | Measure-Object $amountField -Sum).Sum }} -Descending
$merchTable = @($ranked | Select-Object -First $Top | ForEach-Object {
    [pscustomobject]@{
        merchant = $_.Name
        count    = $_.Count
        total    = [math]::Round((($_.Group | Measure-Object $amountField -Sum).Sum), 2)
        avg      = [math]::Round((($_.Group | Measure-Object $amountField -Average).Average), 2)
    }
})

# --- Output ------------------------------------------------------------------
if ($isJson) {
    $out = [ordered]@{
        category    = $Category
        categoryRegex = $catRegex
        direction   = $direction
        from        = $From
        to          = $To
        scope       = $scope
        accountId   = if ($AllAccounts) { $null } else { $AccountId }
        total       = $total
        count       = $count
        byMonth     = $byMonth
    }
    if ($ByMerchant) { $out.byMerchant = $merchTable }
    if ($Detailed) {
        $out.transactions = @($hits | Sort-Object localDate | ForEach-Object {
            [pscustomobject]@{
                date     = $_.localDate
                amount   = $_.$amountField
                merchant = $_._merchantKey
                category = $_.category
                account  = $_.accountName
                id       = $_.id
            }
        })
    }
    $out | ConvertTo-Json -Depth 6 -Compress
    return
}

Write-Host ''
Write-Host ("=== {0} [{1}] | {2} -> {3} | {4} ===" -f $Category, $direction, $From, $To, $scope) -ForegroundColor Cyan
Write-Host ("Total: `${0}  ({1} txns)" -f $total, $count)

if ($count -eq 0) { return }

Write-Host ''
Write-Host 'By month:' -ForegroundColor Cyan
$byMonth | Format-Table -AutoSize

if ($ByMerchant) {
    Write-Host 'By merchant:' -ForegroundColor Cyan
    $merchTable | Format-Table -AutoSize
}

if ($Detailed) {
    Write-Host 'Transactions:' -ForegroundColor Cyan
    $hits | Sort-Object localDate |
        Select-Object @{n='Date';e={$_.localDate}},
                      @{n='Amount';e={$_.$amountField}},
                      @{n='Merchant';e={$_._merchantKey}},
                      @{n='Category';e={$_.category}},
                      accountName |
        Format-Table -AutoSize
}
