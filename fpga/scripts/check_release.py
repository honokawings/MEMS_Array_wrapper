"""Fail-closed release gate for this board and PDS 2022.2 reports.

Reads original PDS reports; it does not accept a manually asserted timing PASS.
The result certifies consistency of local build evidence, not physical board tests.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
TOP = 'mems_array_pg2l200h'
STAGES = ('compile', 'synthesize', 'dev_map', 'pnr', 'report_timing', 'gen_bit_stream')
STEPS = ('frontend', 'fir_arithmetic', 'phy', 'ethernet', 'transport', 'boot', 'core', 'selftest', 'host', 'host_rtl', 'board', 'system_uart', 'parity', 'i2s', 'audio_uart', 'board_audio', 'vendor_uart', 'fir_ram')
FIR_RAM_RESULT = 'log/fir_ram/result.json'
FIR_RAM_SCOPE = 'fir_history_ram_pipeline_functional'
FIR_RAM_SOURCES = ('rtl/fir_decimator.sv', 'rtl/fir1_coeff.svh', 'rtl/fir2_coeff.svh',
                   'tb/tb_fir_ram_pipeline.sv', 'sim/fir/run_ram_pipeline.py',
                   'lib/coeff/fir1_q30.hex', 'lib/coeff/fir2_q30.hex')
FIR_RAM_FIELDS = ('case', 'channels', 'lanes', 'groups', 'taps', 'depth', 'decimation', 'input_interval',
                  'checks', 'writes', 'reads', 'output_samples', 'wraps', 'concurrent_rw', 'resets',
                  'commit_capture', 'writing_faults', 'busy_faults', 'input_changes')
FIR_RAM_PARAMETERS = ((128,16,8,63,128,4,320), (128,16,8,127,256,2,1280),
                      (1,1,1,63,128,4,32), (1,1,1,127,256,2,72),
                      (128,8,16,63,128,4,320), (128,8,16,127,256,2,1280))
FIR_RAM_COVERAGE = ('FIR1/FIR2, 16-lane/eight-group and 8-lane/sixteen-group production rates, and single group',
                    'actual RAM write data/address and post-edge memory content',
                    'independent accepted-input ordinal read addresses and read data',
                    'two complete ring wraps in each configuration',
                    'concurrent read/write with no same-address collision',
                    'input bus changes after capture and during writing',
                    'last RAM commit coincides with capture of next vector',
                    'reset at first/last pending write, after commit and in first read',
                    'writing and busy scheduling faults, clean restart',
                    'independent full convolution, signed-magnitude rounding and exact output latency')
CLOCKS = {'sys27': 1000/27, 'ref125': 8, 'eth250': 4, 'eth125': 8, 'rx125': 8, 'rx_data_launch': 8, 'async_pad_ref': 8, 'audio96': 1000/96,
          'audio122': 1000/122.88, 'tx_pad_ref': 8, 'pdm3072': 1000/3.072, 'mdc992k': 1008}
CLOCK_PARENTS = {'audio96': 'sys27', 'audio122': 'audio96', 'eth250': 'ref125',
                 'eth125': 'eth250', 'pdm3072': 'audio122', 'mdc992k': 'eth125'}
CORE_CLOCKS = {'sys27', 'audio122', 'eth125', 'rx125'}
UART_CDC_PAIRS = (('ref125', 'sys27'), ('audio96', 'sys27'), ('audio122', 'sys27'),
                  ('eth125', 'sys27'), ('rx125', 'sys27'), ('sys27', 'audio122'),
                  ('sys27', 'eth125'), ('sys27', 'rx125'))
SUMMARY_TYPES = ('Setup', 'Hold', 'Recovery', 'Removal', 'Minimum Pulse Width')
PORTS = ({f'pdm_data[{i}]' for i in range(64)} | {f'mic_clk[{i}]' for i in range(8)} |
         {f'PHY0_{d}[{i}]' for d in ('RXD', 'TXD') for i in range(4)} |
         {'PHY0_RXC', 'PHY0_RXCTRL', 'PHY0_TXC', 'PHY0_TXCTRL', 'PHY0_MDIO',
          'PHY0_MDC', 'RSTN_OUT', 'sys_clk_27', 'sys_clk_125_p', 'sys_clk_125_n', 'reset_n', 'selftest_key_n', 'uart_rx', 'uart_tx'} |
         {f'led[{i}]' for i in range(5)} | {'i2s_sck','i2s_bck','i2s_din','i2s_lrck'})
I2S_L5_PINS=set('M19 R14 R15 P14 N14 P15 P16 N16 N17 R16 R17 P18 N18 K25 K26 M20 L20 L24 L25 M24 M25 L22 L23 M21 M22 N21 N22 P20 P21 N23 N24 P19 N19 P23 P24 R20 R21 R25 P25 N26 M26 T24 T25 R26 P26 T22 R22 T23 R23 R18'.split())


class ReleaseError(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise ReleaseError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    need(isinstance(value, dict), f'{path}: expected JSON object')
    return value


def check_pll_validation(data, root):
    need(data.get('status') == 'PASS' and data.get('negative_control_original_rejected') is True,
         'Missing positive and negative vendor PLL validation')
    source = root/'rtl/board/pango_board_clocks.v'
    need(Path(data['rtl_source']).resolve() == source.resolve() and data['rtl_sha256'] == sha(source),
         'PLL validation uses another RTL source')
    need(data['validator_sha256'] == sha(root/'fpga/scripts/check_pll_parameters.py'), 'PLL validator changed')
    need(data['vendor_sha256'] == sha(Path(data['vendor_source'])), 'Installed vendor PLL rules changed')
    rows = data.get('validated_instances', [])
    expected = {'u_pll_eth': (125.0, 4, 16, 4, 31.25, 1000.0, 250.0),
                'u_pll_96': (27.0, 1, 16, 9, 27.0, 864.0, 96.0),
                'u_pll_audio': (96.0, 5, 16, 5, 19.2, 614.4, 122.88)}
    need(len(rows) == 3 and {r['name'] for r in rows} == set(expected), 'Incomplete PLL parameter coverage')
    for row in rows:
        values = [row[k] for k in ('input_mhz', 'idiv', 'mdiv', 'odiv', 'pfd_mhz', 'vco_mhz', 'output_mhz')]
        need(all(abs(x-y) < 1e-6 for x,y in zip(values, expected[row['name']])), 'Unexpected validated PLL configuration')
        need(row['bandwidth'] == 'OPTIMIZED' and row['fdiv'] == 2, 'Unexpected PLL bandwidth/feedback')
    return data


def timestamp(value):
    result = datetime.fromisoformat(value)
    need(result.tzinfo is not None, 'Timestamps must include timezone')
    return result.timestamp()


def check_fir_ram(root, regression, evidence):
    """Bind actual RAM/convolution results and reparse original simulation rows."""
    path = root/FIR_RAM_RESULT
    need(path.is_file(), 'Missing mandatory FIR RAM regression result')
    result_hash = sha(path)
    need(regression['steps']['fir_ram'].get('evidence') == {'path': FIR_RAM_RESULT, 'sha256': result_hash},
         'Full regression FIR RAM result path/hash mismatch')
    result = read_json(path)
    need(result.get('status') == 'PASS' and result.get('scope') == FIR_RAM_SCOPE,
         'FIR RAM result lacks actual RAM functional PASS scope')
    need(all(result.get(key) is False for key in ('sdf_annotated', 'placement_routing_tested', 'real_serial_opened')),
         'FIR RAM result claims unsupported physical or serial verification')

    def bind(label, file):
        need(file.is_file() and file.stat().st_size > 0, f'Missing or empty FIR RAM input: {file}')
        row = {'path': str(file.resolve()), 'bytes': file.stat().st_size, 'sha256': sha(file)}
        evidence['fir_ram_'+label] = row
        return row['sha256']

    evidence['fir_ram_regression'] = {'path': str(path.resolve()), 'bytes': path.stat().st_size, 'sha256': result_hash}
    sources = {rel: bind('source:'+rel, root/rel) for rel in FIR_RAM_SOURCES}
    need(result.get('sources_sha256') == sources, 'FIR RAM source/coefficient input path/hash mismatch')
    coefficients = {rel: sources[rel] for rel in FIR_RAM_SOURCES if rel.endswith('.hex')}
    need(result.get('reference_coefficients_sha256') == coefficients, 'FIR RAM independent reference coefficient hash mismatch')
    logs = {rel: bind('raw_log:'+rel, root/rel) for rel in ('log/fir_ram/vlog.log', 'log/fir_ram/vsim.log')}
    need(result.get('raw_logs_sha256') == logs, 'FIR RAM original compile/simulation log path/hash mismatch')
    artifacts = {'log/fir_ram/modelsim.ini': bind('artifact:modelsim.ini', root/'log/fir_ram/modelsim.ini')}
    need(result.get('artifacts_sha256') == artifacts, 'FIR RAM simulation library configuration path/hash mismatch')
    tools = result.get('tools_sha256')
    need(isinstance(tools, dict) and len(tools) == 3 and
         {Path(p).stem.lower() for p in tools} == {'vlib', 'vlog', 'vsim'}, 'Incomplete FIR RAM ModelSim tool evidence')
    for name, expected in tools.items():
        tool = Path(name)
        need(tool.is_absolute() and bind('tool:'+name, tool) == expected, 'FIR RAM ModelSim tool path/hash mismatch')
    need(timestamp(result['completed_at']) >= timestamp(result['started_at']), 'Invalid FIR RAM verification interval')

    texts = {name: (root/rel).read_text(encoding='utf-8', errors='replace') for name, rel in
             (('compile', 'log/fir_ram/vlog.log'), ('simulation', 'log/fir_ram/vsim.log'))}
    for name, text in texts.items():
        need(not any(token in text for token in ('[TB_ERROR]', '** Error', '** Fatal', '** Warning')) and
             re.search(r'Errors: 0, Warnings: 0', text), f'FIR RAM {name} log contains errors/warnings or no zero-error summary')
    simulation = texts['simulation']
    need('[TB_INFO] Simulation Finished!' in simulation and
         '[TB_INFO] FIR_RAM all six configurations passed' in simulation, 'FIR RAM original simulation lacks complete RAM coverage finish')
    pattern = r'FIR_RAM '+r' '.join(re.escape(field)+r'=(\d+)' for field in FIR_RAM_FIELDS)
    case_lines = re.findall(r'\[TB_DATA\] (FIR_RAM case=[^\r\n]*)', simulation)
    cases = []
    for line in case_lines:
        match = re.fullmatch(pattern, line)
        need(match is not None, 'Unknown FIR RAM original case row')
        cases.append(dict(zip(FIR_RAM_FIELDS, map(int, match.groups()))))
    cases.sort(key=lambda row: row['case'])
    need(len(cases) == 6 and [row['case'] for row in cases] == list(range(6)), 'FIR RAM original log lacks six unique actual RAM cases')
    need(result.get('cases') == cases and all(type(value) is int for row in result['cases'] for value in row.values()),
         'FIR RAM result case counters differ from original simulation')
    for row, parameters in zip(cases, FIR_RAM_PARAMETERS):
        need(tuple(row[key] for key in FIR_RAM_FIELDS[1:8]) == parameters, 'FIR RAM actual configuration mismatch')
        need(row['writes'] > 0 and row['reads'] > 0 and row['output_samples'] > 0 and row['wraps'] >= 2 and
             row['concurrent_rw'] >= 1 and row['resets'] == 4 and row['commit_capture'] >= 1 and
             row['writing_faults'] == 1 and row['busy_faults'] == 1 and row['input_changes'] >= 256 and
             row['checks'] >= 2*row['writes']+row['reads']+row['output_samples'], 'FIR RAM actual RAM/convolution coverage incomplete')
    need(type(result.get('checks')) is int and result['checks'] == sum(row['checks'] for row in cases),
         'FIR RAM total checks differ from actual cases')
    need(isinstance(result.get('coverage'), list) and all(isinstance(item, str) for item in result['coverage']) and
         len(result['coverage']) == len(FIR_RAM_COVERAGE) and
         set(result['coverage']) == set(FIR_RAM_COVERAGE), 'FIR RAM independent RAM/reference coverage contract incomplete')
    return {'status': 'PASS', 'scope': FIR_RAM_SCOPE, 'result_sha256': result_hash, 'cases': cases,
            'checks': result['checks'], 'sources_sha256': sources, 'reference_coefficients_sha256': coefficients,
            'raw_logs_sha256': logs, 'tools_sha256': tools, 'placement_routing_tested': False, 'sdf_annotated': False}


def scanned_sources(root):
    files = []
    for folder in ('rtl', 'tb', 'lib/model', 'lib/cmodel', 'lib/host', 'sim'):
        files.extend(p for p in (root/folder).rglob('*')
                     if p.suffix in {'.v', '.sv', '.svh', '.py', '.cpp', '.do', '.ps1', '.bat', '.f', '.bin'}
                     and (p.suffix != '.bin' or folder == 'lib/host')
                     and not any(v.startswith('work') or v == '__pycache__' for v in p.relative_to(root).parts))
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(set(files))}


def current_build_sources(root):
    files = [p for p in (root/'rtl').rglob('*') if p.suffix in {'.v', '.sv', '.svh'}]
    files += [root/'fpga/constraints/board_pins.fdc', root/'fpga/constraints/timing.fdc', root/'fpga/scripts/build.py',root/'fpga/scripts/check_pll_parameters.py']
    floorplan = root/'fpga/constraints/frontend_floorplan.pcf'
    if floorplan.is_file():
        files.append(floorplan)
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(files)}


def commands(text):
    """These project FDC files deliberately use one literal command per line."""
    return [' '.join(line.split()) for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]


def pins_from_fdc(text):
    pins = {}
    for port, attr, value in re.findall(r'define_attribute\s+\{p:([^}]+)\}\s+\{PAP_IO_(DIRECTION|LOC|VCCIO|STANDARD)\}\s+\{([^}]+)\}', text):
        need(attr not in pins.setdefault(port, {}), f'Duplicate pin attribute: {port} {attr}')
        pins[port][attr] = value
    need(set(pins) == PORTS, 'Board FDC must define exactly the 103 expected ports')
    need(all(set(x) == {'DIRECTION', 'LOC', 'VCCIO', 'STANDARD'} for x in pins.values()), 'Incomplete pin attributes')
    need(len({x['LOC'] for x in pins.values()}) == len(pins), 'Duplicate package pin')
    for name in ('i2s_sck','i2s_bck','i2s_din','i2s_lrck'):
        attrs=pins[name]
        need(attrs['LOC'] in I2S_L5_PINS and attrs['DIRECTION']=='OUTPUT' and
             attrs['VCCIO']=='3.3' and attrs['STANDARD']=='LVCMOS33','I2S output must use reviewed L5/3.3 V electrical settings: '+name)
    return pins


def check_map(text, pin_fdc, timing_fdc):
    need('Generated by Fabric Compiler' in text, 'Unknown DMR format')
    match = re.search(r'Timing Constraint:\s*\n-+\s*\n(.*?)\nLogical Constraint:', text, re.S)
    need(match is not None, 'DMR has no timing constraints')
    need(Counter(commands(match[1])) == Counter(commands(timing_fdc)), 'DMR timing constraints differ from current FDC')
    pins = pins_from_fdc(pin_fdc)
    output_attributes = {}
    for port, attr, value in re.findall(r'define_attribute\s+\{p:([^}]+)\}\s+\{PAP_IO_(DRIVE|SLEW)\}\s+\{([^}]+)\}', pin_fdc):
        need(attr not in output_attributes.setdefault(port, {}), 'Duplicate output electrical attribute')
        output_attributes[port][attr] = value
    for name in ('i2s_sck','i2s_bck','i2s_din','i2s_lrck'):
        need(output_attributes.get(name)=={'DRIVE':'8','SLEW':'FAST'},'I2S output requires 8 mA FAST drive: '+name)
    actual = {}
    for line in text.splitlines():
        fields = [x.strip() for x in line.split('|')]
        if len(fields) >= 6 and fields[2].lower() in {'input', 'output', 'inout'}:
            name, direction, loc, voltage, standard = fields[1:6]
            need(name not in actual, f'Duplicate mapped port {name}')
            actual[name] = {'DIRECTION': direction.upper(), 'LOC': loc, 'VCCIO': voltage, 'STANDARD': standard}
            for attr, index in [('DRIVE',6),('SLEW',8)]:
                if attr in output_attributes.get(name, {}):
                    need(len(fields)>index and fields[index]==output_attributes[name][attr],
                         f'Mapped output {attr} differs from board FDC: {name}')
    need(actual == pins, 'Mapped I/O names, directions, package pins, voltages or standards do not match board FDC')
    return {'ports': len(actual), 'pins': actual, 'output_electrical': output_attributes}


def wildcard_queries(text):
    found = Counter()
    # Braced bus patterns contain literal closing brackets, so a bare [^]] is wrong.
    pattern = r'\[get_(ports|pins|cells|clocks)\b((?:[^\]{}]|\{[^}]*\})*)\]'
    for kind, body in re.findall(pattern, '\n'.join(commands(text))):
        for token in body.replace('{', ' ').replace('}', ' ').split():
            if '*' in token or '?' in token:
                found[(kind, token)] += 1
    return found


def check_constraints(text, timing_fdc, pins, root):
    need(re.search(r'Current device\s*:\s*PG2L200H-6FBB676\s', text), 'CCR device mismatch')
    need(re.search(r'Top Module\s*:\s*'+TOP+r'\s', text), 'CCR top module mismatch')
    for name in ('board_pins.fdc', 'timing.fdc'):
        need((root/'fpga/constraints'/name).as_posix().lower() in text.replace('\\', '/').lower(), f'CCR missing current {name}')
    match = re.search(r'Found (\d+) error\(s\), (\d+) critical warning\(s\), (\d+) warning\(s\), out of (\d+) constraint\(s\)', text)
    need(match is not None, 'Unknown CCR summary format')
    errors, critical, warnings, total = map(int, match.groups())
    need(errors == 0 and warnings == 0 and total > 0, 'CCR has errors, warnings or no constraints')
    diagnostics = re.findall(r'^[ \t]*([ECW]):[ \t]+(.*)$', text, re.M)
    need(len(diagnostics) == critical, 'CCR diagnostic count mismatch')
    shared = []
    for severity, message in diagnostics:
        m = re.fullmatch(r'ConstraintEditor-2002: .*\| Port (\S+) has been placed at location (\S+), whose type is share pin\.', message)
        need(severity == 'C' and m is not None, f'Unreviewed constraint diagnostic: {message}')
        need(m[1] in pins and pins[m[1]]['LOC'] == m[2], 'CCR shared-pin warning does not match board FDC')
        shared.append({'port': m[1], 'pin': m[2], 'code': 'ConstraintEditor-2002'})
    empty = re.search(r'Unconstrained ports:\s*\n\*+\s*\n(.*?)\nConstraints with matching wildcard expressions:', text, re.S)
    need(empty is not None and not empty[1].strip(), 'CCR contains unconstrained ports or unknown section format')
    actual, matches = Counter(), []
    regex = r"^\s*I: The pattern '([^']+)' in command 'get_(ports|pins|cells|clocks) [^']*' match (\d+) objects below:\s*\n((?:[ \t]*I: (?:port|pin|cell|instance|clock) [^\n]+\n)*)"
    for m in re.finditer(regex, text, re.M):
        pattern, kind, count, body = m.groups()
        objects = re.findall(r'I: (?:port|pin|cell|instance|clock) (.+)', body)
        n = int(count)
        need(n > 0 and len(objects) == n and len(set(objects)) == n, f'CCR unmatched/truncated wildcard {pattern}')
        if kind == 'ports':
            expected = [p for p in PORTS if re.fullmatch(re.escape(pattern).replace(r'\*', '.*').replace(r'\?', '.'), p)]
            need(set(objects) == set(expected), f'CCR wildcard port set mismatch: {pattern}')
        actual[(kind, pattern)] += 1
        matches.append({'kind': kind, 'pattern': pattern, 'objects': objects})
    need(actual == wildcard_queries(timing_fdc), 'CCR wildcard query coverage differs from current timing FDC')
    need(actual, 'CCR contains no wildcard target evidence')
    return {'constraint_count': total, 'shared_pin_notices': shared, 'wildcard_matches': matches}


def table_body(text, heading):
    m = re.search(r'^\s*'+re.escape(heading)+r'\s*\n(.*?)^\s*={5,}\s*$', text, re.M | re.S)
    need(m is not None, f'Missing table: {heading}')
    pieces = re.split(r'^\s*-{5,}\s*$', m[1], flags=re.M)
    need(len(pieces) == 2, f'Unknown table format: {heading}')
    return pieces[1]


def parse_clock_summary(text):
    body = table_body(text, 'Clock Summary:')
    result = {}
    pattern = r'(\S+)\s+([\d.]+)\s+\{([\d.]+)\s+([\d.]+)\}\s+(Declared|Generated|Virtual)(?:\s+\(([^)]*)\))?\s+(\d+)\s+(\d+)(?:\s+\{([^}]*)\})?'
    for line in body.splitlines():
        if not line.strip():
            continue
        m = re.fullmatch(pattern, line.strip())
        need(m is not None, f'Unknown clock row: {line.strip()}')
        name, period, rise, fall, kind, parent, loads, nonclock, source = m.groups()
        need(name not in result, f'Duplicate clock: {name}')
        result[name] = {'period_ns': float(period), 'rise_ns': float(rise), 'fall_ns': float(fall),
                        'clock_loads': int(loads), 'nonclock_loads': int(nonclock), 'source': source or '', 'type': kind, 'parent': parent or ''}
    need(set(result) == set(CLOCKS), 'Expected exactly twelve declared/generated/virtual clocks; missing or unexpected clocks')
    sources = {'sys27': 'sys_clk_27', 'ref125': 'sys_clk_125_p', 'rx125': 'PHY0_RXC',
               'pdm3072': 'mic_clk[0]', 'mdc992k': 'PHY0_MDC'}
    for name, expected in CLOCKS.items():
        row = result[name]
        need(row['parent'] == CLOCK_PARENTS.get(name, ''), f'Clock parent mismatch: {name}')
        if name in CLOCK_PARENTS:
            need(row['type'] == 'Generated', f'Clock must be generated: {name}')
        need(abs(row['period_ns']-expected) <= 0.001, f'Incorrect clock period: {name}')
        need(abs(row['rise_ns']-(2 if name == 'rx_data_launch' else 0)) <= 0.001, f'Incorrect clock phase: {name}')
        # PDS truncates intermediate PLL waveform edges to ps before scaling
        # the divided PDM waveform. The observed accumulated rounding is 40 ps.
        waveform_tolerance = 0.050 if name == 'pdm3072' else (0.002 if name == 'audio122' else 0.001)
        need(abs(row['fall_ns']-row['rise_ns']-expected/2) <= waveform_tolerance, f'Incorrect clock waveform: {name}')
        if name in CORE_CLOCKS:
            need(row['clock_loads'] > 0, f'Clock has no functional loads: {name}')
        if name in {'rx_data_launch', 'async_pad_ref', 'tx_pad_ref'}:
            need(row['type'] == 'Virtual' and not row['source'] and row['clock_loads'] == 0, 'Virtual reference clock must have no physical clock loads or source')
        elif name in sources:
            need(row['source'] == sources[name], f'Clock source mismatch: {name}')
        elif name == 'eth125':
            need('u_eth_div/' in row['source'] and row['source'].endswith(('/CLKOUT', '/CLKDIVOUT')), 'Ethernet clock must come from divide-by-two primitive')
        else:
            instance = {'audio96': 'u_pll_96', 'audio122': 'u_pll_audio', 'eth250': 'u_pll_eth'}[name]
            need(instance in row['source'] and row['source'].endswith('/CLKOUT0'), f'PLL source mismatch: {name}')
    return result


def parse_summary(text, kind, corner):
    heading = f'{kind} Summary({corner} Corner):'
    body = table_body(text, heading)
    count = 1 if kind == 'Minimum Pulse Width' else 2
    rows, pending = [], []
    for line in body.splitlines():
        pending += line.split()
        if not pending:
            continue
        # PDS wraps long clock names over up to three lines.
        if len(pending) < count + 4:
            continue
        need(len(pending) == count+4, f'Unknown/truncated row in {heading}: {pending}')
        names = pending[:count]
        try:
            worst, total = map(float, pending[count:count+2])
            failing, endpoints = map(int, pending[-2:])
        except ValueError as exc:
            raise ReleaseError(f'Unknown numeric row in {heading}: {pending}') from exc
        need(math.isfinite(worst) and math.isfinite(total), f'Nonfinite slack in {heading}')
        need(worst >= 0 and total == 0 and failing == 0 and endpoints > 0, f'Timing violation or empty path set in {heading}: {pending}')
        rows.append({'clocks': names, 'worst_slack_ns': worst, 'total_slack_ns': total,
                     'failing_endpoints': failing, 'total_endpoints': endpoints})
        pending = []
    need(not pending and rows, f'Empty or incomplete {heading}')
    if kind in ('Setup', 'Hold', 'Minimum Pulse Width'):
        for clock in CORE_CLOCKS:
            expected = [clock] if count == 1 else [clock, clock]
            need(any(row['clocks'] == expected for row in rows), f'{heading} missing {clock} functional paths')
    if kind == 'Setup':
        for pair in (['audio122', 'eth125'], ['eth125', 'audio122'], ['rx125', 'eth125'], ['eth125', 'rx125']):
            need(any(row['clocks'] == pair for row in rows), f'{heading} missing bounded CDC paths {pair}')
        for pair in UART_CDC_PAIRS:
            need(any(tuple(row['clocks']) == pair for row in rows), f'{heading} missing bounded UART CDC paths {pair}')
    if kind in ('Setup', 'Hold'):
        pair = ['rx_data_launch', 'rx125']
        need(any(row['clocks'] == pair and row['total_endpoints'] == 5 for row in rows), f'{heading} missing RGMII data/control paths {pair}')
    if kind == 'Setup':
        # The reviewed TX datapath-only bound is a max check. Min paths are
        # verified separately, for every edge/corner/pad, by check_tx_source.
        pair = ['eth125', 'tx_pad_ref']
        need(any(row['clocks'] == pair and row['total_endpoints'] == 6 for row in rows), f'{heading} missing six RGMII TX pad paths')
    return rows


def timing_metadata(text, routed_database=None):
    """Keep PDS's model label; validate only explicitly supported report options."""
    models = re.findall(r'^\|[ \t]*Timing Models[ \t]*:[ \t]*([^\r\n]+)', text, re.M)
    need(len(models) == 1, 'RTR requires one timing-model label')
    model = models[0].strip()
    need(model in {'Production', 'Pre-silicon'}, f'Unknown RTR timing model: {model}')
    matches = re.findall(r'^\|[ \t]*Tcl Command[ \t]*:[ \t]*([^\r\n]+)', text, re.M)
    need(len(matches) == 1, 'RTR requires one Tcl Command header')
    command = matches[0].strip()
    parsed_command = command
    options = {}
    if routed_database is not None:
        databases = list(re.finditer(r'(?<!\S)-input_db_file\s+(\{[^{}\r\n]+\}|"[^"\r\n]+"|[^\s{}]+)', command))
        need(len(databases) == 1 and Path(databases[0][1].strip('{}"')).resolve() == Path(routed_database).resolve(),
             'RTR header does not select the authenticated routed database')
        match = databases[0]
        options['-input_db_file'] = str(Path(routed_database).resolve())
        parsed_command = command[:match.start()]+' '+command[match.end():]
    tokens = parsed_command.split()
    need(tokens and tokens[0] == 'report_timing', 'RTR must come from report_timing')
    index = 1
    while index < len(tokens):
        option = tokens[index]
        need(option not in options, f'Duplicate report_timing option: {option}')
        if option in {'-report_io_datasheet', '-report_max_skew'} or (option == '-force_to_run' and routed_database is not None):
            options[option] = True
            index += 1
            continue
        need(option in {'-delay_type', '-report_exception', '-max_path', '-nworst'},
             f'Unsupported report_timing option: {option}')
        need(index+1 < len(tokens), f'Missing value for report_timing option: {option}')
        value = tokens[index+1]
        if option == '-delay_type':
            need(value == 'min_max', 'report_timing must retain both min and max analysis')
        elif option == '-report_exception':
            need(value == 'TRUE', 'report_timing must retain requested exception reporting')
        else:
            need(re.fullmatch(r'[1-9][0-9]*', value), f'{option} requires a positive integer')
            value = int(value)
        options[option] = value
        index += 2
    return {'timing_models': model, 'report_command': command, 'report_options': options}


