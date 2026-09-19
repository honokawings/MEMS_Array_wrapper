param(
    [string]$Port='COM3',
    [ValidateRange(1,300)][int]$Seconds=30,
    [ValidateSet('','s','r','c','t','h')][string]$Command='',
    [switch]$SelfTest,
    [string]$OutputDirectory=''
)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'parse.ps1')
if ($SelfTest -and $Command) { throw 'Use either -SelfTest or -Command.' }
if ($SelfTest -and $Seconds -lt 15) { throw '-SelfTest requires at least 15 seconds.' }
$diagRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../../..'))
if (!$OutputDirectory) { $OutputDirectory=Join-Path $diagRoot ('log/clock_uart/capture_'+(Get-Date -Format 'yyyyMMdd_HHmmss')) }
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$OutputDirectory=[IO.Path]::GetFullPath($OutputDirectory)
$serial=[IO.Ports.SerialPort]::new($Port,115200,[IO.Ports.Parity]::None,8,[IO.Ports.StopBits]::One)
$serial.Handshake=[IO.Ports.Handshake]::None
$serial.DtrEnable=$false; $serial.RtsEnable=$false; $serial.ReadTimeout=100; $serial.WriteTimeout=1000
$serial.NewLine="`n"
$raw=[IO.StreamWriter]::new((Join-Path $OutputDirectory 'raw.log'),$false,[Text.UTF8Encoding]::new($false))
$parsed=[Collections.Generic.List[object]]::new()
$sent=[Collections.Generic.List[object]]::new()
$invalid=0; $firstValidAt=$null; $last=$null; $missing=0; $restarts=0
$checks=[ordered]@{reset_asserted=$false; reset_released=$false; mode_on=$false; mode_off=$false; clear_ack=$false; status_ack=$false; audio_heartbeat_changed=$false}
$schedule=@(@{At=1;Byte='r'},@{At=4;Byte='t'},@{At=6;Byte='t'},@{At=8;Byte='c'},@{At=10;Byte='s'})
$next=0; $baseCommands=0; $firstHeartbeat=$null; $commandSent=$false
$watch=[Diagnostics.Stopwatch]::StartNew()
try {
    $serial.Open()
    Write-Host "Opened $Port at 115200 8N1. Waiting for CLK2 records..."
    while ($watch.Elapsed.TotalSeconds -lt $Seconds) {
        # Never send commands until a valid diagnostic version has identified itself.
        if ($null -ne $firstValidAt) {
            if ($Command -and !$commandSent) {
                $serial.Write($Command);$commandSent=$true
                $sent.Add([pscustomobject]@{Time=$watch.Elapsed.TotalSeconds;Command=$Command})
            }
            if ($SelfTest -and $next -lt $schedule.Count -and ($watch.Elapsed.TotalSeconds-$firstValidAt) -ge $schedule[$next].At) {
                $byte=$schedule[$next].Byte
                $serial.Write($byte)
                $sent.Add([pscustomobject]@{Time=$watch.Elapsed.TotalSeconds;Command=$byte;ExpectedCounter=(($baseCommands+$next+1)%65536)})
                Write-Host "[COMMAND] $byte"
                $next++
            }
        }
        try { $line=$serial.ReadLine().TrimEnd([char[]]"`r`n") }
        catch [TimeoutException] { continue }
        $raw.WriteLine($line);$raw.Flush()
        $row=ConvertFrom-ClockDiagLine -Line $line
        if ($null -eq $row) { $invalid++;Write-Host "[UNPARSED] $line";continue }
        if ($null -eq $firstValidAt) { $firstValidAt=$watch.Elapsed.TotalSeconds;$baseCommands=[int]$row.Commands }
        if ($null -ne $last) {
            if ($row.Sequence -lt $last.Sequence -and $row.UptimeMs -lt $last.UptimeMs) { $restarts++ }
            else {
                $gap=([long]$row.Sequence-[long]$last.Sequence+4294967296)%4294967296
                if ($gap -gt 1) { $missing+=($gap-1) }
            }
        }
        if ($row.Healthy) {
            if ($null -eq $firstHeartbeat) { $firstHeartbeat=$row.AudioHeartbeat }
            elseif ($firstHeartbeat -ne $row.AudioHeartbeat) { $checks.audio_heartbeat_changed=$true }
        }
        if ($SelfTest) {
            $stage=([int]$row.Commands-$baseCommands+65536)%65536
            if ($stage -eq 1 -and $row.LastCommandHex -eq '72') {
                if ($row.ResetActive -and $row.ResetBits -eq '000') { $checks.reset_asserted=$true }
                if (!$row.ResetActive -and $row.Healthy) { $checks.reset_released=$true }
            }
            if ($stage -eq 2 -and $row.LastCommandHex -eq '74' -and $row.SelftestMode) { $checks.mode_on=$true }
            if ($stage -eq 3 -and $row.LastCommandHex -eq '74' -and !$row.SelftestMode) { $checks.mode_off=$true }
            if ($stage -eq 4 -and $row.LastCommandHex -eq '63' -and $row.StickyFaultMask -eq 0) { $checks.clear_ack=$true }
            if ($stage -eq 5 -and $row.LastCommandHex -eq '73') { $checks.status_ack=$true }
        }
        $parsed.Add($row);$last=$row
        Write-Host ('[CLK2] ms={0} lock={1} rst={2} freq={3} MHz={4:F3}/{5:F3}/{6:F3}/{7:F3} now={8:X1} history={9:X1} mode={10} rxerr={11}' -f
            $row.UptimeMs,$row.LockBits,$row.ResetBits,$row.FrequencyBits,$row.Raw125MHz,$row.Clock96MHz,$row.AudioMHz,$row.EthernetMHz,
            $row.CurrentFaultMask,$row.StickyFaultMask,$row.SelftestMode,$row.ReceiveErrors)
    }
} finally {
    if ($serial.IsOpen) { $serial.Close() };$serial.Dispose();$raw.Dispose()
}
$status='NO_DIAGNOSTIC_RECORDS'
if ($parsed.Count -gt 0) {
    $tail=@($parsed | Select-Object -Last 4)
    $healthyTail=($tail.Count -eq 4 -and @($tail | Where-Object { !$_.Healthy -or $_.UptimeMs -lt 1000 }).Count -eq 0)
    if ($healthyTail) { $status='CLOCKS_PASS' } else { $status='CLOCKS_NOT_READY_OR_FAILED' }
    if ($SelfTest -and $healthyTail) {
        if (@($checks.Values | Where-Object { !$_ }).Count -eq 0 -and $next -eq 5) { $status='PASS' }
        else { $status='CONTROL_TEST_INCOMPLETE_OR_FAILED' }
    }
    if ($last.ReceiveErrors -ne 0 -or $missing -ne 0 -or $invalid -gt 1 -or $restarts -gt 0) { $status='SERIAL_OR_SESSION_ISSUE' }
    elseif ($last.StickyFaultMask -ne 0 -and $healthyTail) { $status='CLOCKS_RECOVERED_WITH_HISTORY' }
}
$summary=[ordered]@{Status=$status;Port=$Port;Baud=115200;DurationSeconds=$Seconds;ValidRecords=$parsed.Count;
    InvalidLines=$invalid;MissingRecords=$missing;SessionRestarts=$restarts;SelfTest=[bool]$SelfTest;Checks=$checks;
    CommandsSent=@($sent.ToArray());Latest=$last;GeneratedAt=(Get-Date).ToString('o')}
ConvertTo-Json -InputObject @($parsed.ToArray()) -Depth 6 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'records.json') -Encoding UTF8
$summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'summary.json') -Encoding UTF8
Write-Host "[$status] $OutputDirectory"
