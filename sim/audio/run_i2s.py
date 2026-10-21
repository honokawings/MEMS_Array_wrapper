"""Independent PCM5102 I2S serializer/receiver and all-channel routing regression."""
from pathlib import Path
import hashlib, json, subprocess, time
ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / 'log/i2s'
SIM = ROOT / 'sim'

def run(command, name):
    start = time.monotonic()
    with (LOG/name).open('w', encoding='utf-8') as out:
        result = subprocess.run([str(x) for x in command], cwd=SIM,
            stdout=out, stderr=subprocess.STDOUT, timeout=300)
    text = (LOG/name).read_text(encoding='utf-8', errors='replace')
    if result.returncode or any(x in text for x in ('[TB_ERROR]', '** Error', '** Fatal')):
        raise RuntimeError(text[-12000:])
    return text, round(time.monotonic()-start, 3)

def main():
    LOG.mkdir(parents=True, exist_ok=True)
    work = SIM/'work_i2s'
    sources = [ROOT/'rtl/audio/pcm_i2s_tx.sv', ROOT/'tb/audio/tb_pcm_i2s_tx.sv', Path(__file__).resolve()]
    before = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    if not work.exists(): run(['vlib', work], 'vlib.log')
    _, compile_s = run(['vlog', '-sv', '-lint', '-work', work, *sources[:2]], 'vlog.log')
    text, sim_s = run(['vsim', '-batch', '-onfinish', 'exit', '-wlf', LOG/'i2s.wlf',
        'work_i2s.tb_pcm_i2s_tx', '-do', 'onerror {quit -f -code 1}; onbreak {quit -f -code 1}; run -all; quit -f -code 0'], 'vsim.log')
    if '[TB_INFO] Simulation Finished!' not in text: raise RuntimeError('Simulation incomplete')
    after = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    if before != after: raise RuntimeError('I2S sources changed during verification')
    for line in text.splitlines():
        if '[TB_' in line: print(line, flush=True)
    (LOG/'result.json').write_text(json.dumps({'status': 'PASS', 'compile_seconds': compile_s,
        'simulation_seconds': sim_s, 'sources_sha256': after,
        'coverage': ['independent rising-BCK decode', '24-bit signed/32-bit slots/one-bit I2S delay',
        'clock ratios and edge stability', 'all 128 channels', 'whole-frame select/mute',
        'stale-cache rejection', 'zero on underrun', 'reset recovery', 'independent serial BIST fault injection']}, indent=2)+'\n', encoding='utf-8')

if __name__ == '__main__': main()
