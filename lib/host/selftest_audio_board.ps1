param(
    [string]$Port='COM3',
    [string]$OutputDirectory='',
    [ValidateRange(1,30)][int]$ApplyTimeoutSeconds=5,
    [ValidateRange(100,2000)][int]$SampleIntervalMilliseconds=300,
    [switch]$AllChannels,
    [switch]$Offline
)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'parse_system_uart.ps1')
. (Join-Path $PSScriptRoot 'audio_uart.ps1') -Port $Port
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))

# The offline path performs no serial-port operation and no waiting. It checks
# this script's reusable parser against synthetic and actual simulation frames.
if($Offline){
    $words=[uint32[]](123,5,255,255,0x200000,0x300000,0x200000,0x300000,21,22,0,0xFFFFFF,22,0)
    $sample='I2S1 '+(($words | ForEach-Object {'{0:X8}' -f $_}) -join ' ')
    $row=ConvertFrom-AudioUartLine $sample
    if(!$row.Fresh -or $row.Pending -or $row.ActiveChannel -ne 127 -or $row.ActiveEvenGain -ne 0.5 -or $row.ActiveOddGain -ne 0.75 -or $row.LastPcm -ne -1){throw 'Offline synthetic audio fields'}
    $words[1]=6
    $row=ConvertFrom-AudioUartLine ('GAIN1 '+(($words | ForEach-Object {'{0:X8}' -f $_}) -join ' '))
    if($row.Fresh -or !$row.Pending -or $null -ne $row.ActiveChannel -or $null -ne $row.VerifiedFrames){throw 'Offline stale state must be unavailable'}
    $audioCount=0;$systemCount=0
    $logPath=Join-Path $taskRoot 'log/audio_uart/rtl_uart.log'
    if(Test-Path -LiteralPath $logPath){
        foreach($line in Get-Content -LiteralPath $logPath){
            if(!$line){continue}
            if($line.StartsWith('SYS3 ')){
                if($null -eq (ConvertFrom-SystemUartLine $line)){throw 'Offline malformed SYS3'};$systemCount++
            }else{
                if($null -eq (ConvertFrom-AudioUartLine $line)){throw 'Offline malformed audio line'};$audioCount++
            }
        }
        if($audioCount -lt 25 -or $systemCount -lt 2){throw 'Offline actual simulation coverage insufficient'}
    }
    [pscustomobject]@{Status='OFFLINE_PASS';SerialOpened=$false;SyntheticCases=2;AudioLines=$audioCount;SystemLines=$systemCount;
        Scope='Parser and script preparation only; no board test performed'} | ConvertTo-Json
    return
}

