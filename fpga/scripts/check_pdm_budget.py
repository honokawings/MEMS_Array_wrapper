"""Conservative PDM round-trip budget from routed PDS reports and both SDF corners.

The common PLL/global-buffer path cancels.  For clock skew, retain the entire
launch FF clock branch and conservatively assume zero capture-branch latency.
This intentionally avoids claiming a typical SDF value is an OCV minimum.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
from datetime import datetime


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def microphone_launches(netlist):
    """Trace all eight clock pads back to their actual physical launch FFs."""
    pins_of = lambda text: {pin: net.strip() for pin, net in
                           re.findall(r'\.(\w+)\s+\(([^)]*)\)', text)}
    ff_by_q = {}
    for match in re.finditer(r'^    (V_FF\w+) /\* (.*?) \*/.*?\n        \\(\S+)\s+\(\n(.*?)\);', netlist, re.M | re.S):
        _, logical, physical, pin_text = match.groups()
        pins = pins_of(pin_text)
        if pins.get('Q'):
            if pins['Q'] in ff_by_q:
                raise ValueError('Multiple FF drivers on a physical net')
            # Physical replicas are acceptable only if all state inputs and
            # primitive parameters match; a matching instance name is not proof.
            params = re.findall(r'\.(\w+)\s*\(([^)]*)\)', match[0].split('\\'+physical)[0])
            signature = (_, tuple(sorted((k,v) for k,v in pins.items() if k!='Q')),
                         tuple(sorted((k,v.strip()) for k,v in params)))
            ff_by_q[pins['Q']] = (logical, physical, signature)
    aliases = {}
    for match in re.finditer(r'^    V_BUF\s+\\(\S+)\s+\(\n(.*?)\);', netlist, re.M | re.S):
        pins = pins_of(match.group(2))
        if pins.get('Z') and pins.get('I'):
            aliases[pins['Z']] = pins['I']
    pads = []
    for match in re.finditer(r'^    V_OBUF\w* /\* (.*?) \*/.*?\n        \\(\S+)\s+\(\n(.*?)\);', netlist, re.M | re.S):
        _, physical, pin_text = match.groups()
        pins = pins_of(pin_text)
        if not re.fullmatch(r'mic_clk\[[0-7]\]', pins.get('O', '')):
            continue
        if pins.get('T', "1'b0") != "1'b0":
            raise ValueError('Microphone clock output is not permanently enabled')
        net = pins.get('I')
        visited = set()
        while net in aliases:
            if net in visited:
                raise ValueError('Cycle in microphone clock output connectivity')
            visited.add(net)
            net = aliases[net]
        if net not in ff_by_q:
            raise ValueError(f'Cannot trace {pins["O"]} to a launch FF')
        logical, launch, signature = ff_by_q[net]
        if not re.search(r'capture/mic_clk(?:[_/\[]|$)', logical):
            raise ValueError(f'Unexpected microphone clock source: {logical}')
        pads.append(dict(port=pins['O'], output_buffer=physical,
                         launch_logical=logical, launch_physical=launch,
                         source_signature=signature))
    if len(pads) != 8 or {p['port'] for p in pads} != {f'mic_clk[{i}]' for i in range(8)}:
        raise ValueError('Cannot prove the launch FF for all eight microphone clock pads')
    if len({p['source_signature'] for p in pads}) != 1:
        raise ValueError('Microphone clock replicas do not share identical state inputs and parameters')
    for pad in pads:
        del pad['source_signature']
    return pads


def clock_branches(netlist_path, sdf_path):
    netlist = netlist_path.read_text(encoding='utf8', errors='strict')
    sdf = sdf_path.read_text(encoding='utf8', errors='strict')
    pad_launches = microphone_launches(netlist)
    launch_physicals = {pad['launch_physical'] for pad in pad_launches}
    if '(TIMESCALE    1 ps)' not in sdf:
        raise ValueError('Unexpected SDF timescale')
    ports = {}
    for block in re.split(r'\n\s*\( CELL\s*\n', sdf)[1:]:
        instance = re.search(r'\( INSTANCE (\S+) \)', block)
        delay = re.search(r'\( PORT CK \(([^)]+)\) \(([^)]+)\) \)', block)
        if instance and delay:
            values = [float(x) for part in delay.groups() for x in part.split(':') if x]
            if not values or min(values) < 0:
                raise ValueError('Invalid clock branch delay')
            ports[instance.group(1).replace('\\/', '/')] = max(values) / 1000.0
    records = []
    pattern = r'^    (V_FF\w+) /\* (.*?) \*/.*?\n        \\(\S+)\s+\(\n(.*?)\);'
    for match in re.finditer(pattern, netlist, re.M | re.S):
        _, logical, physical, pins = match.groups()
        kind = ('launch' if physical in launch_physicals else
                'capture' if re.search(r'capture/data_meta\[\d+\]', logical) else None)
        if not kind:
            continue
        clock = re.search(r'\.CK \(([^)]+)\)', pins)
        if not clock or physical not in ports:
            raise ValueError(f'Missing clock mapping/delay for {logical}')
        records.append(dict(kind=kind, logical=logical, physical=physical,
                            clock_net=clock.group(1).strip(),
                            branch_max_ns=ports[physical]))
    launch = [r for r in records if r['kind'] == 'launch']
    capture = [r for r in records if r['kind'] == 'capture']
    if {r['physical'] for r in launch} != launch_physicals or len(capture) != 64:
        raise ValueError(f'Expected microphone clock launch FF and 64 capture FFs; found {len(launch)}/{len(capture)}')
    indices = {int(re.search(r'data_meta\[(\d+)\]', r['logical']).group(1)) for r in capture}
    if indices != set(range(64)):
        raise ValueError('PDM capture FF coverage is incomplete or duplicated')
    clocks = {r['clock_net'] for r in records}
    if len(clocks) != 1:
        raise ValueError('Launch and capture FFs do not share one clock net')
    clock_net = next(iter(clocks))
    # Confirm that this net is driven by a physical global clock buffer.
    buffer_pattern = r'^    V_USCM /\* (.*?) \*/.*?\n        \\(\S+)\s+\(\n(.*?)\);'
    buffers = [m for m in re.finditer(buffer_pattern, netlist, re.M | re.S)
               if re.search(r'\.CLKOUT \(' + re.escape(clock_net) + r'\s*\)', m.group(3))]
    if len(buffers) != 1:
        raise ValueError('Cannot prove one common global clock buffer')
    return dict(buffer_logical=buffers[0].group(1), buffer_physical=buffers[0].group(2),
                clock_pad_launches=pad_launches,
                launch_clock_branch_bound_ns=max(r['branch_max_ns'] for r in launch),
                capture_clock_branch_lower_bound_ns=0.0, registers=records)


def input_budget(report, corner, netlist):
    # KEY1 shares the zero-reference input group with the 64 PDM pins. Its
    # presence is proved from the actual netlist, not a permissive count range.
    # min slack across this superset cannot exceed min slack of PDM alone;
    # 5 - group WNS remains a conservative upper bound on every PDM input path,
    # even though KEY1 itself has a separate 7.5 ns path limit.
    key_present = bool(re.search(r'\binput\s+selftest_key_n\s*;', netlist))
    expected_endpoints = 64 + int(key_present)
    section = re.search(r'Setup Summary\(' + corner.title() + r' Corner\):(.*?)(?=Hold Summary)', report, re.S)
    row = re.search(r'^\s*async_pad_ref\s+audio122\s+([\d.+-]+)\s+([\d.+-]+)\s+(\d+)\s+(\d+)\s*$',
                    section.group(1) if section else '', re.M)
    if not row or int(row.group(3)) != 0 or int(row.group(4)) != expected_endpoints:
        raise ValueError(f'Missing successful {corner} input setup summary for 64 PDM inputs'+(' and KEY1' if key_present else ''))
    bound = 5.0 - float(row.group(1))
    if not 0 <= bound <= 5.0:
        raise ValueError('Unexpected PDM input path budget')
    return bound, expected_endpoints


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('timing-report', 'slow-sdf', 'slow-netlist', 'fast-sdf', 'fast-netlist', 'output'):
        parser.add_argument('--' + arg, type=Path, required=True)
    args = parser.parse_args()
    result = dict(schema='mems-pdm-routed-budget-v1', status='FAIL',
                  generated_at=datetime.now().astimezone().isoformat(),
                  checker_sha256=sha(Path(__file__)))
    try:
        paths = {k: v for k, v in vars(args).items() if k != 'output'}
        result['evidence'] = {k: dict(path=str(v.resolve()), sha256=sha(v)) for k, v in paths.items()}
        report = args.timing_report.read_text(encoding='utf8')
        if 'Design Summary : All Constraints Met.' not in report:
            raise ValueError('The complete routed report must meet all constraints, including the 4 ns microphone outputs')
        result['corners'] = {}
        for corner in ('slow', 'fast'):
            netlist = getattr(args, corner+'_netlist').read_text(encoding='utf8')
            input_setup_ns, endpoints = input_budget(report, corner, netlist)
            data = clock_branches(getattr(args, corner+'_netlist'), getattr(args, corner+'_sdf'))
            data['input_pad_through_setup_ns'] = input_setup_ns
            data['input_summary_endpoints'] = endpoints
            result['corners'][corner] = data
        audio_blocks = [b for b in report.split('Startpoint  :')[1:]
                        if 'Path Group  : audio122' in b and 'Path Type   : max' in b]
        uncertainty = [abs(float(x)) for b in audio_blocks for x in
                       re.findall(r'clock uncertainty\s+([\d.+-]+)', b)]
        if not uncertainty or max(uncertainty) < .300 - .001:
            raise ValueError('Missing expected audio-domain setup uncertainty in detailed report')
        uncertainty_ns = max(uncertainty)
        # SAMPLE_TICK=19 consumes the two-cycle synchronizer output: the
        # selected pin sample entered data_meta 17 clocks after launch.
        # check_release.check_pdm_contract verifies the corresponding RTL.
        interval_ns = 17 * 1e9 / 122_880_000
        for data in result['corners'].values():
            # One ps covers rounding of printed route/summary values.
            total = 120.0 + 4.0 + data['input_pad_through_setup_ns'] + data['launch_clock_branch_bound_ns'] + uncertainty_ns + .001
            data.update(total_bound_ns=total, remaining_ns=interval_ns-total)
            if total >= interval_ns:
                raise ValueError('The conservative routed PDM round-trip bound exceeds the valid capture interval')
        result.update(status='PASS', capture_interval_ns=interval_ns, external_delay_ns=120.0,
                      clock_pad_bound_ns=4.0, uncertainty_ns=uncertainty_ns, report_rounding_guard_ns=.001)
    except (OSError, ValueError) as error:
        result['error'] = str(error)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n', encoding='utf8')
    print(json.dumps({k: result[k] for k in ('status', 'error') if k in result}, ensure_ascii=False))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