RESET_CONTROL_EXCEPTION = 'set_false_path -to [get_pins {clocks.u_pll_96.u_gpll/RST clocks.u_pll_audio.u_gpll/RST clocks.u_pll_eth.u_gpll/RST clocks.u_eth_div/RST_N}]'
RESET_CONTROL_ENDPOINTS = {
    'clocks/u_pll_96/u_gpll/gpll_inst/RST',
    'clocks/u_pll_audio/u_gpll/gpll_inst/RST',
    'clocks/u_pll_eth/u_gpll/gpll_inst/RST',
    'clocks/u_eth_div/iockdiv_inst/CLR_N',
}
LOCK_STATUS_EXCEPTION = 'set_false_path -from [get_pins {clocks.u_pll_96.u_gpll/LOCK clocks.u_pll_audio.u_gpll/LOCK clocks.u_pll_eth.u_gpll/LOCK}]'
LOCK_STATUS_STARTPOINTS = {f'clocks/u_pll_{name}/u_gpll/gpll_inst/LOCK' for name in ('96', 'audio', 'eth')}


def review_timing_diagnostics(log, fdc='', fdc_path=None):
    """Review named non-data clock-primitive reset controls and LOCK status.

    PG2L200H's timing model has no timing endpoints on these controls. The
    corresponding redundant reset/status exceptions therefore have no path.
    No functional FF clear, data path or arbitrary empty exception is waived.
    """
    diagnostics = re.findall(r'^[ \t]*([ECW]):[ \t]+(.+)$', log, re.M)
    if not diagnostics:
        return []
    error = 'Timing diagnostics require review: '+ '; '.join(d[1] for d in diagnostics[:5])
    need(fdc_path is not None and len(diagnostics) in (5, 9), error)
    found, status, empty = [], [], []
    for severity, diagnostic in diagnostics:
        need(severity == 'C', error)
        endpoint = re.fullmatch(r"STA-3006: Object '([^']+)' is not a valid endpoint\.", diagnostic)
        if endpoint:
            found.append(endpoint[1])
            continue
        startpoint = re.fullmatch(r"STA-3005: Object '([^']+)' is not a valid startpoint\.", diagnostic)
        if startpoint:
            status.append(startpoint[1])
            continue
        missing = re.fullmatch(r'STA-3015: \[(.+)\(line number: (\d+)\)\] No path found for -from -through -to path specification\.', diagnostic)
        need(missing is not None, error)
        lines, number = fdc.splitlines(), int(missing[2])
        need(Path(missing[1]).resolve() == Path(fdc_path).resolve(), error)
        need(1 <= number <= len(lines) and lines[number-1].strip() in (RESET_CONTROL_EXCEPTION, LOCK_STATUS_EXCEPTION), error)
        empty.append(lines[number-1].strip())
    need(len(found) == 4 and set(found) == RESET_CONTROL_ENDPOINTS and empty.count(RESET_CONTROL_EXCEPTION) == 1, error)
    need(commands(fdc).count(RESET_CONTROL_EXCEPTION) == 1, error)
    if status:
        need(len(status) == 3 and set(status) == LOCK_STATUS_STARTPOINTS and empty.count(LOCK_STATUS_EXCEPTION) == 1, error)
        need(commands(fdc).count(LOCK_STATUS_EXCEPTION) == 1, error)
    else:
        need(empty == [RESET_CONTROL_EXCEPTION], error)
    return [diagnostic for _, diagnostic in diagnostics]


