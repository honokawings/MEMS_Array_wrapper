param(
    [string]$Port='COM3',[ValidateRange(1,300)][int]$Seconds=30,
    [ValidateSet('','s','r','c','t','h')][string]$Command='',
    [switch]$SelfTest,[string]$OutputDirectory=''
)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'parse_system_uart.ps1')
. (Join-Path $PSScriptRoot 'audio_uart.ps1') -Port $Port
if ($SelfTest -and $Command) { throw 'Use either -SelfTest or -Command.' }
if ($SelfTest -and $Seconds -lt 15) { throw '-SelfTest requires at least 15 seconds.' }
$diagRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
if (!$OutputDirectory) { $OutputDirectory=Join-Path $diagRoot ('log/system_uart/capture_'+(Get-Date -Format 'yyyyMMdd_HHmmss')) }
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$OutputDirectory=[IO.Path]::GetFullPath($OutputDirectory)
foreach ($file in @('raw.log','records.json','audio_records.json','summary.json')) {
    if (Test-Path -LiteralPath (Join-Path $OutputDirectory $file)) { throw "Refusing to overwrite $file" }
}
$serial=[IO.Ports.SerialPort]::new($Port,115200,[IO.Ports.Parity]::None,8,[IO.Ports.StopBits]::One)
$serial.Handshake=[IO.Ports.Handshake]::None
$serial.DtrEnable=$false;$serial.RtsEnable=$false;$serial.ReadTimeout=100;$serial.WriteTimeout=1000;$serial.NewLine="`n"
$raw=[IO.StreamWriter]::new((Join-Path $OutputDirectory 'raw.log'),$false,[Text.UTF8Encoding]::new($false))
$parsed=[Collections.Generic.List[object]]::new();$sent=[Collections.Generic.List[object]]::new()
$audioRecords=[Collections.Generic.List[object]]::new()
$invalid=0;$missing=0;$restarts=0;$last=$null;$firstValidAt=$null;$baseCommands=0;$next=0;$commandSent=$false
$watch=[Diagnostics.Stopwatch]::StartNew()
try {
    $serial.Open();Write-Host "Opened $Port 115200 8N1; waiting for SYS3..."
    while ($watch.Elapsed.TotalSeconds -lt $Seconds) {
        if ($null -ne $firstValidAt) {
            $byte=''
            if ($Command -and !$commandSent) { $byte=$Command;$commandSent=$true }
            if ($SelfTest) {
                $elapsed=$watch.Elapsed.TotalSeconds-$firstValidAt
                if ($next -eq 0 -and $elapsed -ge 1) { $byte='r';$next=1 }
                # Windows may still be probing its address after link-up. Start
                # BIST only after ARP resolves, otherwise its initial frames can
                # overflow the finite transmit queue before the peer is ready.
                elseif ($next -eq 1 -and $elapsed -ge 4 -and $last.ClocksHealthy -and $last.AudioFresh -and $last.EthFresh -and $last.PhyReady -and $last.LinkUp -and $last.PeerValid -and $last.CalibrationDone -and $last.Commands -eq (($baseCommands+1)%65536) -and !$last.SelftestMode) { $byte='t';$next=2 }
            }
            if ($byte) {
                $serial.Write($byte);$sent.Add([pscustomobject]@{Time=$watch.Elapsed.TotalSeconds;Command=$byte})
                Write-Host "[COMMAND] $byte"
            }
        }
        try { $line=$serial.ReadLine().TrimEnd([char[]]"`r`n") } catch [TimeoutException] { continue }
        $raw.WriteLine($line);$raw.Flush()
        $audioRow=ConvertFrom-AudioUartLine -Line $line
        if($null -ne $audioRow){$audioRecords.Add($audioRow);Write-Host "[$($audioRow.Tag)] channel=$($audioRow.ActiveChannel) fresh=$($audioRow.Fresh) pending=$($audioRow.Pending)";continue}
        $row=ConvertFrom-SystemUartLine -Line $line
        if ($null -eq $row) { $invalid++;Write-Host "[UNPARSED] $line";continue }
        if ($null -eq $firstValidAt) { $firstValidAt=$watch.Elapsed.TotalSeconds;$baseCommands=[int]$row.Commands }
        if ($null -ne $last) {
            if ($row.Sequence -lt $last.Sequence -and $row.UptimeMs -lt $last.UptimeMs) { $restarts++ }
            else {
                $gap=([long]$row.Sequence-[long]$last.Sequence+4294967296)%4294967296
                if ($gap -gt 1) { $missing+=($gap-1) }
            }
        }
        $parsed.Add($row);$last=$row
        Write-Host ('[SYS3] ms={0} clocks={1} fresh={2:X1} PHY={3}/{4} id={5} ready={6} link={7} retries={8} ARP={9}/{10} peer={11} UDP={12} RX={13} BIST={14}/{15}/{16}' -f
            $row.UptimeMs,$row.ClocksHealthy,$row.FreshMask,$row.PhyState,$row.ConfigStep,$row.PhyId,$row.PhyReady,$row.LinkUp,$row.PhyRetries,
            $row.ArpRequestsSent,$row.ArpAccepted,$row.PeerValid,$row.UdpSent,$row.RxFrames,$row.SelftestMode,$row.SelftestPass,$row.SelftestTxPass)
    }
} finally {
    if ($serial.IsOpen) { $serial.Close() };$serial.Dispose();$raw.Dispose()
}
$stage='NO_SYS3_RECORDS';$udpProgress=$false;$bistPass=$false
if ($parsed.Count -gt 0) {
    $tail=@($parsed | Select-Object -Last 4)
    $udpProgress=($tail.Count -eq 4 -and $last.EthFresh -and $last.UdpSent -gt $tail[0].UdpSent -and $last.StreamEpoch -eq $tail[0].StreamEpoch)
    $bistPass=($last.AudioFresh -and $last.EthFresh -and $last.SelftestMode -and $last.SelftestPass -and $last.SelftestTxPass -and !$last.SelftestFail -and !$last.SelftestTxFail)
    if (!$last.ClocksHealthy) { $stage='CLOCKS_OR_RESET' }
    elseif (!$last.EthFresh) { $stage='ETH_SNAPSHOT_STALE' }
    elseif (!$last.PhyResetReleased) { $stage='PHY_IN_RESET' }
    elseif (!$last.PhyReady) { $stage='PHY_MDIO_OR_CONFIG' }
    elseif (!$last.LinkUp) { $stage='PHY_LINK_DOWN' }
    elseif (!$last.AudioFresh -or !$last.CalibrationDone -or !$last.Acquiring) { $stage='ACQUISITION_NOT_READY' }
    elseif (!$last.PeerValid) { $stage='ARP_PENDING' }
    elseif (!$udpProgress) { $stage='UDP_NOT_PROGRESSING' }
    else { $stage='FPGA_UDP_PROGRESS' }
    if ($invalid -gt 1 -or $missing -ne 0 -or $restarts -gt 0 -or $last.ReceiveErrors -ne 0) { $stage='UART_OR_SESSION_ISSUE' }
}
$summary=[ordered]@{Stage=$stage;Scope='FPGA telemetry only; PC packet capture and PCM validation are separate';Port=$Port;Baud=115200;
    DurationSeconds=$Seconds;ValidRecords=$parsed.Count;InvalidLines=$invalid;MissingRecords=$missing;SessionRestarts=$restarts;
    SelfTestRequested=[bool]$SelfTest;FpgaSelftestPass=$bistPass;UdpCounterProgress=$udpProgress;
    CommandsSent=@($sent.ToArray());Latest=$last;AudioRecords=$audioRecords.Count;LatestAudio=($audioRecords | Select-Object -Last 1);GeneratedAt=(Get-Date).ToString('o')}
ConvertTo-Json -InputObject @($parsed.ToArray()) -Depth 6 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'records.json') -Encoding UTF8
ConvertTo-Json -InputObject @($audioRecords.ToArray()) -Depth 6 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'audio_records.json') -Encoding UTF8
$summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'summary.json') -Encoding UTF8
Write-Host "[$stage] $OutputDirectory"
