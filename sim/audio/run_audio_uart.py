"""Independent UART audio config, frame arbitration and CDC regression."""
from pathlib import Path
import hashlib,json,subprocess,time
ROOT=Path(__file__).resolve().parents[2]
LOG=ROOT/'log/audio_uart'
def main():
    LOG.mkdir(parents=True,exist_ok=True)
    work=ROOT/'sim/work_audio_uart'
    sources=sorted((ROOT/'rtl/diag').glob('*.sv'))+[ROOT/'rtl/net/reset_release.sv',ROOT/'tb/board/tb_audio_uart.sv']
    inputs=sources+[Path(__file__).resolve(),ROOT/'lib/host/audio_uart.ps1',ROOT/'lib/host/test_audio_uart.ps1',ROOT/'lib/host/parse_system_uart.ps1']
    before={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    def execute(command,name):
        start=time.monotonic()
        with (LOG/name).open('w',encoding='utf-8') as f:
            result=subprocess.run([str(x) for x in command],cwd=ROOT/'sim',stdout=f,stderr=subprocess.STDOUT,timeout=240)
        text=(LOG/name).read_text(encoding='utf-8',errors='replace')
        if result.returncode or any(x in text for x in ('[TB_ERROR]','** Error','** Fatal')):raise RuntimeError(text[-16000:])
        return text,round(time.monotonic()-start,3)
    if not work.exists():execute(['vlib',work],'vlib.log')
    execute(['vlog','-sv','-lint','-work',work,*sources],'vlog.log')
    text,seconds=execute(['vsim','-batch','-onfinish','exit','-wlf',LOG/'audio_uart.wlf',work.name+'.tb_audio_uart',
        '-do','onerror {quit -f -code 1}; onbreak {quit -f -code 1}; run -all; quit -f -code 0'],'vsim.log')
    if '[TB_INFO] Simulation Finished!' not in text:raise RuntimeError('Audio UART simulation incomplete')
    for line in text.splitlines():
        if '[TB_' in line:print(line,flush=True)
    execute(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',ROOT/'lib/host/test_audio_uart.ps1'],'host_parser.log')
    after={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    if before!=after:raise RuntimeError('Sources changed during audio UART regression')
    (LOG/'result.json').write_text(json.dumps({'status':'PASS','seconds':seconds,'sources_sha256':after},indent=2)+'\n')
if __name__=='__main__':main()
