"""Standalone randomized async-FIFO/PCM packetizer integration regression."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
LOG = ROOT / "log" / "net_transport"
SOURCES = ["rtl/net/async_sample_fifo.sv", "rtl/net/pcm_udp_packetizer.sv",
           "tb/net/tb_pcm_transport.sv", "sim/net/run_transport.py"]


def run(args, name):
    begin = time.monotonic()
    with (LOG / name).open("w", encoding="utf-8") as output:
        result = subprocess.run(args, cwd=HERE, stdout=output,
                                stderr=subprocess.STDOUT, timeout=120)
    text = (LOG / name).read_text(encoding="utf-8", errors="replace")
    if result.returncode or any(x in text for x in ("[TB_ERROR]", "** Error", "** Fatal")):
        raise RuntimeError(text[-14000:])
    return text, round(time.monotonic() - begin, 3)


def main():
    for binary in ("vlib", "vlog", "vsim"):
        if not shutil.which(binary):
            raise RuntimeError(f"{binary} is not on PATH")
    LOG.mkdir(parents=True, exist_ok=True)
    if not (HERE / "work_transport").is_dir():
        run(["vlib", "work_transport"], "vlib.log")
    _, compile_seconds = run(["vlog", "-sv", "-lint", "-work", "work_transport",
        *(str(ROOT / path) for path in SOURCES if path.endswith(".sv"))], "vlog.log")
    text, seconds = run(["vsim", "-batch", "-onfinish", "exit",
        "-wlf", str(LOG / "transport.wlf"), "work_transport.tb_pcm_transport", "-do",
        "onerror {quit -f -code 1}; onbreak {quit -f -code 1}; run -all; quit -f -code 0"], "vsim.log")
    if "[TB_INFO] Simulation Finished!" not in text:
        raise RuntimeError("Simulation did not finish successfully")
    for line in text.splitlines():
        if "[TB_" in line:
            print(line)
    (LOG / "result.json").write_text(json.dumps({"status": "PASS",
        "compile_seconds": compile_seconds, "simulation_seconds": seconds,
        "test": "tb_pcm_transport", "sources_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in SOURCES}}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
