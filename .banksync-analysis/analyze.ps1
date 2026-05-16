param(
    [string[]]$Files
)

# Load and combine all transaction pages
$all = @()
foreach ($f in $Files) {
    $d = Get-Content $f -Raw | ConvertFrom-Json
    $all += $d.transactions
}

# Deduplicate by id
$txns = $all | Sort-Object id -Unique
Write-Host "===== OVERVIEW =====" -ForegroundColor Cyan
Write-Host "Total unique txns: $($txns.Count)"
$min = ($txns | Sort-Object date | Select-Object -First 1).date
$max = ($txns | Sort-Object date -Descending | Select-Object -First 1).date
Write-Host "Range: $min  ->  $max"

$totalDebit = [math]::Round((($txns | Measure-Object -Property debitAmount -Sum).Sum), 2)
$totalCredit = [math]::Round((($txns | Measure-Object -Property creditAmount -Sum).Sum), 2)
Write-Host "Total debits (out): `$$totalDebit"
Write-Host "Total credits (in): `$$totalCredit"
Write-Host "Net: `$$([math]::Round(($totalCredit - $totalDebit),2))"

Write-Host "`n===== TOP CATEGORIES (by spend) =====" -ForegroundColor Cyan
$txns | Where-Object {$_.debitAmount -gt 0} |
    Group-Object category |
    Select-Object @{n='Category';e={$_.Name}},
                  @{n='Count';e={$_.Count}},
                  @{n='Total';e={[math]::Round((($_.Group | Measure-Object debitAmount -Sum).Sum),2)}} |
    Sort-Object Total -Descending |
    Select-Object -First 20 |
    Format-Table -AutoSize

Write-Host "`n===== TOP MERCHANTS (by spend) =====" -ForegroundColor Cyan
$txns | Where-Object {$_.debitAmount -gt 0 -and $_.merchantName} |
    Group-Object merchantName |
    Select-Object @{n='Merchant';e={$_.Name}},
                  @{n='Count';e={$_.Count}},
                  @{n='Total';e={[math]::Round((($_.Group | Measure-Object debitAmount -Sum).Sum),2)}},
                  @{n='Avg';e={[math]::Round((($_.Group | Measure-Object debitAmount -Average).Average),2)}} |
    Sort-Object Total -Descending |
    Select-Object -First 30 |
    Format-Table -AutoSize

Write-Host "`n===== MONTHLY SPEND =====" -ForegroundColor Cyan
$txns | ForEach-Object {
    $dt = [datetime]$_.date
    [pscustomobject]@{
        Month   = $dt.ToString('yyyy-MM')
        Debit   = $_.debitAmount
        Credit  = $_.creditAmount
        Cat     = $_.category
        Merch   = $_.merchantName
    }
} | Group-Object Month |
  ForEach-Object {
      [pscustomobject]@{
          Month  = $_.Name
          Spend  = [math]::Round((($_.Group | Measure-Object Debit -Sum).Sum),2)
          Income = [math]::Round((($_.Group | Measure-Object Credit -Sum).Sum),2)
          Count  = $_.Count
      }
  } | Sort-Object Month | Format-Table -AutoSize

Write-Host "`n===== TOP 25 LARGEST DEBITS =====" -ForegroundColor Cyan
$txns | Where-Object {$_.debitAmount -gt 0} |
    Sort-Object debitAmount -Descending |
    Select-Object -First 25 @{n='Date';e={([datetime]$_.date).ToString('yyyy-MM-dd')}},
                            @{n='Amount';e={$_.debitAmount}},
                            merchantName,
                            @{n='Category';e={$_.category}},
                            @{n='Description';e={if($_.description.Length -gt 80){$_.description.Substring(0,80)}else{$_.description}}} |
    Format-Table -AutoSize -Wrap

Write-Host "`n===== RECURRING SUBSCRIPTIONS / FEES (heuristic) =====" -ForegroundColor Cyan
# Look for merchants with >=3 charges of similar amount
$txns | Where-Object {$_.debitAmount -gt 0 -and $_.merchantName} |
    Group-Object merchantName |
    Where-Object {$_.Count -ge 3} |
    ForEach-Object {
        $amts = $_.Group | Select-Object -ExpandProperty debitAmount
        $stdev = if ($amts.Count -gt 1) { [math]::Round([math]::Sqrt((($amts | ForEach-Object { ($_ - ($amts|Measure-Object -Average).Average) * ($_ - ($amts|Measure-Object -Average).Average) } | Measure-Object -Sum).Sum / $amts.Count)),2) } else { 0 }
        $avg = [math]::Round((($_.Group | Measure-Object debitAmount -Average).Average),2)
        $tot = [math]::Round((($_.Group | Measure-Object debitAmount -Sum).Sum),2)
        [pscustomobject]@{
            Merchant = $_.Name
            Count    = $_.Count
            AvgAmt   = $avg
            StDev    = $stdev
            Total    = $tot
            Cat      = ($_.Group[0].category)
        }
    } | Where-Object {$_.StDev -lt ($_.AvgAmt * 0.25 + 1)} |
      Sort-Object Total -Descending |
      Select-Object -First 30 |
      Format-Table -AutoSize

Write-Host "`n===== ATM / FEES / OVERDRAFT =====" -ForegroundColor Cyan
$txns | Where-Object {
    $_.description -match '(ATM|FEE|OVERDRAFT|NSF|INSUFFICIENT|FOREIGN TRANSACTION|MAINTENANCE|SERVICE CHARGE)' -or
    $_.category -match 'Fee|ATM'
} | Sort-Object date -Descending |
  Select-Object @{n='Date';e={([datetime]$_.date).ToString('yyyy-MM-dd')}}, debitAmount, merchantName, category, @{n='Desc';e={if($_.description.Length -gt 70){$_.description.Substring(0,70)}else{$_.description}}} |
  Format-Table -AutoSize -Wrap

Write-Host "`n===== INCOME / TRANSFERS IN =====" -ForegroundColor Cyan
$txns | Where-Object {$_.creditAmount -gt 100} |
    Sort-Object creditAmount -Descending |
    Select-Object -First 20 @{n='Date';e={([datetime]$_.date).ToString('yyyy-MM-dd')}}, creditAmount, merchantName, category, @{n='Desc';e={if($_.description.Length -gt 70){$_.description.Substring(0,70)}else{$_.description}}} |
    Format-Table -AutoSize -Wrap