def check_timing(text, log, fdc='', fdc_path=None, routed_database=None):
    for field, value in (('Design', TOP), ('Device', 'PG2L200H'), ('Speed Grade', '-6'), ('Package', 'FBB676')):
        need(re.search(r'^\|\s*'+field+r'\s*:\s*'+re.escape(value)+r'\s*$', text, re.M), f'RTR {field} mismatch')
    metadata = timing_metadata(text, routed_database)
    need('Timing analysis mode : multi corner' in text, 'Final timing must analyze both process corners')
    need(not re.search('violated', text, re.I), 'RTR reports violated constraints')
    need(re.search(r'Design Summary\s*:\s*All Constraints Met\.', text, re.I), 'RTR has no recognized all-constraints-met result')
    reviewed = review_timing_diagnostics(log, fdc, fdc_path)
    need(re.search(r'Action report_timing:', log), 'Timing run.log lacks completed report_timing action')
    clocks = parse_clock_summary(text)
    summaries = {f'{kind}/{corner}': parse_summary(text, kind, corner)
                 for corner in ('Slow', 'Fast') for kind in SUMMARY_TYPES}
    return {**metadata, 'clocks': clocks, 'summaries': summaries,
            'reviewed_clock_reset_diagnostics': reviewed}


def run_helper(script, arguments, output):
    """Run a reviewed standalone helper; a pre-existing PASS file is not input."""
    need(not output.exists(), 'Helper output must be newly generated')
    result = subprocess.run([sys.executable, str(script), *map(str, arguments), '--output', str(output)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace',
                            timeout=180, check=False)
    need(output.is_file(), f'{script.name} did not produce evidence: {result.stderr[-2000:]}')
    data = read_json(output)
    need(result.returncode == 0 and data.get('status') == 'PASS',
         f'{script.name} rejected physical evidence: '+str(data.get('error') or data.get('errors') or result.stderr[-2000:]))
    return data


def check_database(path, timing, fdc):
    """Cross-check the raw XML against RTR; review check_timing issues by object."""
    try:
        document = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ReleaseError('Malformed PDS timing XML') from exc
    need(document.tag == 'tables', 'Unknown PDS timing XML root')
    tables = {}
    for table in document.findall('./table'):
        name = table.get('id')
        need(name and name not in tables, 'Missing/duplicate PDS XML table ID')
        tables[name] = table

    def rows(name, recursive=False):
        need(name in tables, 'Missing PDS XML table: '+name)
        return [[(x.text or '').strip() for x in row.findall('./data')] for row in tables[name].findall('.//row' if recursive else './row')]

    xml_clocks = {}
    # PDS nests generated clocks below their parent <row>, including cascades.
    for row in rows('report_timing_clock_summary', recursive=True):
        need(len(row) == 10 and row[0] not in xml_clocks, 'Unknown XML clock row')
        xml_clocks[row[0]] = {'type': row[1].split()[0], 'period_ns': float(row[2]),
                             'rise_ns': float(row[4]), 'fall_ns': float(row[5]),
                             'clock_loads': int(row[6]), 'nonclock_loads': int(row[7]), 'parent': row[8]}
    expected_clocks = {name: {key: row[key] for key in ('type', 'period_ns', 'rise_ns', 'fall_ns', 'clock_loads', 'nonclock_loads', 'parent')}
                       for name, row in timing['clocks'].items()}
    need(xml_clocks == expected_clocks, 'XML and RTR clock tables differ')
    for corner in ('Slow', 'Fast'):
        for kind in SUMMARY_TYPES:
            suffix = 'mpw' if kind == 'Minimum Pulse Width' else kind.lower()
            values = []
            for row in rows(f'report_timing_{corner.lower()}_{suffix}'):
                count = 1 if suffix == 'mpw' else 2
                need(len(row) == count+4, 'Unknown XML timing summary row')
                values.append((tuple(row[:count]), float(row[count]), float(row[count+1]), int(row[count+2]), int(row[count+3])))
            expected = [(tuple(row['clocks']), row['worst_slack_ns'], row['total_slack_ns'], row['failing_endpoints'], row['total_endpoints'])
                        for row in timing['summaries'][f'{kind}/{corner}']]
            need(Counter(values) == Counter(expected), 'XML and RTR timing summaries differ: '+corner+'/'+kind)

    # Zero-reference I/O constraints intentionally have equal min/max values.
    # PDS reports those as issues; allow only equality objects mechanically
    # derived from this FDC, never inverted bounds or unknown checks.
    assignments = {}
    for command in commands(fdc):
        start = re.match(r'set_(input|output)_delay\b', command)
        target = re.search(r'\[get_ports\s+(?:\{([^}]+)\}|([^\]]+))\]', command)
        bound = re.search(r'-(min|max)\s+([-+\d.]+)', command)
        clock = re.search(r'-clock\s+(\S+)', command)
        if not (start and target and bound and clock) or float(bound[2]) != 0:
            continue
        for pattern in (target[1] or target[2]).split():
            for port in PORTS:
                if re.fullmatch(re.escape(pattern).replace(r'\*', '.*').replace(r'\?', '.'), port):
                    key = (start[1], clock[1], '-clock_fall' in command, port)
                    assignments.setdefault(key, set()).add(bound[1])
    equality_ports = {key[-1] for key, bounds in assignments.items() if bounds == {'min', 'max'}}
    expected_checks = {'no_clock', 'virtual_clock', 'unexpandable_clocks', 'no_input_delay', 'no_output_delay',
                       'partial_input_delay', 'partial_output_delay', 'io_min_max_delay_consistency',
                       'input_delay_assigned_to_clock', 'loops', 'latch_loops', 'latchs'}
    need('check_timing_summary' in tables, 'Missing XML check_timing_summary')
    checks, equalities, virtual_issues, clock_output_issues = {}, [], [], []
    for row in tables['check_timing_summary'].findall('./row'):
        data = [(x.text or '').strip() for x in row.findall('./data')]
        need(len(data) == 2 and data[0] not in checks, 'Unknown XML check_timing row')
        name, count = data[0], int(data[1])
        need(count >= 0 and name in expected_checks, 'Unknown XML timing check')
        checks[name] = count
        if name == 'io_min_max_delay_consistency':
            leaves = [(x.text or '').strip() for x in row.findall('./table_container/table/row/row/data')]
            need(len(leaves) == count, 'XML I/O consistency issue count mismatch')
            for leaf in leaves:
                match = re.fullmatch(r'(\S+): Min (rise|fall) delay is equal to max \2 delay\.', leaf)
                need(match and match[1] in equality_ports, 'Unreviewed XML I/O bound issue: '+leaf)
            equalities = leaves
        elif name == 'virtual_clock' and count:
            leaves = [(x.text or '').strip() for x in row.findall('./table_container/table/row/data')]
            need(len(leaves) == count and len(set(leaves)) == count, 'XML virtual-clock issue count mismatch')
            coverage = {'rx_data_launch': [(('rx_data_launch', 'rx125'), 5)],
                        'tx_pad_ref': [(('eth125', 'tx_pad_ref'), 6)],
                        'async_pad_ref': [(('async_pad_ref', 'audio122'), 65 if 'get_ports selftest_key_n' in fdc else 64), (('async_pad_ref', 'eth125'), 1)]}
            fdc_commands = commands(fdc)
            for leaf in leaves:
                match = re.fullmatch(r'Virtual clock (\S+) is never referenced in any input or output delay assignment\.', leaf)
                need(match and match[1] in coverage, 'Unreviewed XML virtual clock: '+leaf)
                clock = match[1]
                declarations = [c for c in fdc_commands if c.startswith('create_clock ') and re.search(r'-name\s+'+re.escape(clock)+r'(?:\s|$)', c)]
                need(len(declarations) == 1 and '[' not in declarations[0], 'Virtual reference lacks an explicit virtual clock declaration')
                references = [c for c in fdc_commands if re.match(r'set_(input|output)_delay ', c) and re.search(r'-clock\s+'+re.escape(clock)+r'(?:\s|$)', c)]
                need(any(' -min ' in c for c in references) and any(' -max ' in c for c in references),
                     'Virtual clock actually lacks min/max I/O references: '+clock)
                need(timing['clocks'][clock]['type'] == 'Virtual', 'Reviewed virtual clock is not virtual')
                for corner in ('Slow', 'Fast'):
                    for pair, endpoints in coverage[clock]:
                        covered = [r for r in timing['summaries']['Setup/'+corner] if tuple(r['clocks']) == pair]
                        need(len(covered) == 1 and covered[0]['total_endpoints'] == endpoints and
                             covered[0]['failing_endpoints'] == 0 and covered[0]['worst_slack_ns'] >= 0,
                             'Virtual reference lacks successful actual I/O timing coverage: '+clock)
            virtual_issues = leaves
        elif name == 'no_output_delay' and count:
            leaves = [(x.text or '').strip() for x in row.findall('./table_container/table/row/row/data')]
            need(len(leaves) == count and len(set(leaves)) == count, 'XML clock-output issue count mismatch')
            reviewed_ports = {'mic_clk[0]': ('pdm3072', 'set_max_delay 4.000 -datapath_only -to [get_ports {mic_clk[*]}]'),
                              'PHY0_MDC': ('mdc992k', 'set_max_delay 7.500 -datapath_only -to [get_ports PHY0_MDC]')}
            for port in leaves:
                need(port in reviewed_ports, 'Unreviewed XML output without delay: '+port)
                clock, bound = reviewed_ports[port]
                need(timing['clocks'][clock]['type'] == 'Generated' and timing['clocks'][clock]['source'] == port,
                     'Output-delay exclusion is not an actual generated-clock port')
                need(commands(fdc).count(bound) == 1, 'Generated-clock output lacks the reviewed physical delay bound')
            clock_output_issues = leaves
        elif name == 'unexpandable_clocks' and count:
            # 122.88/27 = 1024/225 exceeds PDS's 1000-cycle phase search.
            # This pair carries handshake/Gray/status CDC only. Verify physical
            # bounds and actual passing coverage in both directions/corners.
            leaves = [(x.text or '').strip() for x in row.findall('.//data')]
            expected = 'Can not find common multiples between the source clock audio122 and destination clock sys27  within 1000 cycles.'
            need(count == 1 and expected in leaves, 'Unreviewed unexpandable clock pair')
            for a,b in (('audio122','sys27'),('sys27','audio122')):
                need(commands(fdc).count(f'set_max_delay 7.500 -datapath_only -from [get_clocks {a}] -to [get_clocks {b}]') == 1,
                     'Missing UART CDC physical bound')
                need(commands(fdc).count(f'set_false_path -hold -from [get_clocks {a}] -to [get_clocks {b}]') == 1,
                     'Missing UART CDC hold exception')
                for corner in ('Slow','Fast'):
                    paths = [p for p in timing['summaries']['Setup/'+corner] if tuple(p['clocks']) == (a,b)]
                    need(len(paths) == 1 and paths[0]['total_endpoints'] > 0 and paths[0]['failing_endpoints'] == 0 and paths[0]['worst_slack_ns'] >= 0,
                         'UART CDC physical timing has no passing coverage')
        else:
            need(count == 0, f'Unreviewed XML check_timing issue: {name}={count}')
    need(set(checks) == expected_checks, 'Incomplete XML check_timing coverage')
    return {'check_timing': checks, 'reviewed_zero_reference_equalities': equalities,
            'reviewed_referenced_virtual_clocks': virtual_issues,
            'reviewed_generated_clock_outputs': clock_output_issues,
            'rtr_clock_and_summary_tables_identical': True}


def check_physical(args, root, build, artifact, scripts, timing, fdc_text):
    """Use original same-build files and bind each fresh helper result to them."""
    db = artifact('timing_database', args.report_db or Path(args.timing_report).parent/'rtr.db', '.db')
    database = check_database(db, timing, fdc_text)
    pdm_contract = check_pdm_contract(root, fdc_text, timing)
    paths = {'timing_report': Path(args.timing_report).resolve()}
    for corner in ('slow', 'fast'):
        for kind, suffix, filename in (('sdf', '.sdf', 'sta.sdf'), ('netlist', '.v', 'sim.v')):
            key = corner+'_'+kind
            paths[key] = artifact(key, getattr(args, key) or build/'clock_audit'/f'{corner}_{filename}', suffix)
    # A unique directory prevents another audit, stale result or previous FAIL
    # from supplying this invocation's answer. No report/source is overwritten.
    directory = build/'clock_audit'
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='release_audit_', dir=directory) as temporary:
        output = Path(temporary)
        pdm_script = root/'fpga/scripts/check_pdm_budget.py'
        pdm_args = [item for key, value in paths.items() for item in ('--'+key.replace('_', '-'), value)]
        pdm = run_helper(pdm_script, pdm_args, output/'pdm.json')
        need(pdm.get('schema') == 'mems-pdm-routed-budget-v1', 'Unknown PDM helper schema')
        need(pdm.get('checker_sha256') == scripts[str(pdm_script)]['sha256'], 'PDM helper hash mismatch')
        need(set(pdm.get('evidence', {})) == set(paths), 'PDM helper evidence set mismatch')
        for key, path in paths.items():
            item = pdm['evidence'][key]
            need(Path(item['path']).resolve() == path and item['sha256'] == sha(path), 'PDM helper used different raw evidence')
        need(set(pdm.get('corners', {})) == {'slow', 'fast'}, 'PDM helper lacks both corners')
        for corner in pdm['corners'].values():
            need(math.isfinite(corner['remaining_ns']) and corner['remaining_ns'] > 0, 'PDM budget has no positive margin')
        tx_script = root/'fpga/scripts/check_tx_source.py'
        fdc = root/'fpga/constraints/timing.fdc'
        tx_paths = {key: value for key, value in paths.items() if key != 'timing_report'}
        tx_args = ['--report-db', db, '--constraints', fdc]
        tx_args += [item for key, value in tx_paths.items() for item in ('--'+key.replace('_', '-'), value)]
        tx = run_helper(tx_script, tx_args, output/'tx.json')
        expected = {'report_db': str(db), 'constraints': str(fdc),
                    'report_db_sha256': sha(db), 'constraints_sha256': sha(fdc),
                    'helper_sha256': scripts[str(tx_script)]['sha256']}
        expected.update({key: str(value) for key, value in tx_paths.items()})
        expected.update({key+'_sha256': sha(value) for key, value in tx_paths.items()})
        need(tx.get('schema_version') == 1, 'Unknown TX helper schema')
        need(tx.get('inputs') == expected, 'TX helper evidence/hash set mismatch')
        need(tx.get('errors') == [] and len(tx.get('cases', [])) == 4, 'TX helper lacks four successful edge/corner cases')
        duty = tx.get('duty', {})
        need(duty.get('status') == 'PASS' and duty.get('nominal_model_status') == 'PASS',
             'TX forwarded-clock nominal duty cycle fails the device model')
        need(tx.get('scope') == 'engineering_board_bringup' and tx.get('unconditional_board_qualification') is False,
             'TX helper must preserve the approved engineering-only scope')
        need(duty.get('qualification_status') == 'UNCONFIRMED', 'TXC board qualification must remain explicitly unconfirmed')
        sensitivity = duty.get('conservative_jitter_sensitivity', {})
        need(sensitivity.get('status') in {'PASS', 'FAIL'} and duty.get('sensitivity_status') == sensitivity['status'],
             'Missing or contradictory original TX jitter sensitivity result')
        need(sensitivity.get('edge_jitter_budget_ns') == .360 and len(sensitivity.get('cases', [])) == 2,
             'Original conservative jitter assumptions/corners are missing')
        jitter_bound = duty.get('required_edgepair_jitter_max_ns')
        need(isinstance(jitter_bound, (int, float)) and math.isfinite(jitter_bound) and jitter_bound > 0,
             'TXC lacks a positive board edge-pair jitter acceptance bound')
        i2s_script=root/'fpga/scripts/check_i2s_budget.py'
        i2s_paths={**paths,'constraints':fdc,'rtl':root/'rtl/audio/pcm_i2s_tx.sv'}
        i2s_args=[item for key,value in i2s_paths.items() for item in ('--'+key.replace('_','-'),value)]
        i2s=run_helper(i2s_script,i2s_args,output/'i2s.json')
        need(i2s.get('schema')=='i2s-routed-budget-v1','Unknown I2S helper schema')
        need(i2s.get('checker_sha256')==scripts[str(i2s_script)]['sha256'] and
             i2s.get('dependency_sha256')==scripts[str(tx_script)]['sha256'],'I2S helper/dependency hash mismatch')
        need(i2s.get('scope')=='engineering_board_bringup' and i2s.get('unconditional_board_qualification') is False,
             'I2S helper must preserve engineering-only scope')
        need(set(i2s.get('evidence',{}))==set(i2s_paths),'I2S helper evidence set mismatch')
        for key,path in i2s_paths.items():
            item=i2s['evidence'][key]
            need(Path(item['path']).resolve()==path.resolve() and item['sha256']==sha(path),'I2S helper used different raw evidence')
        need(set(i2s.get('corners',{}))=={'slow','fast'},'I2S helper lacks both corners')
        contract=i2s.get('contract',{})
        need(all(contract.get(k)==v for k,v in {'audio_clock_hz':122880000,'sck_period_cycles':10,
             'bck_period_cycles':40,'lrck_period_cycles':2560,'data_launch_to_bck_rise_cycles':20,
             'pcm5102_minimum_setup_hold_ns':8.0,'enforced_setup_hold_ns':20.0,
             'external_relative_delay_and_edge_budget_ns':20.0,'uncertainty_ns':0.300}.items()),'I2S reviewed external budget changed')
        for corner in i2s['corners'].values():
            need(set(corner.get('outputs',{}))=={'i2s_sck','i2s_bck','i2s_din','i2s_lrck'},'I2S helper lacks all four physical pad paths')
            for port,item in corner['outputs'].items():
                bound=4.0 if port in ('i2s_sck','i2s_bck') else 20.0
                for key in ('ff_to_pad_rise_ns','ff_to_pad_fall_ns'):
                    need(isinstance(item.get(key),(int,float)) and math.isfinite(item[key]) and 0<=item[key]<=bound+.001,'I2S real routed pad limit failed')
            need(set(corner.get('receiver_margins',{}))=={'i2s_din','i2s_lrck'},'I2S helper lacks data/LRCK margins')
            for item in corner['receiver_margins'].values():
                need(all(math.isfinite(item[k]) and item[k]>0 for k in ('setup_remaining_ns','hold_remaining_ns')),'I2S setup/hold margin failed')
            need(set(corner.get('clock_pulse_margins',{}))=={'i2s_sck','i2s_bck'},'I2S helper lacks SCK/BCK pulse budgets')
            need(all(math.isfinite(item['remaining_ns']) and item['remaining_ns']>0 for item in corner['clock_pulse_margins'].values()),'I2S pulse-width margin failed')
        uart_script=root/'fpga/scripts/check_uart_vendor.py'
        uart_paths={key:paths[key] for key in ('slow_netlist','fast_netlist')}
        uart_paths['probe_result']=root/'log/vendor_uart/result.json'
        uart_args=['--root',root]+[item for key,value in uart_paths.items() for item in ('--'+key.replace('_','-'),value)]
        uart=run_helper(uart_script,uart_args,output/'uart_vendor.json')
        need(uart.get('schema')=='uart-vendor-and-routed-channel-v1' and uart.get('status')=='PASS',
             'UART vendor/physical helper lacks a passing reviewed schema')
        need(uart.get('checker_sha256')==scripts[str(uart_script)]['sha256'] and
             uart.get('dependency_sha256')==scripts[str(tx_script)]['sha256'],'UART helper/dependency hash mismatch')
        need(uart.get('scope')=='engineering_board_bringup','UART helper scope changed')
        need(set(uart.get('evidence',{}))==set(uart_paths),'UART helper raw evidence set mismatch')
        for key,path in uart_paths.items():
            item=uart['evidence'][key]
            need(Path(item['path']).resolve()==path.resolve() and item['sha256']==sha(path),'UART helper used different raw evidence')
        probe=uart.get('probe',{})
        need(probe.get('status')=='PASS' and probe.get('scope')=='vendor_uart_technology_netlist_functional' and
             probe.get('channels')==128 and probe.get('variable_ff_count')==7 and probe.get('response_lines')==143,
             'UART gate probe lacks all channels and rejection/OFF/gain coverage')
        need(set(uart.get('corners',{}))=={'slow','fast'} and uart['corners']['slow']==uart['corners']['fast'],
             'UART routed FF audit lacks identical slow/fast connections')
        for corner in uart['corners'].values():
            bits=corner.get('bits',[])
            need(corner.get('variable_ff_count')==7 and corner.get('clock_input')=='sys_clk_27' and
                 len(bits)==7 and {item.get('bit') for item in bits}==set(range(7)) and
                 len({item.get('instance') for item in bits})==7,'UART routed audit lacks seven independent sys27 channel FFs')
        results = {'pdm': pdm, 'tx': tx,'i2s':i2s,'uart_vendor':uart}
        # Include exact outputs in the release JSON, with their raw JSON hashes.
        output_hashes = {'pdm': sha(output/'pdm.json'), 'tx': sha(output/'tx.json'),'i2s':sha(output/'i2s.json'),'uart_vendor':sha(output/'uart_vendor.json')}
    return {'results': results, 'helper_output_sha256': output_hashes,
            'database': database, 'pdm_contract': pdm_contract}


