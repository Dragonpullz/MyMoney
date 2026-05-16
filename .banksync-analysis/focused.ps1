param([string[]]$Files)
$all = @()
foreach ($f in $Files) { $all += (Get-Content $f -Raw | ConvertFrom-Json).transactions }
$txns = $all | Sort-Object id -Unique

$out = @()
$coffee = $txns | Where-Object {$_.category -match 'Coffee'}
$out += "Coffee txns: $($coffee.Count)  total: `$$([math]::Round((($coffee|Measure-Object debitAmount -Sum).Sum),2))  avg: `$$([math]::Round((($coffee|Measure-Object debitAmount -Average).Average),2))"

$ff = $txns | Where-Object {$_.category -match 'Fast Food'}
$out += "FastFood: $($ff.Count) total `$$([math]::Round((($ff|Measure-Object debitAmount -Sum).Sum),2))  avg `$$([math]::Round((($ff|Measure-Object debitAmount -Average).Average),2))"

$rest = $txns | Where-Object {$_.category -match 'Restaurant'}
$out += "Restaurants: $($rest.Count) total `$$([math]::Round((($rest|Measure-Object debitAmount -Sum).Sum),2))  avg `$$([math]::Round((($rest|Measure-Object debitAmount -Average).Average),2))"

$eatOut = $txns | Where-Object {$_.category -match 'Coffee|Fast Food|Restaurant'}
$out += "DiningOut TOTAL: `$$([math]::Round((($eatOut|Measure-Object debitAmount -Sum).Sum),2)) in $($eatOut.Count) txns"

$instacart = $txns | Where-Object {$_.merchantName -match 'Instacart' -or $_.description -match 'INSTACART'}
$out += "Instacart: $($instacart.Count) trips total `$$([math]::Round((($instacart|Measure-Object debitAmount -Sum).Sum),2)) avg `$$([math]::Round((($instacart|Measure-Object debitAmount -Average).Average),2))"

$inStoreGroc = $txns | Where-Object {$_.merchantName -in @('Food 4 Less',"Trader Joe's",'Costco','Ralphs') -and $_.debitAmount -gt 0}
$out += "In-store grocery (F4L/TJ/Costco/Ralphs): $($inStoreGroc.Count) trips avg `$$([math]::Round((($inStoreGroc|Measure-Object debitAmount -Average).Average),2))"

$subs = @('Netflix','HBO Max','Spotify','Crunchyroll','MLB','OpenAI','GitHub')
foreach ($s in $subs) {
    $g = $txns | Where-Object {$_.merchantName -eq $s -and $_.debitAmount -gt 0}
    if ($g) { $out += ("{0}: {1} charges, total `${2}, avg `${3}" -f $s, $g.Count, ([math]::Round((($g|Measure-Object debitAmount -Sum).Sum),2)), ([math]::Round((($g|Measure-Object debitAmount -Average).Average),2))) }
}
$subTot = $txns | Where-Object {$_.merchantName -in $subs}
$out += "All listed subs total: `$$([math]::Round((($subTot|Measure-Object debitAmount -Sum).Sum),2))"

# Gas - see if we can save by going Costco
$gas = $txns | Where-Object {$_.category -match 'Transportation Gas'}
$out += "Gas: $($gas.Count) total `$$([math]::Round((($gas|Measure-Object debitAmount -Sum).Sum),2)) avg `$$([math]::Round((($gas|Measure-Object debitAmount -Average).Average),2))"
$gas | Group-Object merchantName | Sort-Object {($_.Group | Measure-Object debitAmount -Sum).Sum} -Descending | Select-Object -First 10 @{n='M';e={$_.Name}},Count,@{n='Total';e={[math]::Round((($_.Group|Measure-Object debitAmount -Sum).Sum),2)}},@{n='Avg';e={[math]::Round((($_.Group|Measure-Object debitAmount -Average).Average),2)}} | ForEach-Object { $out += ($_ | Out-String).Trim() }

# Payroll trend
$payroll = $txns | Where-Object {$_.description -match 'PAYROLL|DIRECT DEP'}
$out += "`n--- Payroll deposits ---"
$payroll | Sort-Object date | ForEach-Object {
    $out += ("{0}  +`${1}  {2}" -f ([datetime]$_.date).ToString('yyyy-MM-dd'), $_.creditAmount, ($_.description.Substring(0,[Math]::Min(60,$_.description.Length))))
}

# Cash withdrawals (transfers out + ATM)
$cash = $txns | Where-Object {$_.description -match 'WITHDRAWAL|ATM' -and $_.debitAmount -gt 0}
$out += "`n--- Cash withdrawals (>0) ---"
$out += "Cash withdrawal events: $($cash.Count) total `$$([math]::Round((($cash|Measure-Object debitAmount -Sum).Sum),2))"

$out -join "`n" | Out-File "c:\Users\timwr\OneDrive\Code\Showshare\.banksync-analysis\focused.txt" -Encoding utf8
Write-Host "DONE"
