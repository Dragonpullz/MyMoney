<#
.SYNOPSIS
General BankSync spend query — filter combined transaction JSON dumps by
category, date range, and account.

.DESCRIPTION
The MCP server is only reachable from the AI agent, so the agent must first
call `mcp_banksync_get_transactions` (once per accountId, with from/to) and
collect the resulting JSON content files. Pass those file paths to -Files and
this script will load, dedup, filter, and summarize them.

.PARAMETER Files
One or more JSON files produced by `mcp_banksync_get_transactions`. Each
file is expected to have a `.transactions` array.

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
Aggregate across every account present in the input files.

.PARAMETER Top
Rows in the by-merchant table. Default 20.

.PARAMETER Income
Sum creditAmount (money in) instead of debitAmount (money out).

.EXAMPLE
# Gas spend Feb-Apr 2026 on House Checking
.\query.ps1 -Files $g -Category gas -From 2026-02-01 -To 2026-05-01

.EXAMPLE
# All grocery spend in March across every account
.\query.ps1 -Files $g -Category groceries -From 2026-03-01 -To 2026-04-01 -AllAccounts

.EXAMPLE
# Custom regex (Amazon + Costco) over last 90 days
.\query.ps1 -Files $g -Category 'Online Marketplaces|Superstores'
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string[]]$Files,
    [string]$Category = '.',
    [string]$From,
    [string]$To,
    [string]$AccountId = 'P45rzOvVJ7uA59M1o3REU5gvZvmzQ7Igk6yM9',
    [switch]$AllAccounts,
    [int]$Top = 20,
    [switch]$Income
)

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
    Write-Host ("Category preset '{0}' -> /{1}/" -f $Category, $catRegex) -ForegroundColor DarkGray
}
else {
    $catRegex = $Category
}

if (-not $From) { $From = (Get-Date).AddDays(-90).ToString('yyyy-MM-dd') }
if (-not $To) { $To = (Get-Date).AddDays(1).ToString('yyyy-MM-dd') }
$fromDt = [datetime]$From
$toDt = [datetime]$To

# Load + dedup
$all = @()
foreach ($f in $Files) {
    if (-not (Test-Path $f)) { Write-Warning "Missing file: $f"; continue }
    $d = Get-Content $f -Raw | ConvertFrom-Json
    if ($d.transactions) {
        $all += $d.transactions
        Write-Host ("Loaded {0,4} txns from {1}" -f $d.transactions.Count, (Split-Path $f -Leaf))
    }
}
$txns = $all | Sort-Object id -Unique
Write-Host ("Total unique txns loaded: {0}" -f $txns.Count)

# Amount field
$amountField = if ($Income) { 'creditAmount' } else { 'debitAmount' }
$direction = if ($Income) { 'IN ' } else { 'OUT' }

# Filter
$hits = $txns | Where-Object {
    $_.category -match $catRegex -and
    $_.$amountField -gt 0 -and
    ([datetime]$_.date) -ge $fromDt -and
    ([datetime]$_.date) -lt $toDt -and
    ($AllAccounts -or -not $AccountId -or $_.accountId -eq $AccountId)
}

$total = if ($hits) { [math]::Round((($hits | Measure-Object $amountField -Sum).Sum), 2) } else { 0 }

$scope = if ($AllAccounts -or -not $AccountId) { 'ALL accounts' }
else {
    $name = ($txns | Where-Object accountId -EQ $AccountId | Select-Object -First 1).accountName
    if (-not $name) { $AccountId } else { $name }
}

Write-Host ''
Write-Host ("=== {0} [{1}] | {2} -> {3} | {4} ===" -f $Category, $direction, $From, $To, $scope) -ForegroundColor Cyan
Write-Host ("Total: `${0}  ({1} txns)" -f $total, $hits.Count)

if (-not $hits) { return }

Write-Host ''
Write-Host 'By month:' -ForegroundColor Cyan
$hits | Group-Object { ([datetime]$_.date).ToString('yyyy-MM') } | Sort-Object Name |
    Select-Object @{n = 'Month'; e = { $_.Name } },
                  @{n = 'Count'; e = { $_.Count } },
                  @{n = 'Total'; e = { [math]::Round((($_.Group | Measure-Object $amountField -Sum).Sum), 2) } } |
    Format-Table -AutoSize

Write-Host 'By merchant:' -ForegroundColor Cyan
$hits | Group-Object merchantName |
    Sort-Object { ($_.Group | Measure-Object $amountField -Sum).Sum } -Descending |
    Select-Object -First $Top @{n = 'Merchant'; e = { if ($_.Name) { $_.Name } else { '(none)' } } },
                              @{n = 'Count'; e = { $_.Count } },
                              @{n = 'Total'; e = { [math]::Round((($_.Group | Measure-Object $amountField -Sum).Sum), 2) } },
                              @{n = 'Avg'; e = { [math]::Round((($_.Group | Measure-Object $amountField -Average).Average), 2) } } |
    Format-Table -AutoSize

Write-Host 'Transactions:' -ForegroundColor Cyan
$hits | Sort-Object date |
    Select-Object @{n = 'Date'; e = { ([datetime]$_.date).ToString('yyyy-MM-dd') } },
                  @{n = 'Amount'; e = { $_.$amountField } },
                  merchantName,
                  @{n = 'Category'; e = { $_.category } },
                  accountName |
    Format-Table -AutoSize
