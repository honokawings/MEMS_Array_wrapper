"""Actual board PDM/parity/calibration/I2S and independent audio UART integration."""
from pathlib import Path
import hashlib,json,re,subprocess,time
ROOT=Path(__file__).resolve().parents[2]
SIM=ROOT/'sim'
LOG=ROOT/'log/board_audio'

def run(command,name):
    start=time.monotonic()
    with (LOG/name).open('w',encoding='utf-8') as out:
        result=subprocess.run([str(x) for x in command],cwd=SIM,stdout=out,stderr=subprocess.STDOUT,timeout=600)
    text=(LOG/name).read_text(encoding='utf-8',errors='replace')
    if result.returncode or any(x in text for x in ('[TB_ERROR]','** Error','** Fatal')):raise RuntimeError(text[-14000:])
    return text,round(time.monotonic()-start,3)

def main():
    LOG.mkdir(parents=True,exist_ok=True)
    work=SIM/'work_board_audio'
    sources=sorted((ROOT/'rtl').glob('*.sv'))
    sources += [p for p in sorted((ROOT/'rtl/net').glob('*.sv')) if p.name!='rtl8211f_manager.sv']
    for folder in ('audio','diag'):sources += sorted((ROOT/'rtl'/folder).glob('*.sv'))
    sources += [ROOT/'rtl/board/mems_array_pg2l200h.sv',ROOT/'tb/board/tb_board_audio.sv']
    inputs=sources+[ROOT/'rtl/board/calibration_coeff.svh',Path(__file__).resolve()]
    before={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    if not work.exists():run(['vlib',work],'vlib.log')
    _,compile_s=run(['vlog','-sv','-lint','-work',work,'+incdir+../rtl','+incdir+../rtl/board',*sources],'vlog.log')
    text,sim_s=run(['vsim','-batch','-onfinish','exit','-wlf',LOG/'board_audio.wlf','work_board_audio.tb_board_audio',
        '-do','onerror {quit -f -code 1}; onbreak {quit -f -code 1}; run -all; quit -f -code 0'],'vsim.log')
    if '[TB_INFO] Simulation Finished!' not in text:raise RuntimeError('Simulation incomplete')
    dc=re.search(r'\[TB_INFO\] Board DC windows=(\d+) accepted=(\d+) rejected=(\d+) muted_cycles=(\d+) SYS3_training=(\d+) ready=(\d+) rejected=(\d+) BIST=(\d+)',text)
    if dc is None:raise RuntimeError('Startup DC integration coverage is absent')
    dc_counts=dict(zip(('windows','accepted_channels','rejected_channels','muted_cycles',
                      'uart_training','uart_ready','uart_rejected','uart_bist'),map(int,dc.groups())))
    if dc_counts['windows']!=3 or dc_counts['accepted_channels']!=372 or dc_counts['rejected_channels']!=12 or any(value<=0 for value in dc_counts.values()):
        raise RuntimeError('Startup DC integration coverage is incomplete')
    after={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    if before!=after:raise RuntimeError('Board audio sources changed during verification')
    for line in text.splitlines():
        if '[TB_' in line:print(line,flush=True)
    (LOG/'result.json').write_text(json.dumps({'status':'PASS','compile_seconds':compile_s,'simulation_seconds':sim_s,
        'sources_sha256':after,'dc_coverage':dc_counts,
        'scope':'Actual PDM capture, FIR, startup DC, parity, calibration, I2S, UART and ARP RTL; physical PLL/DDR and PHY link stubs',
        'coverage':['no-link/no-ARP nonzero audio','independent parity/calibration arithmetic for all channels',
        'selected PCM -> independent stereo pin decode','UART I2S0/1/127/OFF and fresh independent queries',
        'UART gain apply/query','gain/DC bypass during PDM BIST','network disconnect preserves real audio and frozen DC',
        'three independent raw-input DC means and masks; initial/mode-exit/reset learning',
        'startup mute until first corrected frame; SYS3 training/ready/rejected states']},indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
