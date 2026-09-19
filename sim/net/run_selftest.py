"""Actual board RTL, button, PDM BIST, filters, Ethernet and host oracle."""
from pathlib import Path
import sys,subprocess,json,hashlib,time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'sim'))
from run_all import model_python
LOG=ROOT/'log/selftest'


def execute(args,name,timeout=600):
    start=time.monotonic()
    with (LOG/name).open('w',encoding='utf-8') as f:
        p=subprocess.run([str(a) for a in args],cwd=ROOT/'sim',stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
    text=(LOG/name).read_text(errors='replace')
    if p.returncode or any(x in text for x in ('[TB_ERROR]','** Error','** Fatal')):raise RuntimeError(text[-10000:])
    return text,round(time.monotonic()-start,3)


def main():
    LOG.mkdir(parents=True,exist_ok=True)
    execute([model_python(),ROOT/'lib/model/generate_selftest.py'],'models.log')
    if not (ROOT/'sim/work_selftest').is_dir():execute(['vlib','work_selftest'],'vlib.log')
    sources=sorted((ROOT/'rtl').glob('*.sv'))+[p for p in sorted((ROOT/'rtl/net').glob('*.sv')) if p.name!='rtl8211f_manager.sv']
    sources += [ROOT/'rtl/board/mems_array_pg2l200h.sv',ROOT/'tb/net/tb_board_boot.sv',ROOT/'tb/board/tb_board_selftest.sv',ROOT/'tb/board/tb_selftest_faults.sv']
    execute(['vlog','-sv','-lint','-work','work_selftest','+incdir+../rtl','+incdir+../rtl/board',*sources],'vlog.log')
    text,seconds=execute(['vsim','-batch','-onfinish','exit','-wlf',LOG/'selftest.wlf',
        'work_selftest.tb_board_selftest','-do','onerror {quit -f -code 1}; onbreak {quit -f -code 1}; run -all; quit -f -code 0'],'vsim.log')
    if '[TB_INFO] Simulation Finished!' not in text:raise RuntimeError('Self-test simulation incomplete')
    for line in text.splitlines():
        if '[TB_' in line:print(line,flush=True)
    faults,_=execute(['vsim','-batch','-onfinish','exit','-wlf',LOG/'faults.wlf',
        'work_selftest.tb_selftest_faults','-do','onerror {quit -f -code 1}; onbreak {quit -f -code 1}; run -all; quit -f -code 0'],'faults.log')
    if '[TB_INFO] Simulation Finished!' not in faults:raise RuntimeError('Fault simulation incomplete')
    for line in faults.splitlines():
        if '[TB_' in line:print(line,flush=True)
    host,_=execute([sys.executable,ROOT/'lib/host/verify_selftest.py','--payloads',LOG/'payloads.hex',
        '--min-frames','96','--output',LOG/'host_result.json'],'host.log')
    print('[TB_INFO] Host BIST golden and continuity '+json.loads(host)['status'])
    (LOG/'result.json').write_text(json.dumps({'status':'PASS','simulation_seconds':seconds,
        'sources_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}},indent=2)+'\n')


if __name__=='__main__':main()
