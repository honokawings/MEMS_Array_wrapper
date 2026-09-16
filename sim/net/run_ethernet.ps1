$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$LogRoot = Join-Path $ProjectRoot 'log/net'
$WorkLibrary = Join-Path $PSScriptRoot 'work'
New-Item -ItemType Directory -Force $LogRoot | Out-Null
if (-not (Test-Path -LiteralPath $WorkLibrary)) {
    & vlib $WorkLibrary
    if ($LASTEXITCODE -ne 0) { throw 'vlib failed' }
}
& vlog -sv -work $WorkLibrary (Join-Path $ProjectRoot 'rtl/net/ethernet_arp_rx.sv') (Join-Path $ProjectRoot 'rtl/net/ethernet_udp_engine.sv') (Join-Path $ProjectRoot 'tb/net/tb_ethernet_udp_engine.sv') 2>&1 | Tee-Object -FilePath (Join-Path $LogRoot 'ethernet_compile.log')
if ($LASTEXITCODE -ne 0) { throw 'Ethernet RTL compilation failed' }
Push-Location $PSScriptRoot
try {
    & vsim -batch -lib work tb_ethernet_udp_engine -do (Join-Path $PSScriptRoot 'run_ethernet.do') 2>&1 | Tee-Object -FilePath (Join-Path $LogRoot 'ethernet_sim.log')
} finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw 'Ethernet simulation failed' }
$SimulationText = Get-Content -Raw (Join-Path $LogRoot 'ethernet_sim.log')
if ($SimulationText -notmatch '\[TB_INFO\] Simulation Finished!' -or $SimulationText -match '\[TB_ERROR\]|\*\* Error|\*\* Fatal') { throw 'Ethernet self-check failed' }
