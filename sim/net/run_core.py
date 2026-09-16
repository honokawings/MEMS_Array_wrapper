"""Full PDM pins -> calibrated PCM -> CDC -> UDP -> GMII golden comparison."""
from pathlib import Path
import subprocess,json,hashlib,time
ROOT=Path(__file__).resolve().parents[2]
LOG=ROOT/'log/net_core'
SIM=ROOT/'sim'
def run(args,name):
    start=time.monotonic()
    with (LOG/name).open('w',encoding='utf-8') as out:
        result=subprocess.run([str(x) for x in args],cwd=SIM,stdout=out,stderr=subprocess.STDOUT,timeout=600)
    text=(LOG/name).read_text(errors='replace')
    if result.returncode or any(x in text for x in ('[TB_ERROR]','** Error','** Fatal')):
        raise RuntimeError(text[-12000:])
    return text,round(time.monotonic()-start,3)
def main():
    LOG.mkdir(parents=True,exist_ok=True)
    if not (SIM/'work_core').exists():run(['vlib','work_core'],'vlib.log')
    sources=sorted((ROOT/'rtl').glob('*.sv'))+sorted((ROOT/'rtl/net').glob('*.sv'))+[ROOT/'tb/net/tb_mems_ethernet_core.sv']
    _,compile_s=run(['vlog','-sv','-lint','-work','work_core','+incdir+../rtl',*sources],'vlog.log')
    text,sim_s=run(['vsim','-batch','-onfinish','exit','-wlf',LOG/'core.wlf','work_core.tb_mems_ethernet_core','-do',
        'onerror {quit -f -code 1}; onbreak {quit -f -code 1}; run -all; quit -f -code 0'],'vsim.log')
    if '[TB_INFO] Simulation Finished!' not in text:raise RuntimeError('Simulation incomplete')
    for line in text.splitlines():
        if '[TB_' in line:print(line,flush=True)
    (LOG/'result.json').write_text(json.dumps({'status':'PASS','compile_seconds':compile_s,'simulation_seconds':sim_s,
        'sources_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}},indent=2))
if __name__=='__main__':main()
