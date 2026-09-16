"""Standalone ModelSim bit-level RTL8211F regression; does not share work libs."""
from pathlib import Path
import json
import hashlib
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
LOG = ROOT / "log" / "net_phy"


def run(args, name):
    begin = time.monotonic()
    with (LOG / name).open("w", encoding="utf-8") as output:
        result = subprocess.run(args, cwd=HERE, stdout=output,
                                stderr=subprocess.STDOUT, timeout=180)
    text = (LOG / name).read_text(encoding="utf-8", errors="replace")
    if result.returncode or any(x in text for x in ("[TB_ERROR]", "** Error", "** Fatal")):
        raise RuntimeError(text[-12000:])
    return text, round(time.monotonic() - begin, 3)


def main():
    for binary in ("vlib", "vlog", "vsim"):
        if not shutil.which(binary):
            raise RuntimeError(f"{binary} is not on PATH")
    LOG.mkdir(parents=True, exist_ok=True)
    if not (HERE / "work_phy").is_dir():
        run(["vlib", "work_phy"], "vlib.log")
    _, compile_seconds = run(["vlog", "-sv", "-lint", "-work", "work_phy",
        "../../rtl/net/mdio_clause22.sv", "../../rtl/net/rtl8211f_manager.sv",
        "../../tb/net/tb_rtl8211f_manager.sv"], "vlog.log")
    text, seconds = run(["vsim", "-batch", "-onfinish", "exit",
        "-wlf", str(LOG / "phy.wlf"), "work_phy.tb_rtl8211f_manager", "-do",
        "onerror {quit -f -code 1}; onbreak {quit -f -code 1}; run -all; quit -f -code 0"], "vsim.log")
    if "[TB_INFO] Simulation Finished!" not in text:
        raise RuntimeError("Simulation did not finish successfully")
    for line in text.splitlines():
        if "[TB_" in line:
            print(line)
    sources = ["rtl/net/mdio_clause22.sv", "rtl/net/rtl8211f_manager.sv",
               "tb/net/tb_rtl8211f_manager.sv", "sim/net/run_phy.py"]
    (LOG / "result.json").write_text(json.dumps({"status": "PASS",
        "compile_seconds": compile_seconds, "simulation_seconds": seconds,
        "test": "tb_rtl8211f_manager", "sources_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in sources}}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
