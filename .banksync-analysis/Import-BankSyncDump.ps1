<#
.SYNOPSIS
Import BankSync MCP transaction dumps into the local cache.

.DESCRIPTION
Takes one or more JSON files produced by `mcp_banksync_get_transactions`
(typically stored under VS Code chat-session-resources) and:

1. Copies each raw file into `.banksync-cache/raw/<accountId>/<fetchId>.json`.
2. Normalizes every transaction into a stable JSON-line schema and writes
   `.banksync-cache/normalized.jsonl`, deduped by transaction id.
3. Updates `.banksync-cache/manifest.json` with accounts seen, covered date
   ranges per account, and per-fetch import timestamps.

Idempotent. Re-running with the same input is safe: the JSONL is fully
rewritten in sorted order so dedup stays reliable.

.PARAMETER Files
One or more paths to MCP `content.json` files (or any JSON with a
`transactions[]` array using the BankSync shape).

.PARAMETER FetchLabel
Optional human label written to the manifest. Default: today's date.

.PARAMETER CacheRoot
Where the cache lives. Default: `.banksync-cache` next to this script's
parent directory (i.e. repo root).

.EXAMPLE
.\Import-BankSyncDump.ps1 -Files $tx1, $tx2 -FetchLabel '2026-05-16 househcheck'
#>
param(
    [Parameter(Mandatory)][string[]]$Files,
    [string]$FetchLabel = (Get-Date -Format 'yyyy-MM-dd'),
    [string]$CacheRoot = (Join-Path $PSScriptRoot '..\.banksync-cache')
)

$ErrorActionPreference = 'Stop'

# Resolve and create cache layout
$null = New-Item -ItemType Directory -Force -Path $CacheRoot
$CacheRoot = (Resolve-Path $CacheRoot).Path
$RawRoot = Join-Path $CacheRoot 'raw'
$null = New-Item -ItemType Directory -Force -Path $RawRoot
$NormalizedPath = Join-Path $CacheRoot 'normalized.jsonl'
$ManifestPath = Join-Path $CacheRoot 'manifest.json'

# Merchant normalization is driven by rules.json (see _Rules.ps1).
. (Join-Path $PSScriptRoot '_Rules.ps1')
$rules = Get-BankSyncRules
$merchantAliases = Get-MerchantAliasMap -Rules $rules

function ConvertTo-NormalizedMerchant {
    param([string]$MerchantName, [string]$Description)
    $candidate = if ($MerchantName) { $MerchantName.Trim() } else { '' }
    if (-not $candidate -and $Description) {
        $candidate = ($Description -split '\s{2,}|DES:|ID:')[0].Trim()
    }
    foreach ($alias in $merchantAliases) {
        if ($candidate -match $alias.pattern) { return $alias.name }
    }
    return $candidate
}

# Load existing normalized cache (if any) — keyed by id for fast dedup
$existing = @{}
if (Test-Path $NormalizedPath) {
    foreach ($line in Get-Content $NormalizedPath) {
        if ($line.Trim()) {
            $t = $line | ConvertFrom-Json
            $existing[$t.id] = $t
        }
    }
    Write-Host ("Loaded {0} existing transactions from cache" -f $existing.Count) -ForegroundColor DarkGray
}

# Load manifest, materialize accounts into a hashtable for easy mutation
$manifest = if (Test-Path $ManifestPath) {
    Get-Content $ManifestPath -Raw | ConvertFrom-Json
} else {
    [pscustomobject]@{ accounts = $null; fetches = @() }
}
$accounts = @{}
if ($manifest.accounts) {
    foreach ($p in $manifest.accounts.PSObject.Properties) {
        $accounts[$p.Name] = $p.Value
    }
}
$fetches = @()
if ($manifest.fetches) { $fetches = @($manifest.fetches) }

$totalIn = 0; $newCount = 0; $updatedCount = 0

