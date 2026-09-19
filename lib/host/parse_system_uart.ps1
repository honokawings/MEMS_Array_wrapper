function ConvertFrom-SystemUartLine {
    param([Parameter(Mandatory=$true)][AllowEmptyString()][string]$Line)
    $lineText=$Line.TrimEnd([char[]]"`r`n")
    if ($lineText -cnotmatch '^SYS3(?: [0-9A-F]{8}){34}$') { return $null }
    $w=@($lineText.Substring(5).Split(' ') | ForEach-Object { [Convert]::ToUInt32($_,16) })
    $cl=$w[2];$a=$w[8];$p=$w[12];$net=$w[21]
    $lock=($cl -band 7);$rst=(($cl -shr 3) -band 7);$freq=(($cl -shr 11) -band 15)
    $now=(($cl -shr 19) -band 15);$reset=[bool]($cl -band 0x08000000)
    [pscustomobject][ordered]@{
        Sequence=$w[0];UptimeMs=$w[1];LockMask=$lock;ResetMask=$rst;FrequencyMask=$freq
        ClockFaultMask=(($cl -shr 15) -band 15);CurrentFaultMask=$now;ResetActive=$reset
        ClocksHealthy=($lock -eq 7 -and $rst -eq 7 -and $freq -eq 15 -and $now -eq 0 -and !$reset)
        MHz=@((($w[3] -band 65535)*0.1024),(($w[3] -shr 16)*0.1024),(($w[4] -band 65535)*0.1024),(($w[4] -shr 16)*0.1024))
        LastCommandHex=('{0:X2}' -f (($w[5] -shr 16) -band 255));Commands=($w[5] -band 65535)
        ReceiveErrors=($w[6] -band 65535);UnknownCommands=($w[6] -shr 16)
        FreshMask=($w[7] -band 7);AudioFresh=[bool]($w[7] -band 1);EthFresh=[bool]($w[7] -band 2);RxFresh=[bool]($w[7] -band 4)
        Started=[bool]($a -band 1);Acquiring=[bool]($a -band 2);Run=[bool]($a -band 4)
        SelftestMode=[bool]($a -band 8);Overflow=[bool]($a -band 16);ProcessingError=[bool]($a -band 32);Clipped=[bool]($a -band 64)
        SelftestPass=[bool]($a -band 128);SelftestFail=[bool]($a -band 256)
        CalibrationDone=[bool]($a -band 1024);Heartbeat=[bool]($a -band 0x00080000)
        DroppedFrames=$w[9];PcmSamples=$w[10];LastPcmFrame=$w[11]
        PhyState=($p -band 15);ConfigStep=(($p -shr 4) -band 31);PhyAddress=(($p -shr 9) -band 31)
        PhyReady=[bool]($p -band 0x4000);LinkUp=[bool]($p -band 0x8000);PhyFault=[bool]($p -band 0x10000);PhyResetReleased=[bool]($p -band 0x20000)
        PhyId=('{0:X8}' -f $w[13]);MdioRead=[bool]($w[14] -band 0x00100000);MdioAck=[bool]($w[14] -band 0x00080000)
        MdioAddress=(($w[14] -shr 14) -band 31);MdioRegister=(($w[14] -shr 9) -band 31)
        MdioStep=(($w[14] -shr 4) -band 31);MdioState=($w[14] -band 15)
        MdioReadData=('{0:X4}' -f ($w[15] -band 65535));MdioWriteData=('{0:X4}' -f ($w[15] -shr 16))
        MdioTransactions=$w[16];MdioReadNoAcks=$w[17];PhyRetries=$w[18]
        FailureState=($w[19] -shr 28);FailureStep=(($w[19] -shr 23) -band 31)
        FailureRead=[bool]($w[19] -band 0x00400000);FailureAck=[bool]($w[19] -band 0x00200000)
        FailureRegister=(($w[19] -shr 16) -band 31);FailureData=('{0:X4}' -f ($w[19] -band 65535))
        PhyStatus=('{0:X4}' -f $w[20]);PeerValid=[bool]($net -band 4);PacketFull=[bool]($net -band 8)
        TxError=[bool]($net -band 16);FramingError=[bool]($net -band 0x1000)
        SelftestTxPass=[bool]($net -band 0x2000);SelftestTxFail=[bool]($net -band 0x4000);EthStreaming=[bool]($net -band 0x8000)
        ArpRequestsSent=$w[22];ArpRepliesSent=$w[23];ArpAccepted=$w[24];UdpSent=$w[25];EthernetFramesSent=$w[26]
        StreamEpoch=$w[27];PeerMac=('{0:X4}{1:X8}' -f $w[29],$w[28])
        RxFrames=$w[30];RxErrorFrames=$w[31];RxBytes=$w[32];RxCycles=$w[33]
        RawWords=$w
    }
}