def check_pdm_contract(root, fdc, timing):
    """Tie the independent budget's constants to the actual FDC and RTL."""
    lines = commands(fdc)
    input_limits = [line for line in lines if line.startswith('set_max_delay') and 'pdm_data' in line]
    output_limits = [line for line in lines if line.startswith('set_max_delay') and 'mic_clk' in line]
    need(input_limits == ['set_max_delay 5.000 -datapath_only -from [get_ports {pdm_data[*]}] -to [get_cells -hierarchical {*data_meta*}]'],
         'PDM budget requires the reviewed 5 ns input bound')
    need(output_limits == ['set_max_delay 4.000 -datapath_only -to [get_ports {mic_clk[*]}]'],
         'PDM budget requires the reviewed 4 ns clock-pad bound')
    need(abs(timing['clocks']['audio122']['period_ns'] - 1e9/122880000) <= .001, 'PDM capture clock differs from budget')
    strip = lambda value: re.sub(r'/\*.*?\*/|//[^\n]*', '', value, flags=re.S)
    capture = strip((root/'rtl/pdm_capture.sv').read_text(encoding='utf8'))
    top = strip((root/'rtl/mems_array_top.sv').read_text(encoding='utf8'))
    for parameter, expected in (('CLOCK_DIV', '40'), ('SAMPLE_TICK', '19')):
        need(re.findall(r'parameter\s+integer\s+'+parameter+r'\s*=\s*(\d+)', capture) == [expected],
             'PDM sample interval constant changed: '+parameter)
    instances = re.findall(r'pdm_capture\s*#\((.*?)\)\s*capture\s*\(', top, re.S)
    need(len(instances) == 1 and re.sub(r'\s+', '', instances[0]) == '.STARTUP_CYCLES(STARTUP_CYCLES)',
         'PDM instance overrides or changes the reviewed sample timing')
    for assignment in ('data_meta <= pdm_data;', 'data_sync <= data_meta;',
                       'if (phase == SAMPLE_TICK) high_phase <= data_sync;'):
        need(re.sub(r'\s+', '', assignment) in re.sub(r'\s+', '', capture), 'PDM synchronizer/sample timing changed')
    return {'clock_div': 40, 'sample_tick': 19, 'synchronizer_latency_cycles': 2,
            'effective_sample_interval_cycles': 17, 'input_bound_ns': 5, 'clock_pad_bound_ns': 4}


