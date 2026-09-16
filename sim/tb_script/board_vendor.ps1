param(
    [string]$PangoInstall = 'D:/Application/ElectronicIDE/Pango/PDS_2022.2-SP6.4',
    [string]$ModelsimBin = 'D:/Application/ElectronicIDE/Modelsim/2020_4/win64'
)
$ErrorActionPreference = 'Stop'
$memsRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$runDir = Join-Path $memsRoot 'log/board_vendor'
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
$localIni = Join-Path $runDir 'modelsim.ini'
$workLibrary = (Join-Path $runDir 'work').Replace('\','/')
Set-Content -LiteralPath $localIni -Value "[Library]`nwork = $workLibrary" -Encoding ascii
if (!(Test-Path -LiteralPath $workLibrary)) {
    & (Join-Path $ModelsimBin 'vlib.exe') $workLibrary
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create local ModelSim library' }
}
$vendorLibrary = Join-Path $PangoInstall 'arch/vendor/pango/verilog/simulation'
$sources = @('GTP_GRS','GTP_INBUF','GTP_INBUFDS','GTP_OUTBUF','GTP_CLKBUFG','GTP_CLKBUFR','GTP_IOCLKDIV_E2','GTP_IODELAY_E2','GTP_GPLL','GTP_ODDR_E1','GTP_IDDR_E1') |
    ForEach-Object { Join-Path $vendorLibrary ($_ + '.v') }
$sources += @('rtl/board/pango_board_clocks.v','rtl/board/pango_rgmii_io.v','tb/board/tb_pango_board_io.sv') |
    ForEach-Object { Join-Path $memsRoot $_ }
& (Join-Path $ModelsimBin 'vlog.exe') -modelsimini $localIni -sv -work $workLibrary @sources 2>&1 |
    Tee-Object -FilePath (Join-Path $runDir 'compile.log')
if ($LASTEXITCODE -ne 0) { throw 'Board vendor RTL compilation failed' }
$transcriptPath = Join-Path $runDir 'transcript.log'
# Keep vendor analog-model real variables visible; ModelSim 2020.4 otherwise
# collapses a GPLL feedback calculation incorrectly when two GPLLs are cascaded.
& (Join-Path $ModelsimBin 'vsim.exe') -modelsimini $localIni -batch -voptargs=+acc -t 1fs -onfinish exit -wlf (Join-Path $runDir 'board_io.wlf') work.tb_pango_board_io -do (Join-Path $PSScriptRoot 'board_vendor.do') -l $transcriptPath *> (Join-Path $runDir 'run.log')
if ($LASTEXITCODE -ne 0) { throw "Board vendor simulation failed with exit $LASTEXITCODE" }
$runText = Get-Content -LiteralPath $transcriptPath -Raw
if ($runText -notmatch '\[TB_INFO\] Simulation Finished!' -or $runText -match '\[TB_ERROR\]|\*\* (Error|Fatal):') {
    throw 'Board vendor simulation has no passing completion marker or contains an error.'
}
