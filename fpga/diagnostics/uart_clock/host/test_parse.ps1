$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'parse.ps1')
$line='CLK2 pfd=31.25 seq=0000000A ms=000003E8 lock=111 rst=111 freq=1111 delta=04C5,03AA,04B0,04C5 seen=F fault=0 now=0 ctrl=03 reset=0 cmd=74 cmds=0002 rxerr=0000'
$row=ConvertFrom-ClockDiagLine -Line $line
if (!$row.Healthy -or $row.Sequence -ne 10 -or $row.UptimeMs -ne 1000 -or !$row.SelftestMode -or !$row.AudioHeartbeat) { throw 'Normal state decode failed' }
if ([math]::Abs($row.AudioMHz-122.88) -gt 0.000001 -or [math]::Abs($row.Raw125MHz-125.0304) -gt 0.000001) { throw 'Frequency conversion failed' }
$bad=ConvertFrom-ClockDiagLine -Line ($line.Replace('lock=111 rst=111 freq=1111','lock=110 rst=000 freq=1110').Replace('now=0','now=9').Replace('ctrl=03','ctrl=00'))
if ($bad.Healthy -or $bad.CurrentFaultMask -ne 9 -or $bad.SelftestMode) { throw 'Eth clock failure decode failed' }
if ($null -ne (ConvertFrom-ClockDiagLine -Line 'noise')) { throw 'Invalid line accepted' }
if ($null -ne (ConvertFrom-ClockDiagLine -Line $line.Replace('freq=1111','freq=11X1'))) { throw 'Unknown bits accepted' }
if ($null -ne (ConvertFrom-ClockDiagLine -Line $line.Replace('pfd=31.25','pfd=125'))) { throw 'Wrong build version accepted' }
if ($null -eq (ConvertFrom-ClockDiagLine -Line ($line+"`r`n"))) { throw 'CRLF input rejected' }
Write-Host '[HOST_PARSE_PASS] normal/fault states, numeric conversion, malformed/version rejection, CRLF'