def check_route_selection(manifest, root, build, text, artifact):
    """Authenticate a completed first PNR iteration before continuing its flow.

    PDS may start another optimization after saving a fully routed, passing
    result. Selection is distinct from claiming that the optimizer exited
    successfully; its original transcript and manifest remain as evidence.
    """
    selection = manifest.get('route_checkpoint_selection')
    if selection is None:
        return None
    need(isinstance(selection, dict) and selection.get('iteration') == 1,
         'Only an explicitly completed first route iteration can be selected')
    saved_manifest = artifact('checkpoint_source_manifest', build/'checkpoint_selection/source_manifest.json', '.json')
    saved_log = artifact('checkpoint_optimizer_log', build/'checkpoint_selection/optimizer.log', '.log')
    need(sha(saved_manifest) == selection.get('source_manifest_sha256') and
         sha(saved_log) == selection.get('optimizer_log_sha256'), 'Checkpoint origin evidence hash mismatch')
    origin = read_json(saved_manifest)
    need(origin.get('start_stage') == 'compile' and origin.get('requested_stage') == 'gen_bit_stream' and
         origin.get('device') == manifest.get('device') and origin.get('started_at') == manifest.get('started_at') and
         origin.get('source_sha256') == manifest.get('source_sha256'), 'Checkpoint is not from this full unchanged build')
    need(origin.get('flow_evidence') == manifest.get('flow_evidence', [])[:2] and
         [f.get('stages') for f in origin.get('flow_evidence', [])] == [list(STAGES[:3]), ['place']],
         'Checkpoint has no matching completed compile/map/place provenance')
    for key in ('postmap_constraints', 'postplace_link'):
        need(origin.get(key) is not None and origin.get(key) == manifest.get(key), 'Checkpoint input linkage changed: '+key)
    original = saved_log.read_text(encoding='utf8')
    boundaries = list(re.finditer(r'^I: Current iteration time: (\d+)\s*$', original, re.M))
    need(len(boundaries) >= 2 and [m[1] for m in boundaries[:2]] == ['1','2'],
         'Checkpoint transcript does not prove the first iteration ended before another began')
    prefix = original[:boundaries[1].start()]
    need(text.startswith(prefix+'MEMS_PANGO_PNR_COMPLETE\n'), 'Selected build log is not the original completed route prefix')
    need(not re.search(r'^[ \t]*[ECW]: (?:Internal-|Flow-)|^[ \t]*E:', prefix, re.M), 'Selected route prefix contains a failed tool action')
    section = original[boundaries[0].end():boundaries[1].start()]
    counts = re.findall(r'^Total net: (\d+), route succeed net: (\d+)\s*$', section, re.M)
    need(len(counts) == 1 and int(counts[0][0]) > 0 and counts[0][0] == counts[0][1], 'Selected checkpoint is not fully routed')
    need('No hold violation.' in section and
         section.count("Design '"+TOP+"' has been routed successfully.") == 1 and
         'Saving design to DB.' in section and 'Action pnr: Real time elapsed is ' in section and
         'Action pnr: Peak memory pool usage is ' in section, 'Missing native completed PNR iteration evidence')
    checkpoint = artifact('completed_route_checkpoint', build/'place_route/route_constraint_ite_1'/f'{TOP}_pnr.adf', '.adf')
    routed = artifact('selected_routed_database', build/'place_route'/f'{TOP}_pnr.adf', '.adf')
    need(sha(checkpoint) == sha(routed) == selection.get('routed_db_sha256') == manifest.get('routed_db_sha256'),
         'Selected route database is not the completed checkpoint')
    report = artifact('checkpoint_original_timing', build/'place_route/route_constraint_ite_1'/f'{TOP}.rtr', '.rtr')
    need(sha(report) == selection.get('timing_report_sha256') and 'Design Summary : All Constraints Met.' in report.read_text(),
         'Selected checkpoint did not meet its original timing constraints')
    route_script = artifact('checkpoint_route_script', build/'route.tcl', '.tcl')
    need(sha(route_script) == selection.get('route_script_sha256'), 'Original route recipe changed after selection')
    finalizer = root/'fpga/scripts/finalize_route_checkpoint.py'
    need(finalizer.is_file() and sha(finalizer) == selection.get('finalizer_sha256'), 'Checkpoint finalizer changed')
    for index, record in enumerate(manifest.get('checkpoint_resume_records', [])):
        previous = artifact('checkpoint_failed_audit_'+str(index), build/record['manifest'], '.json')
        need(sha(previous) == record.get('sha256'), 'Checkpoint resume manifest hash mismatch')
        data = read_json(previous)
        need(data.get('status') == 'FAIL' and data.get('source_sha256') == manifest.get('source_sha256') and
             data.get('routed_db_sha256') == manifest.get('routed_db_sha256') and
             data.get('flow_evidence') == manifest.get('flow_evidence', [])[:6], 'Checkpoint resume changed completed build evidence')
    return selection


def check_stage_log(text, pre_bit, split_place=False, route_selection=None):
    """PDS queues Tcl commands: marker text alone never proves execution."""
    stages = list(STAGES[:-1] if pre_bit else STAGES)
    if split_place:
        stages.insert(stages.index('pnr'), 'place')
    markers = list(re.finditer(r'^MEMS_PANGO_(\w+)_COMPLETE\s*$', text, re.M))
    need([m[1] for m in markers] == [s.upper() for s in stages],
         'Build log does not prove all required stages completed once in order')
    pattern = r'^Executing : ('+'|'.join(STAGES)+r')((?: [^\r\n]*)?) successfully\.[ \t]*$'
    completions = list(re.finditer(pattern, text, re.M))
    def phase(match):
        return 'place' if match[1]=='pnr' and re.search(r'\s-place_only(?:\s|$)',match[2]) else match[1]
    events = [(m.start(), phase(m), m[1]+m[2]) for m in completions]
    if route_selection is not None:
        need(split_place, 'Route checkpoint selection requires the completed placement stage')
        checkpoints = list(re.finditer(r"^Design '"+TOP+r"' has been routed successfully\.$", text, re.M))
        need(len(checkpoints) == 1, 'Missing or duplicate native completed route checkpoint')
        events.append((checkpoints[0].start(), 'pnr', 'completed PNR iteration 1; authenticated checkpoint selection'))
        events.sort()
    need([e[1] for e in events] == stages,
         'PDS native successful stage completions are missing, duplicated or out of order')
    evidence = []
    for (offset, stage, command), marker in zip(events, markers):
        need(offset < marker.start(), 'Stage marker precedes actual PDS completion: '+stage)
        evidence.append({'stage': stage, 'successful_command': command,
                         'completion_line': text.count('\n', 0, offset)+1,
                         'marker_line': text.count('\n', 0, marker.start())+1})
    return evidence


def frontend_floorplan_mode(manifest):
    implementation = manifest.get('implementation', {})
    mode = implementation.get('frontend_floorplan_mode', 'fixed')
    need(mode in ('fixed', 'auto'), 'Unknown frontend floorplan mode')
    if mode == 'auto':
        need(implementation.get('floorplan') is None, 'Auto placement must not select a frontend template')
    return mode


def check_pnr_recipe(manifest, script_command, native_command, is_place, text):
    """Bind the explicit new recipe; historical fixed-flow evidence is unchanged."""
    implementation = manifest.get('implementation', {})
    if 'frontend_floorplan_mode' not in implementation:
        return
    recipe = implementation.get('route_constraint_iteration', {})
    maximum = recipe.get('maximum')
    need(type(maximum) is int and maximum in (1, 2) and recipe.get('enabled') is True,
         'Invalid single/two-route implementation recipe')
    need(implementation.get('router_threads') == 5, 'PG2L200H recipe requires five router threads')
    expected = {'-number_of_router_thread': '5', '-mode': 'performance',
                '-max_ctrl_chain_length': '8', '-fix_hold_violation_in_route': 'TRUE',
                '-fix_hold_violation_threshold_for_clock_path_cross_srb': '20',
                '-fix_hold_violation_threshold_for_clk_tree': '20',
                '-max_hold_violated_paths_num': '50000', '-dump_router_congestion_plot': 'TRUE',
                '-action_timeout': str(implementation.get('pnr_timeout_minutes')),
                '-gplace_seed': str(implementation.get('placement_seed')),
                '-plc_decongestion': str(implementation.get('placement_decongestion')),
                '-plc_initial_method': implementation.get('placement_initial_method')}
    need(type(implementation.get('pnr_timeout_minutes')) is int and implementation['pnr_timeout_minutes'] > 0 and
         type(implementation.get('placement_seed')) is int and implementation['placement_seed'] > 0 and
         type(implementation.get('placement_decongestion')) is int and 0 <= implementation['placement_decongestion'] <= 9 and
         implementation.get('placement_initial_method') in ('Center', 'Quad'), 'Invalid bound PNR parameters')
    # PDS accepts a PLC input only through its constraint-route entry, even
    # when that entry is limited to one routing iteration.
    iterate = not is_place
    for command in (script_command, native_command):
        for option, value in expected.items():
            need(re.findall(r'(?<!\S)'+re.escape(option)+r'\s+(\S+)', command) == [value],
                 'PNR recipe option differs from manifest: '+option)
        need(not re.search(r'(?<!\S)-(?:parallel|route_parallel|gplace_times|groute_times)(?:\s|$)', command),
             'PNR recipe must not introduce multi-seed actions')
        flags = re.findall(r'(?<!\S)-enable_route_constraint_iterate(?:\s|$)', command)
        need(len(flags) == int(iterate), 'Unexpected optional route-constraint iteration')
        for option, value in {'-route_constraint_iterate_times':str(maximum), '-route_constraint_slack':'0.050',
                              '-route_constraint_max_timing_path':'8'}.items():
            need(re.findall(r'(?<!\S)'+re.escape(option)+r'\s+(\S+)', command) == ([value] if iterate else []),
                 'Unexpected route-constraint iteration option: '+option)
    if not is_place:
        need(text.count('MEMS_PANGO_PLACE_COMPLETE') == 1, 'PNR recipe requires one completed placement')
        route_text = text.split('MEMS_PANGO_PLACE_COMPLETE', 1)[1].split('MEMS_PANGO_PNR_COMPLETE', 1)[0]
        sizes = re.findall(r'^Route thread size:\s*(\d+)\s*$', route_text, re.M)
        need(sizes and all(size == '5' for size in sizes), 'Missing or inconsistent native five-thread routing evidence')
        iterations = [int(value) for value in re.findall(r'^I:\s*Current iteration time:\s*(\d+)\s*$', route_text, re.M)]
        need(not iterations or iterations == list(range(1, len(iterations)+1)) and len(iterations) <= maximum,
             'Actual route iteration count exceeds the bound recipe')
        need(not re.search(r'(?:Worst slack after (?:global|post global|detailed) placement|(?:Global|Detailed) placement takes)', route_text),
             'Routing unexpectedly performed another placement')