if(!$OutputDirectory){$OutputDirectory=Join-Path $taskRoot ('log/i2s_parity/board_audio_'+(Get-Date -Format 'yyyyMMdd_HHmmss'))}
$OutputDirectory=[IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
foreach($name in @('raw.log','audio_records.json','system_records.json','cases.json','summary.json')){
    if(Test-Path -LiteralPath (Join-Path $OutputDirectory $name)){throw "Refusing to overwrite $name in $OutputDirectory"}
}
$raw=[IO.StreamWriter]::new((Join-Path $OutputDirectory 'raw.log'),$false,[Text.UTF8Encoding]::new($false))
$serial=[IO.Ports.SerialPort]::new($Port,115200,[IO.Ports.Parity]::None,8,[IO.Ports.StopBits]::One)
$serial.Handshake=[IO.Ports.Handshake]::None;$serial.DtrEnable=$false;$serial.RtsEnable=$false
$serial.ReadTimeout=200;$serial.WriteTimeout=1000;$serial.NewLine="`n"
$script:audioRows=[Collections.Generic.List[object]]::new()
$script:systemRows=[Collections.Generic.List[object]]::new()
$script:cases=[Collections.Generic.List[object]]::new()
$script:commands=[Collections.Generic.List[object]]::new()
$script:lastAudio=$null;$script:lastSystem=$null;$script:validFrameSeen=$false;$script:initialPartialLines=0
$initial=$null;$failure=$null;$restored=$false;$status='FAIL'
$sessionWatch=[Diagnostics.Stopwatch]::StartNew()

function Assert-AudioBoard {
    param([bool]$Condition,[string]$Message)
    if(!$Condition){throw $Message}
}
function Read-AudioBoardLine {
    try{$line=$serial.ReadLine().TrimEnd([char[]]"`r`n")}catch [TimeoutException]{return $null}
    $raw.WriteLine($line);$raw.Flush()
    if(!$line){return $null}
    $row=ConvertFrom-AudioUartLine $line
    if($null -ne $row){
        if($null -ne $script:lastAudio){
            $expected=([long]$script:lastAudio.Sequence+1)%4294967296
            Assert-AudioBoard ($row.Sequence -eq $expected) 'Independent audio response sequence is missing or reordered.'
        }
        Assert-AudioBoard ($row.QueueOverflows -eq 0) 'Audio command queue reported an overflow.'
        if($row.Fresh){Assert-AudioBoard ($row.SerialErrors -eq 0) 'FPGA I2S serial monitor reported a digital serialization error.'}
        $script:audioRows.Add($row);$script:lastAudio=$row;$script:validFrameSeen=$true
        return $row
    }
    $sys=ConvertFrom-SystemUartLine $line
    if($null -ne $sys){
        if($null -ne $script:lastSystem){
            $expected=([long]$script:lastSystem.Sequence+1)%4294967296
            Assert-AudioBoard ($sys.Sequence -eq $expected) 'SYS3 response sequence is missing or reordered.'
        }
        Assert-AudioBoard ($sys.ReceiveErrors -eq 0) 'UART RX reported a framing error.'
        $script:systemRows.Add($sys);$script:lastSystem=$sys;$script:validFrameSeen=$true
        return $null
    }
    # Opening mid-line can yield one initial suffix. Once framing is acquired,
    # every complete line must belong to SYS3, I2S1 or GAIN1.
    if(!$script:validFrameSeen -and $script:initialPartialLines -eq 0){$script:initialPartialLines++;return $null}
    throw "Unrecognized or interleaved UART frame: $line"
}
function Send-AudioBoard {
    param([string]$Command,[int]$ExpectedError=0)
    $tag=$(if($Command.StartsWith('@GAIN')){'GAIN1'}else{'I2S1'})
    $script:commands.Add([pscustomobject]@{Seconds=$sessionWatch.Elapsed.TotalSeconds;Command=$Command;ExpectedError=$ExpectedError})
    $raw.WriteLine('[TX] '+$Command);$raw.Flush();$serial.Write($Command+"`n")
    $watch=[Diagnostics.Stopwatch]::StartNew()
    while($watch.Elapsed.TotalSeconds -lt $ApplyTimeoutSeconds){
        $row=Read-AudioBoardLine
        if($null -eq $row){continue}
        Assert-AudioBoard ($row.Tag -eq $tag) "Response kind mismatch for $Command"
        Assert-AudioBoard ($row.ErrorCode -eq $ExpectedError) "Unexpected FPGA error $($row.ErrorCode) for $Command"
        return $row
    }
    throw "No independent $tag response to $Command within $ApplyTimeoutSeconds seconds."
}
function Wait-AudioApplied {
    param([string]$Query,[bool]$Enabled,[int]$Selected,[string]$Even='400000',[string]$Odd='400000')
    $watch=[Diagnostics.Stopwatch]::StartNew()
    do{
        $row=Send-AudioBoard $Query
        Assert-AudioBoard ($row.DesiredEnabled -eq $Enabled -and $row.DesiredChannel -eq $Selected) 'Desired I2S configuration did not persist.'
        Assert-AudioBoard ($row.DesiredEvenGainHex -eq $Even -and $row.DesiredOddGainHex -eq $Odd) 'Desired parity coefficients did not persist.'
        if($row.Fresh -and !$row.Pending){
            Assert-AudioBoard ($row.AudioResetReleased -and $row.ActiveEnabled -eq $Enabled -and $row.ActiveChannel -eq $Selected) 'Audio snapshot differs from requested I2S state.'
            Assert-AudioBoard ($row.ActiveEvenGainHex -eq $Even -and $row.ActiveOddGainHex -eq $Odd) 'Actual audio gains differ from requested values.'
            return $row
        }
    }while($watch.Elapsed.TotalSeconds -lt $ApplyTimeoutSeconds)
    throw 'Configuration remains pending or audio clock snapshot is unavailable.'
}
function Check-AudioProgress {
    param([string]$Name,[bool]$Enabled,[int]$Selected,[string]$Even='400000',[string]$Odd='400000')
    $first=Wait-AudioApplied '@I2S?' $Enabled $Selected $Even $Odd
    Start-Sleep -Milliseconds $SampleIntervalMilliseconds
    $second=Wait-AudioApplied '@I2S?' $Enabled $Selected $Even $Odd
    $frameDelta=([long]$second.OutputFrames-[long]$first.OutputFrames+4294967296)%4294967296
    $verifiedDelta=([long]$second.VerifiedFrames-[long]$first.VerifiedFrames+4294967296)%4294967296
    $receivedDelta=([long]$second.ReceivedSamples-[long]$first.ReceivedSamples+4294967296)%4294967296
    Assert-AudioBoard ($frameDelta -gt 0 -and $verifiedDelta -gt 0) 'I2S frames and independent verified-frame counter did not advance.'
    if($Enabled){Assert-AudioBoard ($receivedDelta -gt 0) 'Selected PCM channel did not deliver new samples.'}
    else{Assert-AudioBoard ($first.LastPcm -eq 0 -and $second.LastPcm -eq 0) 'I2S OFF did not emit zero samples.'}
    $script:cases.Add([pscustomobject]@{Name=$Name;Status='PASS';First=$first;Second=$second;
        OutputFramesDelta=$frameDelta;VerifiedFramesDelta=$verifiedDelta;ReceivedSamplesDelta=$receivedDelta})
    Write-Host "[PASS] $Name frames=+$frameDelta verified=+$verifiedDelta PCM=+$receivedDelta"
}
function Drain-AudioBoard {
    param([int]$Milliseconds=600)
    $watch=[Diagnostics.Stopwatch]::StartNew()
    while($watch.ElapsedMilliseconds -lt $Milliseconds){$null=Read-AudioBoardLine}
}
function Restore-AudioBoard {
    param($Original)
    $null=Send-AudioBoard '@GAIN=400000,400000'
    $null=Send-AudioBoard ('@I2S='+$Original.DesiredChannel)
    if(!$Original.DesiredEnabled){$null=Send-AudioBoard '@I2S=OFF'}
    $null=Wait-AudioApplied '@I2S?' ([bool]$Original.DesiredEnabled) ([int]$Original.DesiredChannel)
}

try{
    $serial.Open();$serial.DiscardInBuffer()
    Write-Host "Opened one $Port session: 115200 8N1; preparing independent audio tests."
    $initial=Send-AudioBoard '@I2S?'
    Assert-AudioBoard ($initial.Fresh -and $initial.AudioResetReleased) 'Initial audio snapshot is stale or audio reset is active.'
    $null=Send-AudioBoard '@GAIN=400000,400000'
    $selectedChannels=$(if($AllChannels){@(0..127)}else{@(0,1,127)})
    foreach($selected in $selectedChannels){
        $null=Send-AudioBoard ('@I2S='+$selected)
        Check-AudioProgress ('CHANNEL_'+$selected) $true $selected
    }
    $null=Send-AudioBoard '@I2S=OFF'
    Check-AudioProgress 'OFF_ZERO_WITH_CLOCKS_RUNNING' $false 127
    $null=Send-AudioBoard '@I2S=1'
    Check-AudioProgress 'RESTORE_FROM_OFF' $true 1
    $null=Send-AudioBoard '@GAIN=200000,300000'
    $gain=Wait-AudioApplied '@GAIN?' $true 1 '200000' '300000'
    Assert-AudioBoard ($gain.ActiveEvenGain -eq 0.5 -and $gain.ActiveOddGain -eq 0.75) 'Actual parity gain does not equal 0.5 / 0.75.'
    Check-AudioProgress 'PARITY_GAIN_HALF_THREE_QUARTERS' $true 1 '200000' '300000'
    $null=Send-AudioBoard '@GAIN=400000,400000'
    Check-AudioProgress 'PARITY_GAIN_RESTORE_UNITY' $true 1

    Drain-AudioBoard
    Assert-AudioBoard ($null -ne $script:lastSystem) 'No SYS3 frame is available for legacy side-effect checks.'
    $beforeLegacy=$script:lastSystem.Commands
    $before=Send-AudioBoard '@I2S?'
    # Deliberately bypass host validation for FPGA rejection tests. Legacy r/t
    # characters remain inside an '@' frame and must have no reset/mode effect.
    foreach($test in @(@{Command='@I2S=128';Error=2},@{Command='@GAIN=800000,400000';Error=2},@{Command='@I2S=strch';Error=1})){
        $row=Send-AudioBoard $test.Command $test.Error
        Assert-AudioBoard ($row.DesiredChannel -eq $before.DesiredChannel -and $row.DesiredEnabled -eq $before.DesiredEnabled -and
            $row.DesiredEvenGainHex -eq $before.DesiredEvenGainHex -and $row.DesiredOddGainHex -eq $before.DesiredOddGainHex) 'Rejected command modified desired controls.'
        $script:cases.Add([pscustomobject]@{Name=('REJECT_'+$test.Command);Status='PASS';Response=$row})
    }
    Drain-AudioBoard
    Assert-AudioBoard ($script:lastSystem.Commands -eq $beforeLegacy) 'Legacy letters inside an audio command invoked a system command.'

    # Preserve non-default controls through the authorized legacy system reset.
    $null=Send-AudioBoard '@I2S=17';$null=Send-AudioBoard '@GAIN=200000,300000'
    $null=Wait-AudioApplied '@GAIN?' $true 17 '200000' '300000'
    $script:commands.Add([pscustomobject]@{Seconds=$sessionWatch.Elapsed.TotalSeconds;Command='r';ExpectedError=0})
    $raw.WriteLine('[TX] r');$raw.Flush();$serial.Write('r')
    Check-AudioProgress 'SYSTEM_RESET_REPLAYS_CHANNEL_AND_GAINS' $true 17 '200000' '300000'
    Drain-AudioBoard
    Assert-AudioBoard ($script:lastSystem.Commands -eq (($beforeLegacy+1)%65536) -and $script:lastSystem.LastCommandHex -eq '72') 'SYS3 did not confirm exactly one legacy reset command.'
    Restore-AudioBoard $initial;$restored=$true
    $script:cases.Add([pscustomobject]@{Name='FINAL_RESTORE';Status='PASS';Response=$script:lastAudio})
    $status='PASS'
}catch{
    $failure=$_.Exception.Message
    Write-Host "[FAIL] $failure"
}finally{
    if($serial.IsOpen -and $null -ne $initial -and !$restored){
        try{Restore-AudioBoard $initial;$restored=$true}catch{$script:cases.Add([pscustomobject]@{Name='BEST_EFFORT_RESTORE';Status='FAIL';Detail=$_.Exception.Message})}
    }
    if($serial.IsOpen){$serial.Close()};$serial.Dispose();$raw.Dispose()
    $summary=[ordered]@{Status=$status;Failure=$failure;Port=$Port;Baud=115200;SingleSerialSession=$true;
        StartedFrom=$initial;FinalState=$script:lastAudio;ControlsRestored=$restored;FinalGainTarget='unity';
        AllChannelsRequested=[bool]$AllChannels;Cases=$script:cases.Count;AudioRecords=$script:audioRows.Count;SystemRecords=$script:systemRows.Count;
        InitialPartialLines=$script:initialPartialLines;CommandsSent=@($script:commands.ToArray());
        DurationSeconds=$sessionWatch.Elapsed.TotalSeconds;GeneratedAt=(Get-Date).ToString('o');
        Scope='FPGA digital I2S serialization, control/CDC and gain-register telemetry; DAC analog output and acoustic amplitude matching are not verified by this script';
        ResetEffect='Legacy r resets system and clears internal self-test mode; requested I2S/parity settings are replayed'}
    ConvertTo-Json -InputObject @($script:audioRows.ToArray()) -Depth 6 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'audio_records.json') -Encoding UTF8
    ConvertTo-Json -InputObject @($script:systemRows.ToArray()) -Depth 6 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'system_records.json') -Encoding UTF8
    ConvertTo-Json -InputObject @($script:cases.ToArray()) -Depth 7 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'cases.json') -Encoding UTF8
    $summary | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'summary.json') -Encoding UTF8
    Write-Host "[$status] $OutputDirectory"
}
if($status -ne 'PASS'){throw $failure}
