"""UART board integration with real MDIO/PHY RTL, ARP and UDP observability."""
from pathlib import Path
import hashlib,json,subprocess,time

ROOT=Path(__file__).resolve().parents[2]
LOG=ROOT/'log/system_uart'

def execute(command,name,timeout=900):
    begin=time.monotonic()
    with (LOG/name).open('w',encoding='utf-8') as f:
        result=subprocess.run([str(x) for x in command],cwd=ROOT/'sim',stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
    text=(LOG/name).read_text(encoding='utf-8',errors='replace')
    if result.returncode or any(x in text for x in ('[TB_ERROR]','** Error','** Fatal')):
        raise RuntimeError(text[-12000:])
    return text,round(time.monotonic()-begin,3)

def main():
    LOG.mkdir(parents=True,exist_ok=True)
    work=ROOT/'sim/work_system_uart'
    if not work.exists():execute(['vlib',work],'vlib.log')
    sources=sorted((ROOT/'rtl').glob('*.sv'))+sorted((ROOT/'rtl/net').glob('*.sv'))+sorted((ROOT/'rtl/diag').glob('*.sv'))
    sources += [ROOT/'rtl/board/mems_array_pg2l200h.sv',ROOT/'tb/board/tb_system_uart.sv',ROOT/'tb/board/tb_uart_protocol.sv']
    inputs=sources+[Path(__file__).resolve(),ROOT/'rtl/board/calibration_coeff.svh']
    before={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    execute(['vlog','-sv','-lint','-work',work,'+incdir+../rtl','+incdir+../rtl/board',*sources],'vlog.log')
    steps={}
    for top in ['tb_uart_protocol','tb_system_uart']:
        text,seconds=execute(['vsim','-batch','-onfinish','exit','-wlf',LOG/(top+'.wlf'),work.name+'.'+top,
            '-do','onerror {quit -f -code 1}; onbreak {quit -f -code 1}; run -all; quit -f -code 0'],top+'.log')
        if '[TB_INFO] Simulation Finished!' not in text:raise RuntimeError('Simulation incomplete: '+top)
        steps[top]={'status':'PASS','seconds':seconds}
        for line in text.splitlines():
            if '[TB_' in line:print(line,flush=True)
    after={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    if before!=after:raise RuntimeError('Sources changed during UART regression')
    execute(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',ROOT/'lib/host/test_system_uart.ps1'],'host_parser.log')
    (LOG/'result.json').write_text(json.dumps({'status':'PASS','steps':steps,
        'primitive_scope':'Digital clock/DDR stubs in integration; separately required vendor PLL/DDR regression',
        'sources_sha256':after},indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
