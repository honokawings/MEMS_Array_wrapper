$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'audio_uart.ps1')
. (Join-Path $PSScriptRoot 'parse_system_uart.ps1')
$w=[uint32[]](0,5,255,255,0x200000,0x600000,0x200000,0x600000,11,12,3,0xFFFFFF,12,0)
$line='I2S1 '+(($w | ForEach-Object {'{0:X8}' -f $_}) -join ' ')
$row=ConvertFrom-AudioUartLine $line
if(!$row.Fresh -or $row.Pending -or $row.ActiveChannel -ne 127 -or !$row.ActiveEnabled -or $row.LastPcm -ne -1 -or $row.ActiveEvenGain -ne 0.5 -or $row.ActiveOddGain -ne 1.5 -or $row.VerifiedFrames -ne 12){throw 'Audio decode fields'}
foreach($bad in @('',($line+' 00000000'),$line.Replace('I2S1','SYS3'),$line.Replace('00000005','0000000g'),$line.Replace('I2S1 ','I2S1  '))){if($null -ne (ConvertFrom-AudioUartLine $bad)){throw 'Invalid audio response accepted'}}
$w[1]=6;$row=ConvertFrom-AudioUartLine ('GAIN1 '+(($w | ForEach-Object {'{0:X8}' -f $_}) -join ' '))
if($row.Fresh -or !$row.Pending -or $null -ne $row.ActiveChannel -or $null -ne $row.ActiveEvenGain -or $null -ne $row.OutputFrames){throw 'Stale snapshot must not expose active state'}
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$audio=0;$sys=0;$pending=0;$stale=0;$errors=0
foreach($line in Get-Content -LiteralPath (Join-Path $root 'log/audio_uart/rtl_uart.log')){
    if(!$line){continue}
    if($line.StartsWith('SYS3 ')){if($null -eq (ConvertFrom-SystemUartLine $line)){throw 'Mixed SYS3 malformed'};$sys++;continue}
    $row=ConvertFrom-AudioUartLine $line;if($null -eq $row){throw "RTL audio malformed: $line"}
    $audio++;if($row.Pending){$pending++};if(!$row.Fresh){$stale++};if($row.ErrorCode){$errors++}
}
if($audio -lt 25 -or $sys -lt 2 -or !$pending -or !$stale -or $errors -lt 5){throw 'RTL actual coverage missing'}
Write-Host "[HOST_AUDIO_UART_PASS] audio=$audio SYS3=$sys pending=$pending stale=$stale errors=$errors"

# Standalone set/query uses one session. These mocks never instantiate or open
# a real SerialPort; they exercise the same action function as powershell -File.
function New-TestAudioLine {
    param([string]$Tag='GAIN1',[uint32]$Flags=5,[uint32]$Desired=128,[uint32]$Active=128,
        [uint32]$DesiredEven=0,[uint32]$DesiredOdd=0x400000,
        [uint32]$ActiveEven=0,[uint32]$ActiveOdd=0x400000)
    $words=[uint32[]](0,$Flags,$Desired,$Active,$DesiredEven,$DesiredOdd,$ActiveEven,$ActiveOdd,11,12,0,0,12,0)
    $Tag+' '+(($words | ForEach-Object {'{0:X8}' -f $_}) -join ' ')
}
if(!('AudioUartOfflineSerial' -as [type])){
    # A .NET mock throws the same TimeoutException shape as SerialPort. A
    # PowerShell ScriptMethod would add an extra RuntimeException wrapper.
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
public sealed class AudioUartOfflineSerial {
    public bool IsOpen = false, Disposed = false;
    public int OpenCount = 0, CloseCount = 0, PurgeCount = 0;
    public Queue<string> Lines = new Queue<string>();
    public List<string> Sent = new List<string>();
    public void Open() { IsOpen = true; OpenCount++; }
    public void DiscardInBuffer() { PurgeCount++; }
    public void Write(string text) { Sent.Add(text); }
    public string ReadLine() {
        if (Lines.Count != 0) return Lines.Dequeue();
        System.Threading.Thread.Sleep(5);
        throw new TimeoutException("Offline mock read timeout");
    }
    public void Close() { IsOpen = false; CloseCount++; }
    public void Dispose() { Disposed = true; }
}
'@
}
function New-TestAudioSerial {
    param([string[]]$Lines)
    $mock=[AudioUartOfflineSerial]::new()
    foreach($text in $Lines){$mock.Lines.Enqueue($text)}
    return $mock
}
function Assert-TestAudioSession {
    param($Mock)
    if($Mock.OpenCount -ne 1 -or $Mock.CloseCount -ne 1 -or $Mock.PurgeCount -ne 1 -or !$Mock.Disposed -or $Mock.IsOpen){
        throw 'Standalone action must open/purge/close/dispose exactly one serial session'
    }
}
$mockChecks=0
$mock=New-TestAudioSerial @(
    (New-TestAudioLine -Flags 7 -ActiveEven 0x400000),
    (New-TestAudioLine))
