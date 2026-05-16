# Shared helper: loads .banksync-analysis/rules.json with fallback defaults.
# Dot-source from other scripts:  . (Join-Path $PSScriptRoot '_Rules.ps1')

function Get-BankSyncRules {
    param(
        [string]$Path = (Join-Path $PSScriptRoot 'rules.json')
    )

    $defaults = [pscustomobject]@{
        defaultAccountId   = 'P45rzOvVJ7uA59M1o3REU5gvZvmzQ7Igk6yM9'
        defaultAccountName = 'House Checking'
        virtualCategories  = [pscustomobject]@{}
        excludeFromHouseholdSpend = @('Transfer In','Transfer Out','Loan Payments Credit Card Payment')
        merchantAliases    = [pscustomobject]@{}
    }

    if (-not (Test-Path $Path)) { return $defaults }

    try {
        $r = Get-Content $Path -Raw | ConvertFrom-Json
    } catch {
        Write-Warning "Could not parse $Path : $_"
        return $defaults
    }

    foreach ($prop in 'defaultAccountId','defaultAccountName','virtualCategories','excludeFromHouseholdSpend','merchantAliases') {
        if ($null -eq $r.$prop) {
            Add-Member -InputObject $r -NotePropertyName $prop -NotePropertyValue $defaults.$prop -Force
        }
    }
    return $r
}

function Get-MerchantAliasMap {
    param($Rules)
    # Convert the rules.json merchantAliases (PSObject of pattern->name) into an
    # ordered list of [pscustomobject]@{ pattern; name } suitable for regex matching.
    $list = @()
    if ($Rules.merchantAliases) {
        foreach ($p in $Rules.merchantAliases.PSObject.Properties) {
            $list += [pscustomobject]@{ pattern = $p.Name; name = $p.Value }
        }
    }
    return ,$list
}

function Test-ExcludedFromSpend {
    param($Transaction, $Rules)
    foreach ($pat in $Rules.excludeFromHouseholdSpend) {
        if ($Transaction.category -like "$pat*") { return $true }
    }
    return $false
}

function Get-VirtualCategoryHits {
    param($Transaction, $Rules)
    $hits = @()
    if (-not $Rules.virtualCategories) { return $hits }
    foreach ($vc in $Rules.virtualCategories.PSObject.Properties) {
        foreach ($prefix in $vc.Value) {
            if ($Transaction.category -like "$prefix*") {
                $hits += $vc.Name
                break
            }
        }
    }
    return ,$hits
}