def check_flow_provenance(manifest, root, build, text, pre_bit, artifact, start, end):
    """Bind each Python-driven PDS process to its script and one routed DB."""
    routed = artifact('routed_database', build/'place_route'/f'{TOP}_pnr.adf', '.adf')
    need(manifest.get('routed_db_sha256') == sha(routed), 'Routed database hash differs from build manifest')
    split = manifest.get('postmap_constraints') is not None
    split_place = manifest.get('postplace_link') is not None
    selected_route = manifest.get('route_checkpoint_selection') is not None
    need(not split_place or split, 'Placement stage requires audited map/PCF inputs')
    if frontend_floorplan_mode(manifest) == 'auto':
        need(split and split_place, 'Auto placement requires complete map and placement provenance')
        need(not selected_route, 'Auto placement does not use legacy checkpoint selection')
    expected = [('MEMS_Array', list(STAGES[:3] if split else STAGES[:-1]), 'build.tcl')]
    if split:
        if split_place:
            expected.append(('MEMS_Array_place', ['place'], 'place.tcl'))
        if selected_route:
            expected += [('MEMS_Array_route_selection', ['pnr'], 'route.tcl'),
                         ('MEMS_Array_timing', ['report_timing'], 'finalize_timing.tcl')]
        else:
            expected.append(('MEMS_Array_route', ['pnr', 'report_timing'], 'route.tcl'))
        mapped, physical_pcf = check_postmap_link(manifest, root, build, text, artifact)
        route_input = mapped
        if split_place:
            route_input = artifact('placed_database', build/'place_route'/f'{TOP}_placed_input.adf', '.adf')
            need(manifest['postplace_link'].get('placed_db_sha256') == sha(route_input), 'Placement input hash mismatch')
    expected += [('MEMS_Array_slow_sdf', ['gen_netlist'], 'export_slow.tcl'),
                 ('MEMS_Array_fast_sdf', ['gen_netlist'], 'export_fast.tcl')]
    if not pre_bit:
        expected.append(('MEMS_Array_bitstream', ['gen_bit_stream'], 'generate_bitstream.tcl'))
    flows = manifest.get('flow_evidence')
    need(isinstance(flows, list) and len(flows) == len(expected), 'Missing or extra completed PDS process evidence')
    native_exports = re.findall(r'^Executing : (gen_netlist(?: [^\r\n]*)?) successfully\.[ \t]*$', text, re.M)
    need(len(native_exports) == 2, 'Both real corner-export completions are required exactly once')
    native_bit = re.findall(r'^Executing : (gen_bit_stream(?: [^\r\n]*)?) successfully\.[ \t]*$', text, re.M)

    def check_database_argument(command, database=routed):
        paths = re.findall(r'-input_db_file\s+(\{[^}]+\}|"[^"]+"|\S+)', command)
        need(len(paths) == 1 and Path(paths[0].strip('{}"')).resolve() == database,
             'PDS command does not use the audited routed database' if database == routed else
             ('Route command does not use the audited placed database' if split_place and database == route_input else 'Route command does not use the audited mapped database'))

    previous = start-1
    for index, (flow, (project, stages, filename)) in enumerate(zip(flows, expected)):
        selection_flow = selected_route and stages == ['pnr']
        success = (flow.get('execution_kind') == 'completed_checkpoint_selection' and 'exit_code' not in flow) if selection_flow else flow.get('exit_code') == 0
        need(flow.get('project') == project and flow.get('stages') == stages and success,
             'PDS process project/stage/exit evidence mismatch')
        completed = timestamp(flow['completed_at'])
        need(previous <= completed <= end+1, 'PDS process completion times are invalid or out of order')
        previous = completed
        script = artifact('flow_script_'+str(index), root/flow['script'], '.tcl')
        need(script == build/filename and sha(script) == flow.get('script_sha256'), 'Executed PDS script path/hash mismatch')
        lines = commands(script.read_text(encoding='utf8'))
        if frontend_floorplan_mode(manifest) == 'auto':
            need(not any(line.startswith('def_inst_site ') or
                         line.startswith('add_constraint ') and 'frontend_floorplan.pcf' in line for line in lines),
                 'Auto placement scripts must not apply frontend macro constraints')
        actions = [line for line in lines if re.match(r'^(?:'+ '|'.join(STAGES)+r'|gen_netlist)\b', line)]
        script_phases = ['place' if line.startswith('pnr ') and re.search(r'\s-place_only(?:\s|$)',line) else line.split()[0] for line in actions]
        need(script_phases == (['pnr','report_timing'] if selection_flow else stages), 'PDS script action sequence differs from completed process')
        need(not any(re.match(r'^(?:puts|exec|file|flush)\b', line) for line in lines),
             'Flow scripts must not rely on pre-executed Tcl side effects')
        if stages in (['place'], ['pnr', 'report_timing']) or selection_flow:
            native_routes = re.findall(r'^Executing : (pnr(?: [^\r\n]*)?)'+('' if selection_flow else r' successfully\.')+r'[ \t]*$', text, re.M)
            if selection_flow:
                native_routes = [c for c in native_routes if not c.endswith(' successfully.')]
            is_place = stages == ['place']
            native_routes = [command for command in native_routes if bool(re.search(r'\s-place_only(?:\s|$)',command)) == is_place]
            need(len(native_routes) == 1, 'Missing actual staged routing completion')
            for command in (actions[0], native_routes[0]):
                check_database_argument(command, mapped if is_place else route_input)
            check_pnr_recipe(manifest, actions[0], native_routes[0], is_place, text)
            selected = [line for line in lines if line.startswith('add_constraint ') and physical_pcf.as_posix() in line]
            need(len(selected) == 1, 'Route script must select the audited physical PCF')
        elif stages == ['report_timing']:
            native_timing = re.findall(r'^Executing : (report_timing(?: [^\r\n]*)?) successfully\.[ \t]*$', text, re.M)
            need(len(native_timing) == 1, 'Missing standalone timing completion')
            for command in (actions[0], native_timing[0]):
                check_database_argument(command)
        elif stages == ['gen_netlist']:
            corner_index = 0 if filename == 'export_slow.tcl' else 1
            for command in (actions[0], native_exports[corner_index]):
                check_database_argument(command)
                corner = 'slow' if corner_index == 0 else 'fast'
                need(re.search(r'-process_corner\s+'+corner+r'(?:\s|$)', command) and
                     re.search(r'-sdf_annotate\s+FALSE(?:\s|$)', command), 'Corner export command mismatch')
        elif stages == ['gen_bit_stream']:
            need(len(native_bit) == 1, 'Missing real bitstream completion')
            for command in (actions[0], native_bit[0]):
                check_database_argument(command)
    return flows


def check_route_entry_recovery(manifest, root, build, log_path, artifact):
    """Authenticate only the pre-routing PLC-entry failure and its byte prefix.

    Failed evidence remains separate and hashed. It cannot stand in for an
    actual successful routing, timing, corner export, or bitstream completion.
    """
    recovery = manifest.get('route_entry_recovery')
    if recovery is None:
        return None
    need(isinstance(recovery, dict) and frontend_floorplan_mode(manifest) == 'auto' and
         manifest.get('route_checkpoint_selection') is None, 'Invalid route-entry recovery mode')
    directory = recovery.get('archive_dir')
    need(isinstance(directory, str) and not Path(directory).is_absolute() and
         (root/directory).resolve() == (build/'resume_before_route').resolve(),
         'Route-entry recovery archive must belong to this build')
    archive = (root/directory).resolve()
    paths = {name: artifact('route_entry_previous_'+name, archive/filename, suffix)
             for name, filename, suffix in (('build_log', 'build.log', '.log'),
                 ('manifest', 'manifest.json', '.json'), ('route_script', 'route.tcl', '.tcl'),
                 ('build_recipe', 'build.py', '.py'))}
    for name, path in paths.items():
        need(sha(path) == recovery.get('previous_'+name+'_sha256'),
             'Route-entry recovery archived identity mismatch: '+name)
    previous = read_json(paths['manifest'])
    need(previous.get('status') == 'FAIL' and previous.get('exit_code') == 1 and
         previous.get('sources_unchanged') is True and
         previous.get('start_stage') == 'compile' and previous.get('requested_stage') == 'gen_bit_stream',
         'Route-entry recovery must preserve the failed full-build manifest')
    need(previous.get('device') == manifest.get('device') and
         previous.get('started_at') == manifest.get('started_at'),
         'Route-entry recovery changed build origin')
    recovered_at = timestamp(recovery.get('recovered_at'))
    end = timestamp(manifest['completed_at']) if manifest.get('completed_at') else datetime.now().astimezone().timestamp()
    need(timestamp(previous['started_at']) <= timestamp(previous['completed_at']) <= recovered_at <= end+1,
         'Route-entry recovery timestamps are invalid')
    old_sources, new_sources = previous.get('source_sha256'), manifest.get('source_sha256')
    recipe_source = 'fpga/scripts/build.py'
    need(isinstance(old_sources, dict) and isinstance(new_sources, dict) and
         set(old_sources) == set(new_sources) and recipe_source in old_sources and
         all(old_sources[key] == new_sources[key] for key in old_sources if key != recipe_source),
         'Route-entry recovery may change only the build recipe source')
    need(sha(paths['build_recipe']) == old_sources[recipe_source] and
         sha(root/recipe_source) == new_sources[recipe_source],
         'Route-entry recovery build recipe source binding mismatch')
    old_implementation, new_implementation = previous.get('implementation', {}), manifest.get('implementation', {})
    need({k:v for k,v in old_implementation.items() if k != 'route_constraint_iteration'} ==
         {k:v for k,v in new_implementation.items() if k != 'route_constraint_iteration'},
         'Route-entry recovery changed placement or routing parameters')
    old_iteration = old_implementation.get('route_constraint_iteration', {})
    new_iteration = new_implementation.get('route_constraint_iteration', {})
    need(old_iteration.get('enabled') is False and old_iteration.get('maximum') == 1 and
         new_iteration.get('enabled') is True and type(new_iteration.get('maximum')) is int and
         new_iteration['maximum'] in (1, 2) and
         {k:v for k,v in old_iteration.items() if k not in ('enabled', 'maximum')} ==
         {k:v for k,v in new_iteration.items() if k not in ('enabled', 'maximum')},
         'Route-entry recovery did not repair only the PLC routing entry')
    need(previous.get('flow_evidence') == manifest.get('flow_evidence', [])[:2] and
         isinstance(previous.get('flow_evidence'), list) and
         [row.get('stages') for row in previous['flow_evidence']] == [list(STAGES[:3]), ['place']] and
         all(row.get('exit_code') == 0 for row in previous['flow_evidence']),
         'Route-entry recovery changed completed compile/map/place evidence')
    need(all(timestamp(previous['started_at']) <= timestamp(row['completed_at']) <=
             timestamp(previous['completed_at']) for row in previous['flow_evidence']),
         'Route-entry recovery completed input stages postdate the archived failure')
    for key in ('postmap_constraints', 'postplace_link'):
        need(previous.get(key) is not None and previous[key] == manifest.get(key),
             'Route-entry recovery changed map/PCF/placement linkage: '+key)
    placed = artifact('route_entry_same_placed_input', build/'place_route'/f'{TOP}_placed_input.adf', '.adf')
    plc = artifact('route_entry_original_placed_database', build/'place_route'/f'{TOP}_plc.adf', '.adf')
    need(sha(placed) == sha(plc) == previous['postplace_link'].get('placed_db_sha256'),
         'Route-entry recovery does not use the same completed PLC database')
    original_bytes = paths['build_log'].read_bytes()
    markers = list(re.finditer(rb'(?m)^MEMS_PANGO_PLACE_COMPLETE\r?\n', original_bytes))
    retained = recovery.get('retained_log_bytes')
    need(len(markers) == 1 and type(retained) is int and retained == markers[0].end(),
         'Route-entry recovery must retain exactly the completed-placement byte prefix')
    prefix = original_bytes[:retained]
    need(hashlib.sha256(prefix).hexdigest() == recovery.get('retained_log_sha256') and
         Path(log_path).resolve() == (build/'build.log').resolve() and Path(log_path).read_bytes().startswith(prefix),
         'Route-entry recovery retained log prefix identity mismatch')
    before = prefix.decode('utf-8')
    failed = original_bytes[retained:].decode('utf-8')
    need(not re.search(r'(?m)^[ \t]*E:', before), 'Route-entry recovery completed prefix contains a tool error')
    prefix_markers = re.findall(r'(?m)^MEMS_PANGO_(\w+)_COMPLETE\s*$', before)
    prefix_completions = list(re.finditer(r'^Executing : ('+'|'.join(STAGES)+r')((?: [^\r\n]*)?) successfully\.[ \t]*\r?$', before, re.M))
    prefix_stages = ['place' if row[1] == 'pnr' and re.search(r'\s-place_only(?:\s|$)', row[2]) else row[1]
                     for row in prefix_completions]
    need(prefix_markers == ['COMPILE', 'SYNTHESIZE', 'DEV_MAP', 'PLACE'] and
         prefix_stages == ['compile', 'synthesize', 'dev_map', 'place'],
         'Route-entry recovery prefix does not prove only completed compile/map/place')
    failures = re.findall(r"(?m)^E: Flow-0013: The input DB '([^'\r\n]+)' should be of phase 'DEVMAP'\.[ \t]*\r?$", failed)
    need(len(failures) == 1 and Path(failures[0]).resolve() == placed.resolve(),
         'Route-entry recovery is not the specific pre-routing PLC/DEVMAP failure')
    other_errors = [line for line in failed.splitlines() if re.match(r'^[ \t]*E:', line) and
                    not re.fullmatch(r"E: Flow-0013: The input DB '[^']+' should be of phase 'DEVMAP'\.[ \t]*", line) and
                    not re.fullmatch(r'E: Failed to execute the script\s*:\s*', line)]
    need(not other_errors and not re.search(r'(?m)^(?:I: Current iteration time:|Route thread size:|Routing started\.|Finished routing\.|MEMS_PANGO_\w+_COMPLETE)', failed) and
         not re.search(r"has been routed successfully|^Executing : (?:pnr|report_timing|gen_netlist|gen_bit_stream)[^\r\n]* successfully\.", failed, re.M),
         'Route-entry recovery archive contains another error or started/completed routing')
    route_commands = commands(paths['route_script'].read_text(encoding='utf-8'))
    actions = [line for line in route_commands if re.match(r'^(?:'+ '|'.join(STAGES)+r'|gen_netlist)\b', line)]
    need([line.split()[0] for line in actions] == ['pnr', 'report_timing'] and
         not any(re.match(r'^(?:puts|exec|file|flush)\b', line) for line in route_commands),
         'Route-entry recovery archived route script is not the original queued flow')
    inputs = re.findall(r'-input_db_file\s+(\{[^}]+\}|"[^"]+"|\S+)', actions[0])
    need(len(inputs) == 1 and Path(inputs[0].strip('{}"')).resolve() == placed.resolve() and
         not re.search(r'-enable_route_constraint_iterate|-route_constraint_(?:iterate_times|slack|max_timing_path)|-place_only', actions[0]),
         'Route-entry recovery archived route recipe differs from the failed PLC entry')
    attempted = re.findall(r'^Executing : (pnr(?: [^\r\n]*)?)[ \t]*\r?$', failed, re.M)
    normalize = lambda command: command.replace('{', '').replace('}', '').replace('"', '').split()
    need(len(attempted) == 1 and normalize(attempted[0]) == normalize(actions[0]),
         'Route-entry recovery original route command was not actually attempted')
    return {'status': 'PASS', 'scope': 'authenticated_pre_route_entry_recovery',
            'archived_failure_status': 'FAIL', 'archive_dir': directory,
            'recovered_at': recovery['recovered_at'], 'retained_log_bytes': retained,
            'retained_log_sha256': recovery['retained_log_sha256'],
            'previous_sha256': {name: sha(path) for name, path in paths.items()},
            'same_placed_db_sha256': sha(placed), 'permitted_source_change': recipe_source}


