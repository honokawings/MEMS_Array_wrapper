param(
    [string]$Port='COM3',
    [ValidateSet('Query','Select','Off','Gain')][string]$Action='Query',
    [ValidateRange(0,127)][int]$Channel=0,
    [ValidatePattern('^[0-7][0-9A-Fa-f]{5}$')][string]$EvenGain='400000',
    [ValidatePattern('^[0-7][0-9A-Fa-f]{5}$')][string]$OddGain='400000',
    [ValidateRange(1,30)][int]$TimeoutSeconds=5,
    [string]$LogPath=''
)
function ConvertFrom-AudioUartLine {
    param([Parameter(Mandatory=$true)][AllowEmptyString()][string]$Line)
    $text=$Line.TrimEnd([char[]]"`r`n")
    if($text -cnotmatch '^(I2S1|GAIN1)(?: [0-9A-F]{8}){14}$'){return $null}
    $parts=$text.Split(' ');$tag=$parts[0]
    $w=@($parts[1..14] | ForEach-Object {[Convert]::ToUInt32($_,16)})
    $fresh=[bool]($w[1] -band 1)
    $pcm=[int]($w[11] -band 0xFFFFFF);if($pcm -ge 0x800000){$pcm-=0x1000000}
    [pscustomobject][ordered]@{
        Tag=$tag;Sequence=$w[0];Fresh=$fresh;Pending=[bool]($w[1] -band 2)
        AudioResetReleased=[bool]($w[1] -band 4);ErrorCode=(($w[1] -shr 8) -band 255);QueueOverflows=($w[1] -shr 16)
        DesiredEnabled=[bool]($w[2] -band 128);DesiredChannel=($w[2] -band 127)
        ActiveEnabled=$(if($fresh){[bool]($w[3] -band 128)}else{$null})
        ActiveChannel=$(if($fresh){$w[3] -band 127}else{$null})
        DesiredEvenGainHex=('{0:X6}' -f $w[4]);DesiredOddGainHex=('{0:X6}' -f $w[5])
        DesiredEvenGain=($w[4]/4194304.0);DesiredOddGain=($w[5]/4194304.0)
        ActiveEvenGainHex=$(if($fresh){'{0:X6}' -f $w[6]}else{$null})
        ActiveOddGainHex=$(if($fresh){'{0:X6}' -f $w[7]}else{$null})
        ActiveEvenGain=$(if($fresh){$w[6]/4194304.0}else{$null})
        ActiveOddGain=$(if($fresh){$w[7]/4194304.0}else{$null})
        ReceivedSamples=$(if($fresh){$w[8]}else{$null});OutputFrames=$(if($fresh){$w[9]}else{$null})
        Underruns=$(if($fresh){$w[10]}else{$null});LastPcm=$(if($fresh){$pcm}else{$null})
        VerifiedFrames=$(if($fresh){$w[12]}else{$null});SerialErrors=$(if($fresh){$w[13]}else{$null})
        RawWords=$w;RawLine=$text
    }
}
function Assert-AudioUartCommand {
    param([Parameter(Mandatory=$true)][string]$Command)
    if($Command -cnotmatch '^@(I2S(?:\?|=(?:OFF|[0-9]{1,3}))|GAIN(?:\?|=[0-7][0-9A-Fa-f]{5},[0-7][0-9A-Fa-f]{5}))$'){
        throw 'Invalid audio command; use @I2S?, @I2S=0..127, @I2S=OFF, @GAIN?, or @GAIN=EEEEEE,OOOOOO.'
    }
    if($Command -cmatch '^@I2S=([0-9]+)$' -and [int]$Matches[1] -gt 127){throw 'I2S channel must be 0..127.'}
}
function Add-AudioUartTrace {
    param([Parameter(Mandatory=$true)]$Session,[Parameter(Mandatory=$true)][AllowEmptyString()][string]$Text)
    $Session.Trace.Enqueue($Text)
    while($Session.Trace.Count -gt 24){$null=$Session.Trace.Dequeue()}
    if($null -ne $Session.Writer){$Session.Writer.WriteLine($Text);$Session.Writer.Flush()}
}
function Get-AudioUartFailureText {
    param($Session,[string]$Message)
    $log=$(if($Session.LogPath){"`nRaw log: $($Session.LogPath)"}else{''})
    $Message+$log+"`nRecent serial records:`n"+($Session.Trace.ToArray() -join "`n")
}
function Close-AudioUartSession {
    param($Session)
    try{if($Session.Serial.IsOpen){$Session.Serial.Close()}}
    finally{
        try{$Session.Serial.Dispose()}
        finally{if($null -ne $Session.Writer){$Session.Writer.Dispose()}}
    }
}
function Open-AudioUartSession {
    # Serial is an offline test seam; production callers leave it unspecified.
    param([string]$Port='COM3',[string]$LogPath='',[object]$Serial=$null)
    $writer=$null
    if($LogPath){
        $LogPath=[IO.Path]::GetFullPath($LogPath)
        if(Test-Path -LiteralPath $LogPath){throw "Refusing to overwrite UART log: $LogPath"}
        $parent=[IO.Path]::GetDirectoryName($LogPath)
        if(!(Test-Path -LiteralPath $parent)){New-Item -ItemType Directory -Path $parent -Force | Out-Null}
        $writer=[IO.StreamWriter]::new($LogPath,$false,[Text.UTF8Encoding]::new($false))
    }
    if($null -eq $Serial){
        $Serial=[IO.Ports.SerialPort]::new($Port,115200,[IO.Ports.Parity]::None,8,[IO.Ports.StopBits]::One)
        $Serial.Handshake=[IO.Ports.Handshake]::None;$Serial.DtrEnable=$false;$Serial.RtsEnable=$false
        $Serial.ReadTimeout=200;$Serial.WriteTimeout=1000;$Serial.NewLine="`n"
    }
    $session=[pscustomobject]@{Serial=$Serial;Writer=$writer;LogPath=$LogPath;Trace=[Collections.Generic.Queue[string]]::new()}
    try{
        Add-AudioUartTrace $session "[OPEN] $Port 115200 8N1"
        $Serial.Open();$Serial.DiscardInBuffer()
        return $session
    }catch{
        $message=Get-AudioUartFailureText $session $_.Exception.Message
        Close-AudioUartSession $session
        throw $message
    }
}
function Send-AudioUartSessionCommand {
    param([Parameter(Mandatory=$true)]$Session,[Parameter(Mandatory=$true)][string]$Command,[double]$TimeoutSeconds=5)
    Assert-AudioUartCommand $Command
    $wanted=$(if($Command.StartsWith('@GAIN')){'GAIN1'}else{'I2S1'})
    $watch=[Diagnostics.Stopwatch]::StartNew()
    Add-AudioUartTrace $Session ('[TX] '+$Command)
    $Session.Serial.Write($Command+"`n")
    while($watch.Elapsed.TotalSeconds -lt $TimeoutSeconds){
        try{$line=$Session.Serial.ReadLine()}catch [TimeoutException]{continue}
        Add-AudioUartTrace $Session $line
        $row=ConvertFrom-AudioUartLine $line
        if($null -eq $row -or $row.Tag -ne $wanted){continue}
        if($row.ErrorCode -ne 0){throw "FPGA rejected $Command (error $($row.ErrorCode)): $($row.RawLine)"}
        if($row.QueueOverflows -ne 0){throw "FPGA audio queue overflow for ${Command}: $($row.RawLine)"}
        return $row
    }
    throw "No independent $wanted response to $Command within $TimeoutSeconds seconds."
}
function Invoke-AudioUartCommand {
    # Keep the one-command library API. The standalone action below owns one
    # session for its entire set/query handshake, without repeated purges.
    param([string]$Port='COM3',[Parameter(Mandatory=$true)][string]$Command,[int]$TimeoutSeconds=5,[string]$LogPath='')
    Assert-AudioUartCommand $Command
    $session=$null
    try{
        $session=Open-AudioUartSession -Port $Port -LogPath $LogPath
        Send-AudioUartSessionCommand -Session $session -Command $Command -TimeoutSeconds $TimeoutSeconds
    }catch{
        if($null -ne $session){throw (Get-AudioUartFailureText $session $_.Exception.Message)}
        throw
    }finally{if($null -ne $session){Close-AudioUartSession $session}}
}
function Invoke-AudioUartAction {
    param([string]$Port='COM3',[ValidateSet('Query','Select','Off','Gain')][string]$Action='Query',
        [ValidateRange(0,127)][int]$Channel=0,
        [ValidatePattern('^[0-7][0-9A-Fa-f]{5}$')][string]$EvenGain='400000',
        [ValidatePattern('^[0-7][0-9A-Fa-f]{5}$')][string]$OddGain='400000',
        [ValidateRange(1,30)][int]$TimeoutSeconds=5,[string]$LogPath='',[object]$Serial=$null)
    $command=switch($Action){'Select'{"@I2S=$Channel"};'Off'{'@I2S=OFF'};'Gain'{"@GAIN=$EvenGain,$OddGain"};default{'@I2S?'}}
    $session=$null
    try{
        $session=Open-AudioUartSession -Port $Port -LogPath $LogPath -Serial $Serial
        $watch=[Diagnostics.Stopwatch]::StartNew()
        $row=Send-AudioUartSessionCommand -Session $session -Command $command -TimeoutSeconds $TimeoutSeconds
        if($Action -eq 'Query'){
            # Query reports pending/stale facts. It makes no application claim.
            $row
            Send-AudioUartSessionCommand -Session $session -Command '@GAIN?' -TimeoutSeconds $TimeoutSeconds
            return
        }
        $query=$(if($Action -eq 'Gain'){'@GAIN?'}else{'@I2S?'})
        $offChannel=$row.DesiredChannel
        while($true){
            if($Action -eq 'Gain'){
                if($row.DesiredEvenGainHex -ine $EvenGain -or $row.DesiredOddGainHex -ine $OddGain){
                    throw "Desired parity gains differ from requested $EvenGain,$OddGain`: $($row.RawLine)"
                }
            }elseif($Action -eq 'Select'){
                if(!$row.DesiredEnabled -or $row.DesiredChannel -ne $Channel){throw "Desired I2S state differs from requested channel ${Channel}: $($row.RawLine)"}
            }elseif($row.DesiredEnabled -or $row.DesiredChannel -ne $offChannel){throw "Desired I2S state differs from requested OFF: $($row.RawLine)"}
            if($row.Fresh -and !$row.Pending){
                if(!$row.AudioResetReleased){throw "Audio reset remains active: $($row.RawLine)"}
                if($Action -eq 'Gain'){
                    if($row.ActiveEvenGainHex -ine $EvenGain -or $row.ActiveOddGainHex -ine $OddGain){
                        throw "Actual parity gains differ from requested $EvenGain,$OddGain`: $($row.RawLine)"
                    }
                }elseif($row.ActiveEnabled -ne $row.DesiredEnabled -or $row.ActiveChannel -ne $row.DesiredChannel){
                    throw "Actual I2S state differs from requested $Action`: $($row.RawLine)"
                }
                return $row
            }
            if($watch.Elapsed.TotalSeconds -ge $TimeoutSeconds){throw "FPGA accepted request but audio state remains pending or stale: $($row.RawLine)"}
            Start-Sleep -Milliseconds 25
            $remaining=$TimeoutSeconds-$watch.Elapsed.TotalSeconds
            if($remaining -le 0){throw "FPGA accepted request but audio state remains pending or stale: $($row.RawLine)"}
            $row=Send-AudioUartSessionCommand -Session $session -Command $query -TimeoutSeconds $remaining
        }
    }catch{
        if($null -ne $session){throw (Get-AudioUartFailureText $session $_.Exception.Message)}
        throw
    }finally{if($null -ne $session){Close-AudioUartSession $session}}
}
if($MyInvocation.InvocationName -ne '.'){
    $ErrorActionPreference='Stop'
    Invoke-AudioUartAction -Port $Port -Action $Action -Channel $Channel -EvenGain $EvenGain -OddGain $OddGain -TimeoutSeconds $TimeoutSeconds -LogPath $LogPath |
        ForEach-Object {$_ | ConvertTo-Json -Depth 4}
}
