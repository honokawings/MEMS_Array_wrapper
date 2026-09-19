$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'parse_system_uart.ps1')
$words=[uint32[]]::new(34)
$words[0]=123;$words[1]=4567;$words[2]=0x0780783F
$words[3]=0x03AA04C5;$words[4]=0x04C504B0;$words[5]=0x00740002;$words[7]=7
$words[8]=0x0008068F;$words[12]=0x0002CBB9;$words[13]=0x001CC916
$words[14]=0x001975BB;$words[15]=0x1355102C;$words[16]=1234;$words[17]=3
$words[20]=0x102C;$words[21]=0xA006;$words[22]=2;$words[24]=1;$words[25]=16000
$words[26]=16002;$words[27]=2;$words[28]=0x30405060;$words[29]=0x1020
$words[30]=1;$words[32]=72
$line='SYS3 '+(($words | ForEach-Object { '{0:X8}' -f $_ }) -join ' ')
$row=ConvertFrom-SystemUartLine $line
if ($null -eq $row -or !$row.ClocksHealthy -or $row.FreshMask -ne 7) { throw 'Clock/fresh fields' }
if (!$row.SelftestMode -or !$row.SelftestPass -or !$row.SelftestTxPass -or !$row.CalibrationDone -or !$row.Heartbeat) { throw 'Audio/BIST fields' }
if ($row.PhyId -ne '001CC916' -or !$row.PhyReady -or !$row.LinkUp -or $row.PhyAddress -ne 5 -or $row.ConfigStep -ne 27 -or $row.PhyState -ne 9) { throw 'PHY fields' }
if (!$row.MdioRead -or !$row.MdioAck -or $row.MdioAddress -ne 5 -or $row.MdioRegister -ne 26 -or $row.MdioReadData -ne '102C') { throw 'MDIO fields' }
if ($row.PeerMac -ne '102030405060' -or !$row.PeerValid -or $row.UdpSent -ne 16000 -or $row.RxBytes -ne 72) { throw 'Network fields' }
if ([math]::Abs($row.MHz[0]-125.0304) -gt 0.00001 -or [math]::Abs($row.MHz[2]-122.88) -gt 0.00001) { throw 'Frequency units' }
foreach ($bad in @('',($line.Substring(1)),($line+' 00000000'),($line.Substring(0,$line.Length-1)),($line.Replace('SYS3','SYS2')),($line.Replace('001CC916','001XX916')))) {
    if ($null -ne (ConvertFrom-SystemUartLine $bad)) { throw "Malformed line accepted: [$bad]" }
}
$words[19]=[Convert]::ToUInt32('83D5AC50',16)
$row=ConvertFrom-SystemUartLine ('SYS3 '+(($words | ForEach-Object { '{0:X8}' -f $_ }) -join ' '))
if ($row.FailureState -ne 8 -or $row.FailureStep -ne 7 -or !$row.FailureRead -or $row.FailureAck -or $row.FailureRegister -ne 21 -or $row.FailureData -ne 'AC50') { throw 'Latched failure decode' }
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$rows=@(Get-Content -LiteralPath (Join-Path $root 'log/system_uart/rtl_uart.log') | Where-Object { $_ } | ForEach-Object {
    $value=ConvertFrom-SystemUartLine $_
    if ($null -eq $value) { throw 'RTL UART line failed host parsing' };$value
})
if ($rows.Count -lt 12 -or @($rows | Where-Object { $_.EthFresh -and $_.PeerValid -and $_.UdpSent -gt 0 -and $_.PhyId -eq '001CC916' }).Count -eq 0) { throw 'RTL end-to-end evidence missing' }
if (@($rows | Where-Object { $_.FreshMask -eq 3 }).Count -eq 0) { throw 'Stopped RX not observable' }
if (@($rows | Where-Object { $_.EthFresh -and $_.PhyRetries -gt 0 }).Count -eq 0) { throw 'MDIO fault evidence missing' }
Write-Host "[HOST_UART_PASS] synthetic field/error checks and $($rows.Count) actual RTL serial lines"