def check_postmap_link(manifest, root, build, text, artifact):
    """A split flow must prove immutable map/PCF inputs, not merely stage names."""
    link = manifest['postmap_constraints']
    need(isinstance(link, dict), 'Invalid postmap link evidence')
    mapped = artifact('mapped_database', build/'device_map'/f'{TOP}_map.adf', '.adf')
    base = artifact('base_physical_constraints', build/'device_map'/f'{TOP}_base.pcf', '.pcf')
    pcf = artifact('route_physical_constraints', build/'device_map'/f'{TOP}.pcf', '.pcf')
    template = root/'fpga/constraints/frontend_floorplan.pcf'
    need(template.is_file(), 'Missing floorplan source template')
    for field, path in [('mapped_db_sha256', mapped), ('base_pcf_sha256', base), ('route_pcf_sha256', pcf), ('template_sha256', template)]:
        need(link.get(field) == sha(path), 'Postmap input hash mismatch: '+field)
    mode = frontend_floorplan_mode(manifest)
    if 'frontend_floorplan_mode' in manifest.get('implementation', {}):
        need(link.get('frontend_floorplan_mode') == mode and link.get('template_applied') is (mode == 'fixed'),
             'Postmap frontend mode/application differs from manifest')
    if mode == 'auto':
        need(pcf.read_bytes() == base.read_bytes(), 'Auto physical PCF is not the exact generated base')
        need(not re.search(r'^Executing : def_inst_site\b', text, re.M),
             'Auto placement log applies fixed macro locations')
    else:
        need(pcf.read_bytes() == base.read_bytes()+b'\n'+template.read_bytes(),
             'Physical PCF is not the exact generated base plus reviewed template')
        # No clocks, false paths, or arbitrary Tcl can enter through the template.
        locations = []
        for line in commands(template.read_text(encoding='ascii')):
            m = re.fullmatch(r'def_inst_site \{(core/frontend/fir[12]/[^{}]+)\} ((APM|DRM)_\d+_\d+) (XAPM_CORE_[UD]|DRM0)', line)
            need(m is not None, 'Floorplan template contains an unexpected command')
            cell, site, kind, element = m.groups()
            need((kind == 'APM' and re.fullmatch(r'core/frontend/fir[12]/N\d+/gopapm', cell) and element.startswith('XAPM_CORE_')) or
                 (kind == 'DRM' and re.fullmatch(r'core/frontend/fir[12]/lane\[\d+\]\.history(?:_[01])?/gopdrm_36k', cell) and element == 'DRM0'),
                 'Unexpected floorplan resource/instance mapping')
            locations.append((cell, site, element, kind))
            need('Executing : '+line+' successfully' in text, 'Floorplan location was not actually accepted: '+cell)
        need(len(locations) == 176 and Counter(row[3] for row in locations) == {'APM':128, 'DRM':48}, 'Incomplete frontend floorplan')
        need(len({row[0] for row in locations}) == 176 and len({row[1:3] for row in locations}) == 176, 'Duplicate floorplan cell/site')
    pins = pins_from_fdc((root/'fpga/constraints/board_pins.fdc').read_text())
    base_ports = {}
    for line in commands(base.read_text(encoding='ascii')):
        m = re.fullmatch(r'def_port \{([^}]+)\} (.+)', line)
        need(m is not None and m[1] not in base_ports, 'Unexpected command/duplicate port in generated physical PCF')
        fields = {}
        for token in m[2].split():
            key, sep, value = token.partition('=')
            need(sep and key in {'LOC','VCCIO','IOSTANDARD','DRIVE','SLEW'} and key not in fields and re.fullmatch(r'[A-Za-z0-9_.]+', value), 'Unexpected physical port attribute')
            fields[key] = value
        base_ports[m[1]] = fields
    need(set(base_ports) == PORTS, 'Generated physical PCF has a different port set')
    for port, fields in base_ports.items():
        need(all(fields.get(k) == pins[port][v] for k,v in [('LOC','LOC'),('VCCIO','VCCIO'),('IOSTANDARD','STANDARD')]), 'Generated physical PCF pin mismatch: '+port)
    output_attributes = re.findall(r'define_attribute\s+\{p:([^}]+)\}\s+\{PAP_IO_(DRIVE|SLEW)\}\s+\{([^}]+)\}',
                                   (root/'fpga/constraints/board_pins.fdc').read_text())
    for port, attr, value in output_attributes:
        need(base_ports.get(port,{}).get(attr)==value, 'Generated physical PCF output attribute mismatch: '+port+' '+attr)
    return mapped, pcf


def check_audio_config_cdc(root, fdc, timing):
    """Prove the source mailbox contract and its whole-domain routing coverage.

    The 56 held bits are bundled data, never independent bit synchronizers.
    Request/ACK traverse preserved two-stage chains. Alive is a local reset
    release chain; its asynchronous bridge reset is not a sampled data bus.
    No synthesized instance name is used as a substitute for timing coverage.
    """
    paths = ('rtl/diag/audio_config_cdc.sv', 'rtl/diag/board_uart_diagnostics.sv',
             'rtl/board/mems_array_pg2l200h.sv', 'rtl/board/pango_board_clocks.v')
    source = {}
    for relative in paths:
        value = (root/relative).read_text()
        value = re.sub(r'/\*.*?\*/|//[^\n]*', '', value, flags=re.S)
        source[relative] = re.sub(r'\s+', '', value)
    cdc = source[paths[0]]
    signatures = (
        'wire[55:0]desired={desired_enable,desired_channel,desired_even_gain,desired_odd_gain};',
        'wirebridge_rst_n=ref_rst_n&&audio_rst_n;',
        '(*syn_preserve=1*)reg[55:0]held,accepted;',
        '(*async_reg="true",syn_preserve=1*)regalive_meta,alive_sync,ack_meta,ack_sync;',
        '(*async_reg="true",syn_preserve=1*)regrequest_meta,request_sync;',
        'elsebeginalive_meta<=1;alive_sync<=alive_meta;end',
        'ack_meta<=acknowledge;ack_sync<=ack_meta;',
        'request_meta<=request_toggle;request_sync<=request_meta;',
        'elseif(waiting)beginif(ack_sync==request_toggle)beginwaiting<=0;accepted<=held;dirty<=0;endend',
        'elseif(dirty||accepted!=desired)beginheld<=desired;request_toggle<=~request_toggle;waiting<=1;end',
        'if(!audio_gain_cfg_valid&&request_sync!=acknowledge)begin'
        'audio_even_gain<=held[47:24];audio_odd_gain<=held[23:0];audio_gain_cfg_valid<=1;',
        'elseif(audio_gain_cfg_valid&&audio_gain_cfg_ready)begin'
        'audio_i2s_enable<=held[55];audio_i2s_channel<=held[54:48];'
        'audio_gain_cfg_valid<=0;acknowledge<=request_sync;')
    for signature in signatures:
        need(cdc.count(signature) == 1, 'Audio configuration CDC contract changed: '+signature)
    events = re.findall(r'always@\(([^)]+)\)', cdc)
    need(Counter(events) == Counter({'posedgeref_clkornegedgebridge_rst_n': 2,
                                    'posedgeaudio_clkornegedgebridge_rst_n': 1}),
         'Audio configuration CDC clock/reset domains changed')
    for name, count in (('held', 2), ('request_meta', 2), ('request_sync', 2),
                        ('ack_meta', 2), ('ack_sync', 2), ('alive_meta', 2), ('alive_sync', 2)):
        need(len(re.findall(name+r'<=', cdc)) == count,
             'Audio configuration CDC has an unreviewed extra assignment: '+name)
    need('audio_config_cdcconfiguration(.ref_clk(ref_clk),.ref_rst_n(observer_rst_n),'
         '.audio_clk(audio_clk),.audio_rst_n(audio_rst_n),' in source[paths[1]],
         'Audio configuration bridge no longer uses the supervisor/audio clocks')
    board = source[paths[2]]
    for signature in ('.ref_clk_27(sys_clk_27)', '.audio_clk(audio_clk)',
                      '.monitor_ref_clk(monitor_ref_clk)', '.ref_clk(monitor_ref_clk)'):
        need(signature in board, 'Board audio configuration clock connection changed')
    clocks = source[paths[3]]
    for signature in ('.I(ref_clk_27),.O(clk_27_ibuf)',
                      'GTP_CLKBUFG u_monitor_ref(.CLKIN(clk_27_ibuf),.CLKOUT(monitor_ref_clk));'):
        need(signature.replace(' ', '') in clocks, 'Supervisor clock is no longer the reviewed sys27 tree')
    lines = commands(fdc)
    need(not any(line.startswith('set_clock_groups') for line in lines),
         'Audio configuration CDC routing bounds cannot be overridden by clock groups')
    coverage = {}
    for launch, capture in (('sys27', 'audio122'), ('audio122', 'sys27')):
        bound = f'set_max_delay 7.500 -datapath_only -from [get_clocks {launch}] -to [get_clocks {capture}]'
        hold = f'set_false_path -hold -from [get_clocks {launch}] -to [get_clocks {capture}]'
        need(lines.count(bound) == 1 and lines.count(hold) == 1,
             'Audio configuration CDC requires the unchanged whole-domain 7.500 ns bound')
        extras = [line for line in lines if f'-from [get_clocks {launch}]' in line and
                  f'-to [get_clocks {capture}]' in line and
                  line.startswith(('set_max_delay', 'set_false_path', 'set_multicycle_path'))]
        need(set(extras) == {bound, hold}, 'Audio configuration CDC has an overriding timing exception')
        for corner in ('Slow', 'Fast'):
            rows = [p for p in timing['summaries']['Setup/'+corner]
                    if tuple(p['clocks']) == (launch, capture)]
            need(len(rows) == 1 and rows[0]['total_endpoints'] > 0 and
                 rows[0]['failing_endpoints'] == 0 and math.isfinite(rows[0]['worst_slack_ns']) and
                 rows[0]['worst_slack_ns'] >= 0,
                 'Audio configuration CDC lacks passing two-corner whole-domain coverage')
            coverage[f'{launch}->{capture}/{corner}'] = rows[0]
    return {'payload_bits': 56, 'routing_bound_ns': 7.5, 'request_ack_sync_stages': 2,
            'alive_reset_release_stages': 2, 'held_stable_until_ack': True,
            'coverage_scope': 'every path in sys27/audio122 domains, including held payload and first-stage request/ACK',
            'source_sha256': {relative: sha(root/relative) for relative in paths},
            'physical_coverage': coverage}


