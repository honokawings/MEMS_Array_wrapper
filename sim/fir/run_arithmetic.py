"""Verify actual FIR lane multiplier and rounding against independent arithmetic."""
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
SIM=Path(__file__).resolve().parent
LOG=ROOT/'log/fir'

def run(command,name):
    with (LOG/name).open('w',encoding='utf-8') as output:
        completed=subprocess.run([str(x) for x in command],cwd=SIM,stdout=output,stderr=subprocess.STDOUT,timeout=120)
    text=(LOG/name).read_text(errors='replace')
    if completed.returncode or any(s in text for s in ('[TB_ERROR]','** Error','** Fatal')):
        raise RuntimeError(text)
    return text

def main():
    LOG.mkdir(parents=True,exist_ok=True)
    if not (SIM/'work').exists():run(['vlib','work'],'vlib.log')
    run(['vlog','-sv','-lint','+incdir+../../rtl',ROOT/'rtl/fir_decimator.sv',ROOT/'tb/tb_fir_arithmetic.sv'],'arithmetic_compile.log')
    text=run(['vsim','-batch','-onfinish','exit','work.tb_fir_arithmetic','-do',
              'onerror {quit -f -code 1}; onbreak {quit -f -code 1}; run -all; quit -f -code 0'],'arithmetic_sim.log')
    if '[TB_INFO] Simulation Finished!' not in text:raise RuntimeError(text)
    for line in text.splitlines():
        if '[TB_' in line:print(line)

if __name__=='__main__':main()
