function ConvertFrom-ClockDiagLine {
    param([Parameter(Mandatory=$true)][AllowEmptyString()][string]$Line)
    $pattern = '^CLK2 pfd=31\.25 seq=(?<seq>[0-9A-F]{8}) ms=(?<ms>[0-9A-F]{8}) lock=(?<lock>[01]{3}) rst=(?<rst>[01]{3}) freq=(?<freq>[01]{4}) delta=(?<d0>[0-9A-F]{4}),(?<d1>[0-9A-F]{4}),(?<d2>[0-9A-F]{4}),(?<d3>[0-9A-F]{4}) seen=(?<seen>[0-9A-F]) fault=(?<fault>[0-9A-F]) now=(?<now>[0-9A-F]) ctrl=(?<ctrl>[0-9A-F]{2}) reset=(?<reset>[01]) cmd=(?<cmd>[0-9A-F]{2}) cmds=(?<cmds>[0-9A-F]{4}) rxerr=(?<rxerr>[0-9A-F]{4})$'
    if ($Line.TrimEnd([char[]]"`r`n") -cnotmatch $pattern) { return $null }
    $m = $Matches.Clone()
    $counts = @(0..3 | ForEach-Object { [Convert]::ToUInt16($m["d$_"],16) })
    $control = [Convert]::ToByte($m.ctrl,16)
    $healthy = ($m.lock -eq '111' -and $m.rst -eq '111' -and $m.freq -eq '1111' -and $m.now -eq '0' -and $m.reset -eq '0')
    [pscustomobject][ordered]@{
        Sequence=[Convert]::ToUInt32($m.seq,16); UptimeMs=[Convert]::ToUInt32($m.ms,16)
        LockBits=$m.lock; ResetBits=$m.rst; FrequencyBits=$m.freq
        Raw125MHz=$counts[0]*0.1024; Clock96MHz=$counts[1]*0.1024
        AudioMHz=$counts[2]*0.1024; EthernetMHz=$counts[3]*0.1024
        Counts=$counts; SeenMask=[Convert]::ToByte($m.seen,16)
        StickyFaultMask=[Convert]::ToByte($m.fault,16); CurrentFaultMask=[Convert]::ToByte($m.now,16)
        Controller=$control; AudioHeartbeat=[bool]($control -band 1); SelftestMode=[bool]($control -band 2)
        ResetActive=($m.reset -eq '1'); LastCommandHex=$m.cmd
        Commands=[Convert]::ToUInt16($m.cmds,16); ReceiveErrors=[Convert]::ToUInt16($m.rxerr,16)
        Healthy=$healthy
    }
}