def audit(args, root=ROOT):
    root = root.resolve()
    script_paths = [Path(__file__).resolve(), root/'fpga/scripts/check_pdm_budget.py', root/'fpga/scripts/check_tx_source.py',root/'fpga/scripts/check_i2s_budget.py',root/'fpga/scripts/check_uart_vendor.py']
    scripts = {str(path): {'path': str(path), 'sha256': sha(path)} for path in script_paths}
    manifest_path, regression_path = Path(args.manifest).resolve(), Path(args.regression).resolve()
    manifest_hash, regression_hash = sha(manifest_path), sha(regression_path)
    manifest, regression = read_json(manifest_path), read_json(regression_path)
    if manifest.get('route_checkpoint_selection') is not None:
        finalizer = root/'fpga/scripts/finalize_route_checkpoint.py'
        scripts[str(finalizer)] = {'path': str(finalizer), 'sha256': sha(finalizer)}
    pre_bit = bool(args.pre_bit)
    if pre_bit:
        need(manifest.get('status') in {'RUNNING', 'PASS'} and manifest.get('exit_code', 0) == 0, 'Pre-bit manifest has failed')
    else:
        need(manifest.get('sources_unchanged') is True, 'Build manifest must attest unchanged sources before final audit')
        need(manifest.get('status') == 'PASS' and manifest.get('exit_code') == 0, 'Build manifest is not a successful unchanged build')
    need(manifest.get('requested_stage') == 'gen_bit_stream' and manifest.get('start_stage') == 'compile', 'Release requires compile through gen_bit_stream in one run')
    need(manifest.get('device') == 'PG2L200H-6-FBB676', 'Build device mismatch')
    start = timestamp(manifest['started_at'])
    end = datetime.now().astimezone().timestamp() if pre_bit else timestamp(manifest['completed_at'])
    need(end >= start and end <= datetime.now().astimezone().timestamp()+1, 'Invalid build time interval')
    current = current_build_sources(root)
    need(manifest.get('source_sha256') == current, 'Build sources/coefficients/constraints changed, were added or were removed')
    need(regression.get('status') == 'PASS' and regression.get('vendor_included') is True and regression.get('models_reused') is False, 'Release requires full model and vendor regression PASS')
    need(set(regression.get('steps', {})) == set(STEPS) and all(regression['steps'][s].get('status') == 'PASS' for s in STEPS), 'Incomplete full regression steps')
    uart_probe_path=root/'log/vendor_uart/result.json'
    need(uart_probe_path.is_file(),'Missing mandatory UART vendor regression result')
    uart_probe_hash=sha(uart_probe_path)
    need(regression['steps']['vendor_uart'].get('evidence')=={'path':'log/vendor_uart/result.json','sha256':uart_probe_hash},
         'Full regression UART vendor result path/hash mismatch')
    regression_sources = scanned_sources(root)
    need(regression.get('sources_sha256') == regression_sources, 'Regression source set/hash differs from current workspace')
    need({k: v for k, v in current.items() if k.startswith('rtl/')} == {k: v for k, v in regression_sources.items() if k.startswith('rtl/')}, 'Build and regression used different RTL/coefficient headers')
    vectors = {p.relative_to(root).as_posix(): sha(p) for p in sorted((root/'tb/vectors').glob('*')) if p.is_file()}
    need(vectors and regression.get('vectors_sha256') == vectors, 'Reference vector set/hash mismatch')
    evidence = {'vendor_uart_regression':{'path':str(uart_probe_path),'bytes':uart_probe_path.stat().st_size,'sha256':uart_probe_hash}}
    fir_ram = check_fir_ram(root, regression, evidence)
    build = manifest_path.parent

    def artifact(label, value, suffix=None):
        path = Path(value).resolve()
        need(path.is_relative_to(build) and path.is_file(), f'{label} must be an existing artifact in this build directory: {path}')
        need(path.stat().st_size > 0, f'Empty {label}')
        if suffix:
            need(path.suffix.lower() == suffix, f'Wrong {label} suffix')
        # PDS embedded dates have one-second resolution; filesystem mtime does not.
        need(start-1 <= path.stat().st_mtime <= end+1, f'Stale or post-build {label}: {path}')
        evidence[label] = {'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path),
                           'modified_at': datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat()}
        return path

    pll_validation = check_pll_validation(read_json(artifact('pll_validation', build/'pll_validation.json', '.json')), root)
    artifact('vendor_pll_check', build/'vendor_pll_check.log', '.log')
    artifact('vendor_pll_validation_script', build/'validate_vendor_pll.tcl', '.tcl')
    texts = {}
    for label, value, suffix in (
        ('timing_report', args.timing_report, '.rtr'), ('constraints_report', args.constraints_report, '.ccr'),
        ('map_report', args.map_report, '.dmr'), ('timing_log', args.timing_log or Path(args.timing_report).parent/'run.log', '.log'),
        ('build_log', args.build_log or build/'build.log', '.log')):
        texts[label] = artifact(label, value, suffix).read_text(encoding='utf-8', errors='replace')
    build_log = texts['build_log']
    route_entry_recovery = check_route_entry_recovery(manifest, root, build,
        args.build_log or build/'build.log', artifact)
    need(not re.search(r'^[ \t]*E:[ \t]+', build_log, re.M), 'PDS build log contains errors')
    route_selection = check_route_selection(manifest, root, build, build_log, artifact)
    stage_completions = check_stage_log(build_log, pre_bit, manifest.get('postplace_link') is not None, route_selection)
    flow_evidence = check_flow_provenance(manifest, root, build, build_log, pre_bit, artifact, start, end)
    need(not re.search(r'^[ \t]*[ECW]:[ \t]+Internal-', build_log, re.M), 'Build contains rejected timing exception Internal-1001 or other Internal diagnostic')
    # Check the report's original timestamp as well as its filesystem timestamp.
    for label, pattern, fmt in (
        ('timing_report', r'^\|\s*Date\s*:\s*(.+)$', '%a %b %d %H:%M:%S %Y'),
        ('constraints_report', r'Written on (\d{4}/\d\d/\d\d \d\d:\d\d:\d\d)', '%Y/%m/%d %H:%M:%S'),
        ('map_report', r'^Generated by Fabric Compiler .* at (.+)$', '%a %b %d %H:%M:%S %Y')):
        m = re.search(pattern, texts[label], re.M)
        need(m is not None, f'Missing original report date: {label}')
        report_time = datetime.strptime(m[1].strip(), fmt).astimezone().timestamp()
        need(start-1 <= report_time <= end+1, f'Original report date is outside this build: {label}')
    pins_text = (root/'fpga/constraints/board_pins.fdc').read_text()
    fdc = (root/'fpga/constraints/timing.fdc').read_text()
    pins = pins_from_fdc(pins_text)
    mapping = check_map(texts['map_report'], pins_text, fdc)
    constraints = check_constraints(texts['constraints_report'], fdc, pins, root)
    timing = check_timing(texts['timing_report'], texts['timing_log'], fdc, root/'fpga/constraints/timing.fdc',
                          build/'place_route'/f'{TOP}_pnr.adf' if route_selection is not None else None)
    audio_configuration_cdc = check_audio_config_cdc(root, fdc, timing)
    physical = check_physical(args, root, build, artifact, scripts, timing, fdc)
    need(physical['results']['uart_vendor']['probe'].get('result_sha256')==uart_probe_hash,
         'Fresh UART helper used another regression result')
    if not pre_bit:
        need(args.bitstream is not None, 'Final release requires --bitstream')
        # PDS "Create Bit File" emits .sbit, including an unencrypted stream.
        artifact('bitstream', args.bitstream, '.sbit')
        need(Path(args.bitstream).stem == TOP, 'Bitstream top-module filename mismatch')
        need(Path(args.bitstream).stat().st_mtime >= Path(args.timing_report).stat().st_mtime, 'Bitstream predates final timing report')
        if args.bin:
            artifact('binary', args.bin, '.bin')
    # Recheck after reading reports, preventing a concurrent edit being certified.
    need(current == current_build_sources(root) and regression_sources == scanned_sources(root), 'Sources changed during release audit')
    need(sha(manifest_path) == manifest_hash and sha(regression_path) == regression_hash, 'Build or regression manifest changed during audit')
    need(vectors == {p.relative_to(root).as_posix(): sha(p) for p in sorted((root/'tb/vectors').glob('*')) if p.is_file()}, 'Reference vectors changed during release audit')
    for item in evidence.values():
        need(sha(Path(item['path'])) == item['sha256'], 'Artifact changed during release audit')
    for item in scripts.values():
        need(sha(Path(item['path'])) == item['sha256'], 'Executed audit script changed during release audit')
    return {'status': 'PASS', 'phase': 'pre-bit' if pre_bit else 'release', 'release_authorized': not pre_bit,
            'scope': 'engineering_board_bringup',
            'model_scope': 'PDS original '+timing['timing_models']+' multi-corner model; complete functional regression',
            'qualification': {'unconditional_board_qualification': False,
                              'txc_duty_and_jitter': 'UNCONFIRMED: measure actual TXC duty/jitter at the PHY before board qualification',
                              'sensitivity_status': physical['results']['tx']['duty']['sensitivity_status'],
                              'required_edgepair_jitter_max_ns': physical['results']['tx']['duty']['required_edgepair_jitter_max_ns'],
                              'board_conditions': ['TXC output duty must be 45..55 percent at the PHY',
                                                   'RGMII PCB relative skew budget is at most 0.200 ns',
                                                   'PDM external round-trip propagation budget is at most 20 ns',
                                                   'Verify PDM clock load, edge rates and duty with all microphones connected',
                                                   'I2S DAC input and L5 bank operate at 3.3 V',
                                                   'I2S relative wiring/edge delay budget is at most 20 ns; verify actual DAC setup/hold and clock waveforms']},
            'checked_at': datetime.now().astimezone().isoformat(), 'device': manifest['device'],
            'build_started_at': manifest['started_at'], 'build_completed_at': manifest.get('completed_at'),
            'build_manifest': {'path': str(manifest_path), 'sha256': manifest_hash},
            'regression': {'path': str(regression_path), 'sha256': regression_hash},
            'checker_sha256': scripts[str(Path(__file__).resolve())]['sha256'], 'audit_scripts': scripts,
            'source_sha256': current, 'vectors_sha256': vectors, 'evidence': evidence,
            'stage_completions': stage_completions,
            'flow_evidence': flow_evidence, 'route_entry_recovery': route_entry_recovery,
            'mapping': mapping, 'constraints': constraints, 'timing': timing, 'physical': physical,
            'pll_validation': pll_validation, 'audio_configuration_cdc': audio_configuration_cdc, 'fir_ram_regression': fir_ram}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('manifest', 'regression', 'timing-report', 'constraints-report', 'map-report', 'output'):
        p.add_argument('--'+name, required=True, type=Path)
    p.add_argument('--bin', type=Path)
    p.add_argument('--bitstream', type=Path, help='Required for final release; omitted with --pre-bit')
    p.add_argument('--pre-bit', action='store_true', help='Audit timing before generating bitstream; does not authorize release')
    p.add_argument('--timing-log', type=Path, help='Default: timing report sibling run.log')
    p.add_argument('--build-log', type=Path, help='Default: manifest sibling build.log')
    p.add_argument('--report-db', type=Path, help='Default: timing report sibling rtr.db')
    for corner in ('slow', 'fast'):
        p.add_argument('--'+corner+'-sdf', type=Path, help='Default: build/clock_audit/'+corner+'_sta.sdf')
        p.add_argument('--'+corner+'-netlist', type=Path, help='Default: build/clock_audit/'+corner+'_sim.v')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = audit(args)
        code = 0
    except (ReleaseError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        result = {'status': 'FAIL', 'checked_at': datetime.now().astimezone().isoformat(), 'error': str(exc)}
        code = 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    print('[RELEASE_'+result['status']+'] '+(result.get('error') or str(args.output)), flush=True)
    return code


if __name__ == '__main__':
    sys.exit(main())