foreach ($f in $Files) {
    if (-not (Test-Path $f)) {
        Write-Warning "Missing input file: $f"
        continue
    }
    $payload = Get-Content $f -Raw | ConvertFrom-Json
    if (-not $payload.transactions) {
        Write-Warning "No transactions[] in $f"
        continue
    }
    $txns = $payload.transactions
    $totalIn += $txns.Count

    # Copy raw payload into per-account folder, update account ranges
    foreach ($g in ($txns | Group-Object accountId)) {
        $accId = $g.Name
        $dest = Join-Path $RawRoot $accId
        $null = New-Item -ItemType Directory -Force -Path $dest
        $stamp = (Get-Date -Format 'yyyyMMdd-HHmmss')
        $shortName = [IO.Path]::GetFileNameWithoutExtension($f)
        $copy = Join-Path $dest ("{0}_{1}.json" -f $stamp, $shortName)
        Copy-Item -LiteralPath $f -Destination $copy -Force

        $first = $g.Group | Select-Object -First 1
        # Plaid stamps txn dates at midnight UTC of the calendar date; use the
        # raw YYYY-MM-DD string so we don't lose a day to local-tz conversion.
        $localDates = $g.Group | ForEach-Object { ([string]$_.date).Substring(0,10) } | Sort-Object -Unique
        $minD = $localDates[0]
        $maxD = $localDates[-1]

        if (-not $accounts.ContainsKey($accId)) {
            $accounts[$accId] = [pscustomobject]@{
                accountName = $first.accountName
                bankId      = $first.bankId
                firstSeen   = $minD
                lastSeen    = $maxD
            }
        } else {
            $a = $accounts[$accId]
            if ($a.firstSeen -gt $minD) { $a.firstSeen = $minD }
            if ($a.lastSeen  -lt $maxD) { $a.lastSeen  = $maxD }
        }
    }

    foreach ($t in $txns) {
        $dateStr   = [string]$t.date
        $localDate = $dateStr.Substring(0,10)
        $direction = if ($t.creditAmount -gt 0) { 'IN' } else { 'OUT' }
        $norm = [ordered]@{
            id                 = $t.id
            date               = $t.date
            localDate          = $localDate
            month              = $localDate.Substring(0,7)
            year               = $localDate.Substring(0,4)
            description        = $t.description
            merchantName       = $t.merchantName
            normalizedMerchant = (ConvertTo-NormalizedMerchant -MerchantName $t.merchantName -Description $t.description)
            category           = $t.category
            amount             = $t.amount
            debitAmount        = $t.debitAmount
            creditAmount       = $t.creditAmount
            direction          = $direction
            accountId          = $t.accountId
            accountName        = $t.accountName
            bankId             = $t.bankId
            pending            = $t.pending
            isTransfer         = [bool]($t.category -match 'Transfer In|Transfer Out')
            isCcPayment        = [bool]($t.category -match 'Credit Card Payment')
        }
        if ($existing.ContainsKey($t.id)) { $updatedCount++ } else { $newCount++ }
        $existing[$t.id] = [pscustomobject]$norm
    }

    $fetches += [pscustomobject]@{
        file       = (Resolve-Path $f).Path
        fetchLabel = $FetchLabel
        importedAt = (Get-Date).ToString('o')
        txnCount   = $txns.Count
    }
}

# Rewrite JSONL deterministically (newest first, id as tiebreaker)
$sorted = $existing.Values | Sort-Object @{ Expression = 'localDate'; Descending = $true }, id
$sorted | ForEach-Object { $_ | ConvertTo-Json -Compress -Depth 5 } |
    Set-Content -Path $NormalizedPath -Encoding utf8

# Persist manifest
$manifest = [pscustomobject]@{
    accounts = [pscustomobject]$accounts
    fetches  = $fetches
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -Path $ManifestPath -Encoding utf8

Write-Host ""
Write-Host ("Imported {0} transactions across {1} file(s)" -f $totalIn, $Files.Count) -ForegroundColor Cyan
Write-Host ("  New: {0}  Updated/seen: {1}  Cache total: {2}" -f $newCount, $updatedCount, $existing.Count)
Write-Host ("  Cache: {0}" -f $CacheRoot)