$rows=@(Invoke-AudioUartAction -Action Gain -EvenGain 000000 -OddGain 400000 -Serial $mock)
if($rows.Count -ne 1 -or !$rows[0].Fresh -or $rows[0].Pending -or $rows[0].ActiveEvenGainHex -ne '000000' -or
    ($mock.Sent -join '') -ne "@GAIN=000000,400000`n@GAIN?`n"){throw 'Gain set/query final state or command construction'}
Assert-TestAudioSession $mock;$mockChecks++

$mock=New-TestAudioSerial @(
    (New-TestAudioLine -Tag I2S1 -Flags 4 -Desired 255 -Active 128),
    (New-TestAudioLine -Tag I2S1 -Desired 255 -Active 255))
$rows=@(Invoke-AudioUartAction -Action Select -Channel 127 -Serial $mock)
if($rows.Count -ne 1 -or $rows[0].ActiveChannel -ne 127 -or ($mock.Sent -join '') -ne "@I2S=127`n@I2S?`n"){
    throw 'Select must wait for fresh even when a stale response has pending=0'
}
Assert-TestAudioSession $mock;$mockChecks++

$mock=New-TestAudioSerial @((New-TestAudioLine -Tag I2S1 -Desired 7 -Active 7))
$rows=@(Invoke-AudioUartAction -Action Off -Serial $mock)
if($rows.Count -ne 1 -or $rows[0].ActiveEnabled -or $rows[0].ActiveChannel -ne 7 -or $mock.Sent.Count -ne 1){throw 'OFF state must preserve its channel'}
Assert-TestAudioSession $mock;$mockChecks++

$mock=New-TestAudioSerial @((New-TestAudioLine -Tag I2S1 -Flags 6),(New-TestAudioLine -Flags 6))
$rows=@(Invoke-AudioUartAction -Action Query -Serial $mock)
if($rows.Count -ne 2 -or !$rows[0].Pending -or $rows[0].Fresh -or $null -ne $rows[0].ActiveChannel -or $rows[1].Fresh){
    throw 'Query must expose pending/stale facts without pretending configuration applied'
}
Assert-TestAudioSession $mock;$mockChecks++

foreach($case in @(
    @{Name='wrong desired gain';Action='Gain';Line=(New-TestAudioLine -DesiredEven 0x400000 -ActiveEven 0x400000);Match='Desired parity'},
    @{Name='wrong actual gain';Action='Gain';Line=(New-TestAudioLine -ActiveEven 0x400000);Match='Actual parity'},
    @{Name='wrong desired channel';Action='Select';Line=(New-TestAudioLine -Tag I2S1);Match='Desired I2S'},
    @{Name='wrong actual channel';Action='Select';Line=(New-TestAudioLine -Tag I2S1 -Desired 255);Match='Actual I2S'},
    @{Name='queue overflow';Action='Gain';Line=(New-TestAudioLine -Flags 0x10005);Match='queue overflow'},
    @{Name='FPGA rejection';Action='Gain';Line=(New-TestAudioLine -Flags 0x205);Match='FPGA rejected'})){
    $mock=New-TestAudioSerial @($case.Line);$caught=$null
    try{$null=Invoke-AudioUartAction -Action $case.Action -Channel 127 -EvenGain 000000 -Serial $mock}
    catch{$caught=$_.Exception.Message}
    if(!$caught -or !$caught.Contains($case.Match) -or !$caught.Contains('[TX]') -or !$caught.Contains($case.Line)){
        throw "False success or missing diagnostic records: $($case.Name)"
    }
    Assert-TestAudioSession $mock;$mockChecks++
}
$mock=New-TestAudioSerial @();$caught=$null
try{$null=Invoke-AudioUartAction -Action Gain -EvenGain 000000 -TimeoutSeconds 1 -Serial $mock}
catch{$caught=$_.Exception.Message}
if(!$caught -or !$caught.Contains('No independent GAIN1 response') -or !$caught.Contains('[TX] @GAIN=000000,400000')){
    throw 'Timeout must fail and preserve the exact attempted command'
}
Assert-TestAudioSession $mock;$mockChecks++
Write-Host "[HOST_AUDIO_SESSION_PASS] cases=$mockChecks real_serial_opened=false"
