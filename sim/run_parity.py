"""Run frame-atomic Q2.30 parity compensation unit verification."""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT=Path(__file__).resolve().parents[1]
SIM=ROOT/'sim/parity'
LOG=ROOT/'log/parity'


def run(command,name):
    with (LOG/name).open('w',encoding='utf-8') as output:
        result=subprocess.run([str(x) for x in command],cwd=SIM,stdout=output,stderr=subprocess.STDOUT,timeout=120)
    text=(LOG/name).read_text(errors='replace')
    if result.returncode or any(s in text for s in ('[TB_ERROR]','** Error','** Fatal')):
        raise RuntimeError(text)
    return text


def main():
    SIM.mkdir(parents=True,exist_ok=True);LOG.mkdir(parents=True,exist_ok=True)
    sources=[ROOT/'rtl/pcm_parity_compensation.sv',ROOT/'tb/tb_parity_compensation.sv',ROOT/'tb/tb_parity_dc_estimator.sv',Path(__file__).resolve()]
    if not (SIM/'work').exists():run(['vlib','work'],'vlib.log')
    run(['vlog','-sv','-lint',*sources[:3]],'compile.log')
    text=run(['vsim','-batch','-onfinish','exit','work.tb_parity_compensation','-do',
              'onerror {quit -f -code 1}; onbreak {quit -f -code 1}; run -all; quit -f -code 0'],'simulation.log')
    if '[TB_INFO] Simulation Finished!' not in text:raise RuntimeError(text)
    dc_text=run(['vsim','-batch','-onfinish','exit','work.tb_parity_dc_estimator','-do',
              'onerror {quit -f -code 1}; onbreak {quit -f -code 1}; run -all; quit -f -code 0'],'dc_simulation.log')
    if '[TB_INFO] Simulation Finished!' not in dc_text:raise RuntimeError(dc_text)
    result={'status':'PASS','sources_sha256':{str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
    (LOG/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    for line in (text+'\n'+dc_text).splitlines():
        if '[TB_' in line:print(line)


if __name__=='__main__':main()
