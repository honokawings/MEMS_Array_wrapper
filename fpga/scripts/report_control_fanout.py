"""Report CE/synchronous-reset pin loads in a PDS synthesis Verilog netlist.

This is an implementation diagnostic, not a timing or release check. Counts
are per synthesized module (before mapping/placement), not physical fanout.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re


def report(path):
    text = Path(path).read_text(encoding='utf-8', errors='replace')
    text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
    result = {}
    for match in re.finditer(r'\bmodule\s+(\S+)(.*?)\bendmodule\b', text, re.S):
        name, body = match.groups()
        if not name.startswith(('fir_decimator', 'pcm_calibration', 'pcm_frame_fifo', 'cic_decimator', 'board_uart_report')):
            continue
        pins = {}
        for pin in ('CE', 'R', 'WE'):
            counts = Counter(n.strip() for n in re.findall(r'\.' + pin + r'\s*\(([^()]*)\)', body)
                             if n.strip() and "'" not in n)
            pins[pin] = dict(counts.most_common())
        result[name] = pins
    if not result:
        raise ValueError('No expected synthesized modules found')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('netlist')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = report(args.netlist)
    Path(args.output).write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    for module, pins in result.items():
        print(module)
        for pin, nets in pins.items():
            print(' ', pin, list(nets.items())[:5])


if __name__ == '__main__':
    main()
