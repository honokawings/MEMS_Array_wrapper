"""Gate fixtures exercise report parsing; they are not FPGA timing evidence."""
from datetime import datetime, timedelta
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1]/'check_release.py'
spec = importlib.util.spec_from_file_location('check_release', SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class ReleaseGateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.build = self.root/'fpga/build/MEMS_Array'
        self.now = datetime.now().astimezone()-timedelta(seconds=2)
        self.start = self.now-timedelta(minutes=2)
        self.write('rtl/top.sv', 'module top; endmodule\n')
        self.write('rtl/fir1_coeff.svh', '32\'d1\n')
        self.write('rtl/pdm_capture.sv', 'parameter integer CLOCK_DIV=40, SAMPLE_TICK_UNUSED=0;\nparameter integer SAMPLE_TICK=19;\ndata_meta <= pdm_data;\ndata_sync <= data_meta;\nif (phase == SAMPLE_TICK) high_phase <= data_sync;\n')
        self.write('rtl/mems_array_top.sv', 'pdm_capture #(.STARTUP_CYCLES(STARTUP_CYCLES)) capture(.clk(clk));\n')
        self.write('fpga/scripts/build.py', '# Fixture build script\n')
        self.write('fpga/scripts/check_pll_parameters.py', '# Fixture PLL validator\n')
        self.write('rtl/board/pango_board_clocks.v', '// Fixture clocks, not a physical PLL\n')
        self.write('vendor_rules.tcl', '# Fixture vendor input\n')
        pll_rows=[]
        for name,fin,i,m,o in [('u_pll_eth',125.0,4,16,4),('u_pll_96',27.0,1,16,9),('u_pll_audio',96.0,5,16,5)]:
            pll_rows.append(dict(name=name,input_mhz=fin,idiv=i,mdiv=m,odiv=o,pfd_mhz=fin/i,
                vco_mhz=fin/i*m*2,output_mhz=fin/i*m*2/o,bandwidth='OPTIMIZED',fdiv=2))
        pll=dict(status='PASS',negative_control_original_rejected=True,validated_instances=pll_rows,
            rtl_source=str(self.root/'rtl/board/pango_board_clocks.v'),rtl_sha256=gate.sha(self.root/'rtl/board/pango_board_clocks.v'),
            validator_sha256=gate.sha(self.root/'fpga/scripts/check_pll_parameters.py'),
            vendor_source=str(self.root/'vendor_rules.tcl'),vendor_sha256=gate.sha(self.root/'vendor_rules.tcl'))
        self.put(self.build/'pll_validation.json',json.dumps(pll))
        self.put(self.build/'vendor_pll_check.log','Fixture vendor check\n')
        self.put(self.build/'validate_vendor_pll.tcl','# Fixture invocation\n')
        self.write('fpga/scripts/check_pdm_budget.py', '# Mocked helper; not timing evidence\n')
        self.write('fpga/scripts/check_tx_source.py', '# Mocked helper; not timing evidence\n')
        self.write('tb/vectors/expected_pcm.bin', b'\x01\x02\x03')
        pins = []
        for i, name in enumerate(sorted(gate.PORTS)):
            direction = 'INOUT' if name == 'PHY0_MDIO' else 'INPUT'
            for attr, value in [('DIRECTION', direction), ('LOC', f'A{i+1}'), ('VCCIO', '3.3'), ('STANDARD', 'LVCMOS33')]:
                pins.append(f'define_attribute {{p:{name}}} {{PAP_IO_{attr}}} {{{value}}}')
        self.pin_fdc = '\n'.join(pins)+'\n'
        self.fdc = 'set_max_delay 5.000 -datapath_only -from [get_ports {pdm_data[*]}] -to [get_cells -hierarchical {*data_meta*}]\nset_max_delay 4.000 -datapath_only -to [get_ports {mic_clk[*]}]\nset_input_delay -max 0 -clock audio122 [get_ports {pdm_data[*]}]\n'
        self.write('fpga/constraints/board_pins.fdc', self.pin_fdc)
        self.write('fpga/constraints/timing.fdc', self.fdc)
        self.rtr = self.build/'report_timing'/f'{gate.TOP}.rtr'
        self.ccr = self.build/'constraint_check/constraint_check.ccr'
        self.dmr = self.build/'device_map'/f'{gate.TOP}.dmr'
        self.bit = self.build/'generate_bitstream'/f'{gate.TOP}.sbit'
        self.put(self.rtr, self.timing_report())
        self.put(self.rtr.parent/'rtr.db', self.database_report())
        for corner in ('slow', 'fast'):
            self.put(self.build/'clock_audit'/f'{corner}_sta.sdf', 'Mock SDF input\n')
            self.put(self.build/'clock_audit'/f'{corner}_sim.v', 'Mock netlist input\n')
        self.put(self.ccr, self.constraint_report())
        self.put(self.dmr, self.map_report())
        self.put(self.rtr.parent/'run.log', 'Action report_timing: Peak memory pool usage 256 MB\n')
        self.put(self.build/'build.log', self.build_log(gate.STAGES))
        self.put(self.bit, b'FIXTURE_NOT_A_REAL_BITSTREAM')
        self.routed = self.build/'place_route'/f'{gate.TOP}_pnr.adf'
        self.put(self.routed, b'FIXTURE_NOT_A_ROUTED_DATABASE')
        flows = [('MEMS_Array', list(gate.STAGES[:-1]), 'build.tcl', '\n'.join(gate.STAGES[:-1])),
                 ('MEMS_Array_slow_sdf', ['gen_netlist'], 'export_slow.tcl', self.export_command('slow')),
                 ('MEMS_Array_fast_sdf', ['gen_netlist'], 'export_fast.tcl', self.export_command('fast')),
                 ('MEMS_Array_bitstream', ['gen_bit_stream'], 'generate_bitstream.tcl', self.bit_command())]
        flow_evidence = []
        for project, stages, filename, content in flows:
            path = self.build/filename
            self.put(path, content+'\n')
            flow_evidence.append({'project': project, 'stages': stages, 'script': path.relative_to(self.root).as_posix(),
                                  'script_sha256': gate.sha(path), 'exit_code': 0, 'completed_at': self.now.isoformat()})
        self.manifest = {'status': 'PASS', 'exit_code': 0, 'sources_unchanged': True,
                         'requested_stage': 'gen_bit_stream', 'start_stage': 'compile',
                         'started_at': self.start.isoformat(), 'completed_at': self.now.isoformat(),
                         'device': 'PG2L200H-6-FBB676', 'source_sha256': gate.current_build_sources(self.root),
                         'routed_db_sha256': gate.sha(self.routed), 'flow_evidence': flow_evidence}
        self.regression = {'status': 'PASS', 'vendor_included': True, 'models_reused': False,
                           'steps': {s: {'status': 'PASS'} for s in gate.STEPS},
                           'sources_sha256': gate.scanned_sources(self.root),
                           'vectors_sha256': {'tb/vectors/expected_pcm.bin': gate.sha(self.root/'tb/vectors/expected_pcm.bin')}}
        self.save_json()
        self.args = gate.parser().parse_args([
            '--manifest', str(self.build/'manifest.json'), '--regression', str(self.root/'log/full_regression.json'),
            '--timing-report', str(self.rtr), '--constraints-report', str(self.ccr), '--map-report', str(self.dmr),
            '--bitstream', str(self.bit), '--output', str(self.build/'release.json')])
        self.helper_mock = mock.patch.object(gate, 'run_helper', side_effect=self.helper_result).start()
        self.addCleanup(mock.patch.stopall)

    def helper_result(self, script, arguments, output):
        """Only the orchestration is tested here; physical parsers have real probes."""
        pairs = {str(arguments[i])[2:].replace('-', '_'): Path(arguments[i+1]) for i in range(0, len(arguments), 2)}
        if script.name == 'check_pdm_budget.py':
            result = {'schema': 'mems-pdm-routed-budget-v1', 'status': 'PASS',
                      'checker_sha256': gate.sha(script),
                      'corners': {c: {'remaining_ns': 1.0} for c in ('slow', 'fast')},
                      'evidence': {k: {'path': str(p), 'sha256': gate.sha(p)} for k, p in pairs.items()}}
        else:
            result = {'schema_version': 1, 'status': 'PASS', 'scope': 'engineering_board_bringup', 'unconditional_board_qualification': False,
                      'errors': [], 'cases': [{}, {}, {}, {}], 'duty': {'status': 'PASS', 'nominal_model_status': 'PASS',
                      'qualification_status': 'UNCONFIRMED', 'sensitivity_status': 'FAIL', 'required_edgepair_jitter_max_ns': .271,
                      'conservative_jitter_sensitivity': {'status': 'FAIL', 'edge_jitter_budget_ns': .360, 'cases': [{'pass': False}, {'pass': False}]}},
                      'inputs': {'report_db': str(pairs['report_db']), 'constraints': str(pairs['constraints']),
                                 'report_db_sha256': gate.sha(pairs['report_db']),
                                 'constraints_sha256': gate.sha(pairs['constraints']), 'helper_sha256': gate.sha(script)}}
            for key in ('slow_sdf', 'slow_netlist', 'fast_sdf', 'fast_netlist'):
                result['inputs'][key] = str(pairs[key])
                result['inputs'][key+'_sha256'] = gate.sha(pairs[key])
        output.write_text(json.dumps(result), encoding='utf8')
        return result

    def put(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, bytes):
            path.write_bytes(value)
        else:
            path.write_text(value, encoding='utf-8')
        os.utime(path, (self.now.timestamp(), self.now.timestamp()))

    def build_log(self, stages):
        main = [s for s in stages if s != 'gen_bit_stream']
        text = ''.join(f'Executing : {s} successfully.\n' for s in main)+''.join(f'MEMS_PANGO_{s.upper()}_COMPLETE\n' for s in main)
        text += ''.join('Executing : '+self.export_command(c)+' successfully.\n' for c in ('slow', 'fast'))
        if 'gen_bit_stream' in stages:
            text += 'Executing : '+self.bit_command()+' successfully.\nMEMS_PANGO_GEN_BIT_STREAM_COMPLETE\n'
        return text

    def export_command(self, corner):
        path = self.build/'place_route'/f'{gate.TOP}_pnr.adf'
        return 'gen_netlist -input_db_file {'+str(path)+'} -sdf_annotate FALSE -process_corner '+corner

    def bit_command(self):
        path = self.build/'place_route'/f'{gate.TOP}_pnr.adf'
        return 'gen_bit_stream -create_bit_file TRUE -input_db_file {'+str(path)+'}'

    def write(self, name, value):
        self.put(self.root/name, value)

    def save_json(self):
        self.put(self.build/'manifest.json', json.dumps(self.manifest))
        self.write('log/full_regression.json', json.dumps(self.regression))

    def timing_report(self):
        lines = [f'| Date : {self.now.strftime("%a %b %d %H:%M:%S %Y")}',
                 f'| Design : {gate.TOP}', '| Device : PG2L200H', '| Speed Grade : -6',
                 '| Package : FBB676', '| Timing Models : Production', '| Tcl Command : report_timing',
                 'Timing analysis mode : multi corner', 'Clock Summary:', '**********',
                 ' Clock Period Waveform Type ClockLoads Non-clockLoads Sources', '----------']
        sources = {'sys27': 'sys_clk_27', 'ref125': 'sys_clk_125_p', 'rx125': 'PHY0_RXC',
                   'eth250': 'clocks/u_pll_eth/u_gpll/CLKOUT0', 'eth125': 'clocks/u_eth_div/iockdiv_inst/CLKOUT',
                   'audio96': 'clocks/u_pll_96/u_gpll/CLKOUT0', 'audio122': 'clocks/u_pll_audio/u_gpll/CLKOUT0',
                   'pdm3072': 'mic_clk[0]', 'mdc992k': 'PHY0_MDC', 'rx_data_launch': '', 'async_pad_ref': '', 'tx_pad_ref': ''}
        for name, period in gate.CLOCKS.items():
            rise = 2 if name == 'rx_data_launch' else 0
            loads = 7 if name in gate.CORE_CLOCKS else 0
            virtual = name in {'rx_data_launch', 'async_pad_ref', 'tx_pad_ref'}
            kind = 'Virtual' if virtual else 'Declared'
            if name in gate.CLOCK_PARENTS:
                kind = 'Generated ('+gate.CLOCK_PARENTS[name]+')'
            source = '' if virtual else '{'+sources[name]+'}'
            lines.append(f'{name} {period:.4f} {{{rise:.4f} {rise+period/2:.4f}}} {kind} {loads} 0 {source}')
        lines += ['==========', 'Design Summary : All Constraints Met.']
        for corner in ('Slow', 'Fast'):
            for kind in gate.SUMMARY_TYPES:
                lines += [f'{kind} Summary({corner} Corner):', '**********', 'Clocks Worst Total Failing Endpoints', '----------']
                for clock in sorted(gate.CORE_CLOCKS):
                    names = clock if kind == 'Minimum Pulse Width' else f'{clock} {clock}'
                    lines.append(f'{names} 0.150 0.000 0 7')
                if kind == 'Setup':
                    for launch, capture in [('audio122', 'eth125'), ('eth125', 'audio122'), ('rx125', 'eth125'), ('eth125', 'rx125')]:
                        lines.append(f'{launch} {capture} 0.150 0.000 0 7')
                    for launch, capture in gate.UART_CDC_PAIRS:
                        lines.append(f'{launch} {capture} 0.150 0.000 0 7')
                if kind in ('Setup', 'Hold'):
                    lines += ['rx_data_launch rx125 0.150 0.000 0 5']
                if kind == 'Setup':
                    lines += ['eth125 tx_pad_ref 0.150 0.000 0 6']
                lines.append('==========')
        return '\n'.join(lines)+'\n'

    def constraint_report(self):
        return f'''##### Written on {self.now.strftime('%Y/%m/%d %H:%M:%S')} ####
Current device :
 PG2L200H-6FBB676
Top Module :
 {gate.TOP}
Constraint File(s) :
 {(self.root/'fpga/constraints/board_pins.fdc').as_posix()}
 {(self.root/'fpga/constraints/timing.fdc').as_posix()}
Found 0 error(s), 0 critical warning(s), 0 warning(s), out of 350 constraint(s)
Unconstrained ports:
**********

Constraints with matching wildcard expressions:
**********
 I: The pattern '*data_meta*' in command 'get_cells -hierarchical *data_meta*' match 1 objects below:
 I: instance core/frontend/capture/data_meta[63:0]

 I: The pattern 'pdm_data[*]' in command 'get_ports {{pdm_data[*]}}' match 64 objects below:
'''+''.join(f' I: port pdm_data[{i}]\n' for i in range(64))+"\n I: The pattern 'pdm_data[*]' in command 'get_ports {pdm_data[*]}' match 64 objects below:\n"+''.join(f' I: port pdm_data[{i}]\n' for i in range(64))+"\n I: The pattern 'mic_clk[*]' in command 'get_ports {mic_clk[*]}' match 8 objects below:\n"+''.join(f' I: port mic_clk[{i}]\n' for i in range(8))

    def database_report(self):
        doc = gate.ET.Element('tables')
        def table(name, rows):
            t = gate.ET.SubElement(doc, 'table', id=name)
            for values in rows:
                row = gate.ET.SubElement(t, 'row')
                for value in values:
                    gate.ET.SubElement(row, 'data').text = str(value)
            return t
        text = self.rtr.read_text()
        table('report_timing_clock_summary', [[name, x['type'], x['period_ns'], '', x['rise_ns'], x['fall_ns'], x['clock_loads'], x['nonclock_loads'], x['parent'], '']
                                             for name, x in gate.parse_clock_summary(text).items()])
        for corner in ('Slow', 'Fast'):
            for kind in gate.SUMMARY_TYPES:
                suffix = 'mpw' if kind == 'Minimum Pulse Width' else kind.lower()
                table(f'report_timing_{corner.lower()}_{suffix}', [x['clocks']+[x['worst_slack_ns'], x['total_slack_ns'], x['failing_endpoints'], x['total_endpoints']]
                                                                 for x in gate.parse_summary(text, kind, corner)])
        table('check_timing_summary', [[name, 0] for name in ('no_clock', 'virtual_clock', 'unexpandable_clocks', 'no_input_delay', 'no_output_delay',
                                                           'partial_input_delay', 'partial_output_delay', 'io_min_max_delay_consistency',
                                                           'input_delay_assigned_to_clock', 'loops', 'latch_loops', 'latchs')])
        return gate.ET.tostring(doc, encoding='unicode')

    def map_report(self):
        text = f'Generated by Fabric Compiler ( version 2022.2-SP6.4 ) at {self.now.strftime("%a %b %d %H:%M:%S %Y")}\nTiming Constraint:\n----------\n{self.fdc}\nLogical Constraint:\n'
        for name, attrs in gate.pins_from_fdc(self.pin_fdc).items():
            text += f'| {name} | {attrs["DIRECTION"].lower()} | {attrs["LOC"]} | {attrs["VCCIO"]} | {attrs["STANDARD"]} |\n'
        return text

    def test_mapped_drive_and_slew_are_checked(self):
        port='mic_clk[0]'
        pin_fdc=self.pin_fdc+'define_attribute {p:mic_clk[0]} {PAP_IO_DRIVE} {16}\n'+'define_attribute {p:mic_clk[0]} {PAP_IO_SLEW} {FAST}\n'
        lines=self.map_report().splitlines()
        report='\n'.join(line+' 16 | | FAST |' if line.startswith('| '+port+' |') else line for line in lines)+'\n'
        gate.check_map(report,pin_fdc,self.fdc)
        for bad in (report.replace(' 16 | | FAST |',' 8 | | FAST |'),report.replace(' 16 | | FAST |',' 16 | | SLOW |')):
            with self.assertRaises(gate.ReleaseError):gate.check_map(bad,pin_fdc,self.fdc)

    def rejected(self, contains):
        with self.assertRaisesRegex(gate.ReleaseError, contains):
            gate.audit(self.args, self.root)

    def test_full_release(self):
        result = gate.audit(self.args, self.root)
        self.assertEqual(result['status'], 'PASS')
        self.assertTrue(result['release_authorized'])
        self.assertEqual(len(result['timing']['summaries']), 10)
        self.assertEqual(result['evidence']['bitstream']['sha256'], gate.sha(self.bit))
        self.assertEqual(result['mapping']['ports'], 99)

    def test_pre_bit_running_without_unchanged(self):
        self.args.pre_bit = True
        self.args.bitstream = None
        self.manifest.update(status='RUNNING')
        for key in ('sources_unchanged', 'exit_code', 'completed_at'):
            self.manifest.pop(key)
        self.manifest['flow_evidence'] = self.manifest['flow_evidence'][:3]
        self.save_json()
        self.put(self.build/'build.log', self.build_log(gate.STAGES[:-1]))
        result = gate.audit(self.args, self.root)
        self.assertFalse(result['release_authorized'])
        self.assertNotIn('bitstream', result['evidence'])

    def test_missing_bit(self):
        self.bit.unlink()
        self.rejected('existing artifact')

    def test_stale_bit(self):
        os.utime(self.bit, (self.start.timestamp()-5, self.start.timestamp()-5))
        self.rejected('Stale')

    def test_stale_report_original_date(self):
        text = self.rtr.read_text().replace(self.now.strftime('%a %b %d %H:%M:%S %Y'), 'Mon Jan 01 00:00:00 2024')
        self.put(self.rtr, text)
        self.rejected('Original report date')

    def test_changed_source(self):
        self.write('rtl/top.sv', '// Changed after build\n')
        self.rejected('sources/coefficients/constraints changed')

    def test_added_source(self):
        self.write('rtl/new.sv', 'module new; endmodule\n')
        self.rejected('sources/coefficients/constraints changed')

    def test_changed_test(self):
        self.write('tb/new.sv', '// New untested testbench\n')
        self.rejected('Regression source set')

    def test_reference_vectors_changed(self):
        self.write('tb/vectors/expected_pcm.bin', b'\xFF')
        self.rejected('Reference vector')

    def test_regression_model_reuse(self):
        self.regression['models_reused'] = True
        self.save_json()
        self.rejected('full model and vendor')

    def test_negative_timing(self):
        self.put(self.rtr, self.rtr.read_text().replace('0.150 0.000 0 7', '-0.001 0.000 0 7', 1))
        self.rejected('Timing violation')

    def test_empty_fast_corner(self):
        import re
        text = re.sub(r'(Setup Summary\(Fast Corner\):\n\*+\n[^\n]+\n-+\n).*?(?==========)', r'\1', self.rtr.read_text(), flags=re.S)
        self.put(self.rtr, text)
        self.rejected('Empty or incomplete')

    def test_nan_timing(self):
        self.put(self.rtr, self.rtr.read_text().replace('0.150 0.000 0 7', 'nan 0.000 0 7', 1))
        self.rejected('Nonfinite')

    def test_zero_clock_loads(self):
        self.put(self.rtr, self.rtr.read_text().replace('Declared 7 0 {PHY0_RXC}', 'Declared 0 0 {PHY0_RXC}'))
        self.rejected('no functional loads')

    def test_wrong_clock_phase(self):
        self.put(self.rtr, self.rtr.read_text().replace('rx_data_launch 8.0000 {2.0000 6.0000}', 'rx_data_launch 8.0000 {0.0000 4.0000}'))
        self.rejected('Incorrect clock phase')

    def test_no_clock_warning(self):
        self.put(self.rtr.parent/'run.log', 'W: STA-3011: Clock pin foo has no clock\nAction report_timing: done\n')
        self.rejected('Timing diagnostics')

    def test_rejected_pds_exception(self):
        text = (self.build/'build.log').read_text()+'C: Internal-1001: unsupported bound\n'
        self.put(self.build/'build.log', text)
        self.rejected('Internal-1001')

    def test_unmatched_wildcard(self):
        self.put(self.ccr, self.ccr.read_text().replace('match 64 objects', 'match 0 objects'))
        self.rejected('unmatched/truncated wildcard')

    def test_missing_constraint_object(self):
        self.put(self.ccr, self.ccr.read_text().replace(' I: port pdm_data[63]\n', ''))
        self.rejected('unmatched/truncated wildcard')

    def test_unknown_critical_warning(self):
        text = self.ccr.read_text().replace('0 critical warning(s)', '1 critical warning(s)')+'C: SDC-2023: Ignored constraint\n'
        self.put(self.ccr, text)
        self.rejected('Unreviewed constraint')

    def test_wrong_pin_location(self):
        self.put(self.dmr, self.dmr.read_text().replace('| A1 |', '| Z99 |', 1))
        self.rejected('Mapped I/O')

    def test_map_missing_constraint(self):
        self.put(self.dmr, self.dmr.read_text().replace(self.fdc.splitlines()[0]+'\n', '', 1))
        self.rejected('DMR timing constraints differ')

    def test_missing_stage_marker(self):
        self.put(self.build/'build.log', (self.build/'build.log').read_text().replace('MEMS_PANGO_PNR_COMPLETE\n', ''))
        self.rejected('required stages')

    def test_wrapped_summary_rows(self):
        self.put(self.rtr, self.rtr.read_text().replace('audio122 audio122 0.150 0.000 0 7', 'audio122\n audio122\n 0.150 0.000 0 7'))
        self.assertEqual(gate.audit(self.args, self.root)['status'], 'PASS')

    def test_documented_pds_waveform_rounding(self):
        text = self.rtr.read_text().replace('audio122 8.1380 {0.0000 4.0690}', 'audio122 8.1380 {0.0000 4.0680}')
        text = text.replace('pdm3072 325.5208 {0.0000 162.7604}', 'pdm3072 325.5205 {0.0000 162.7200}')
        self.put(self.rtr, text)
        self.put(self.rtr.parent/'rtr.db', self.database_report())
        self.assertEqual(gate.audit(self.args, self.root)['status'], 'PASS')

    def test_reviewed_shared_pin_notice(self):
        text = self.ccr.read_text().replace('0 critical warning(s)', '1 critical warning(s)')
        name, attrs = next(iter(gate.pins_from_fdc(self.pin_fdc).items()))
        text += f'C: ConstraintEditor-2002: [board_pins.fdc(line number: 1)] | Port {name} has been placed at location {attrs["LOC"]}, whose type is share pin.\n'
        self.put(self.ccr, text)
        self.assertEqual(len(gate.audit(self.args, self.root)['constraints']['shared_pin_notices']), 1)

    def test_cdc_accidentally_false_pathed(self):
        self.put(self.rtr, self.rtr.read_text().replace('audio122 eth125 0.150 0.000 0 7\n', ''))
        self.rejected('missing bounded CDC paths')

    def test_rgmii_control_unconstrained(self):
        self.put(self.rtr, self.rtr.read_text().replace('rx_data_launch rx125 0.150 0.000 0 5', 'rx_data_launch rx125 0.150 0.000 0 4'))
        self.rejected('missing RGMII data/control paths')

    def test_presilicon_model_and_current_build_options_recorded(self):
        command = 'report_timing -delay_type min_max -report_io_datasheet -report_exception TRUE -max_path 8'
        text = self.rtr.read_text().replace('Timing Models : Production', 'Timing Models : Pre-silicon')
        text = text.replace('Tcl Command : report_timing\n', 'Tcl Command : '+command+'\n')
        self.put(self.rtr, text)
        result = gate.audit(self.args, self.root)
        self.assertEqual(result['timing']['timing_models'], 'Pre-silicon')
        self.assertEqual(result['timing']['report_command'], command)
        self.assertEqual(result['timing']['report_options']['-max_path'], 8)
        self.assertEqual(len(result['timing']['summaries']), 10)

    def test_real_probe_metadata_format(self):
        metadata = gate.timing_metadata('| Timing Models: Pre-silicon\n| Tcl Command  : report_timing -nworst 6 -max_path 30 \n')
        self.assertEqual(metadata['timing_models'], 'Pre-silicon')
        self.assertEqual(metadata['report_options'], {'-nworst': 6, '-max_path': 30})

    def test_unknown_model_rejected(self):
        self.put(self.rtr, self.rtr.read_text().replace('Timing Models : Production', 'Timing Models : Estimated'))
        self.rejected('Unknown RTR timing model')

    def test_unknown_timing_option_rejected(self):
        self.put(self.rtr, self.rtr.read_text().replace('Tcl Command : report_timing', 'Tcl Command : report_timing -from audio122'))
        self.rejected('Unsupported report_timing option')

    def test_setup_only_command_rejected(self):
        self.put(self.rtr, self.rtr.read_text().replace('Tcl Command : report_timing', 'Tcl Command : report_timing -delay_type max'))
        self.rejected('both min and max')

    def test_duplicate_timing_option_rejected(self):
        self.put(self.rtr, self.rtr.read_text().replace('Tcl Command : report_timing', 'Tcl Command : report_timing -max_path 8 -max_path 1'))
        self.rejected('Duplicate report_timing option')

    def test_invalid_timing_option_value_rejected(self):
        for suffix in ('-nworst 0', '-max_path -1', '-nworst', '-report_exception FALSE'):
            with self.subTest(suffix=suffix):
                with self.assertRaises(gate.ReleaseError):
                    gate.timing_metadata('| Timing Models: Pre-silicon\n| Tcl Command: report_timing '+suffix+'\n')

    def test_presilicon_does_not_bypass_corner_coverage(self):
        text = self.rtr.read_text().replace('Timing Models : Production', 'Timing Models : Pre-silicon')
        self.put(self.rtr, text.replace('Hold Summary(Fast Corner):', 'Hold Summary(Unknown Corner):'))
        self.rejected('Missing table: Hold Summary')

    def test_helper_scripts_and_raw_files_are_recorded(self):
        result = gate.audit(self.args, self.root)
        self.assertEqual(len(result['audit_scripts']), 3)
        self.assertEqual(set(result['physical']['results']), {'pdm', 'tx'})
        self.assertIn('timing_database', result['evidence'])
        self.assertIn('fast_sdf', result['evidence'])

    def test_stale_sdf_rejected(self):
        path = self.build/'clock_audit/slow_sta.sdf'
        os.utime(path, (self.start.timestamp()-5, self.start.timestamp()-5))
        self.rejected('Stale or post-build slow_sdf')

    def test_missing_raw_xml_rejected(self):
        (self.rtr.parent/'rtr.db').unlink()
        self.rejected('existing artifact')

    def test_helper_changed_during_audit(self):
        original = self.helper_result
        def change(script, arguments, output):
            result = original(script, arguments, output)
            if script.name == 'check_tx_source.py':
                (self.root/'fpga/scripts/check_pdm_budget.py').write_text('# concurrent edit\n')
            return result
        self.helper_mock.side_effect = change
        self.rejected('Executed audit script changed')

    def test_raw_evidence_changed_during_audit(self):
        original = self.helper_result
        def change(script, arguments, output):
            result = original(script, arguments, output)
            if script.name == 'check_tx_source.py':
                (self.build/'clock_audit/slow_sta.sdf').write_text('Changed raw SDF')
            return result
        self.helper_mock.side_effect = change
        self.rejected('Artifact changed|helper evidence/hash set mismatch')

    def test_helper_wrong_evidence_hash(self):
        original = self.helper_result
        def change(script, arguments, output):
            result = original(script, arguments, output)
            if script.name == 'check_pdm_budget.py':
                result['evidence']['slow_sdf']['sha256'] = '0'*64
            return result
        self.helper_mock.side_effect = change
        self.rejected('used different raw evidence')

    def test_unproved_duty_never_authorizes_release(self):
        original = self.helper_result
        def change(script, arguments, output):
            result = original(script, arguments, output)
            if script.name == 'check_tx_source.py':
                result['duty'] = {'status': 'FAIL'}
            return result
        self.helper_mock.side_effect = change
        self.rejected('nominal duty cycle fails')

    def test_report_max_skew_option(self):
        data = gate.timing_metadata('| Timing Models: Pre-silicon\n| Tcl Command: report_timing -report_max_skew\n')
        self.assertTrue(data['report_options']['-report_max_skew'])

    def test_unknown_xml_check_rejected(self):
        path = self.rtr.parent/'rtr.db'
        self.put(path, path.read_text().replace('<data>no_clock</data><data>0</data>', '<data>no_clock</data><data>1</data>'))
        self.rejected('Unreviewed XML check_timing issue')

    def test_xml_cannot_describe_different_routed_build(self):
        path = self.rtr.parent/'rtr.db'
        self.put(path, path.read_text().replace('<data>0.15</data>', '<data>0.16</data>', 1))
        self.rejected('XML and RTR timing summaries differ')

    def test_xml_clock_mismatch_rejected(self):
        path = self.rtr.parent/'rtr.db'
        self.put(path, path.read_text().replace('<data>8.0</data>', '<data>9.0</data>', 1))
        self.rejected('XML and RTR clock tables differ')

    def detailed_issue(self, name, leaves, nested=False):
        path = self.rtr.parent/'rtr.db'
        doc = gate.ET.parse(path)
        table = doc.getroot().find("./table[@id='check_timing_summary']")
        row = next(r for r in table.findall('./row') if r.find('./data').text == name)
        row.findall('./data')[1].text = str(len(leaves))
        container = gate.ET.SubElement(row, 'table_container')
        detail = gate.ET.SubElement(container, 'table')
        if nested:
            detail = gate.ET.SubElement(detail, 'row')
            gate.ET.SubElement(detail, 'data').text = 'Issue count summary'
        for leaf in leaves:
            gate.ET.SubElement(gate.ET.SubElement(detail, 'row'), 'data').text = leaf
        self.put(path, gate.ET.tostring(doc.getroot(), encoding='unicode'))
        return path

    def test_actual_virtual_reference_notice_needs_constraints_and_coverage(self):
        path = self.detailed_issue('virtual_clock', [
            'Virtual clock rx_data_launch is never referenced in any input or output delay assignment.',
            'Virtual clock tx_pad_ref is never referenced in any input or output delay assignment.'])
        fdc = self.fdc+'\n'.join([
            'create_clock -name rx_data_launch -period 8.000 -waveform {2.000 6.000}',
            'create_clock -name tx_pad_ref -period 8.000',
            'set_input_delay -clock rx_data_launch -min -1.000 [get_ports {PHY0_RXD[*] PHY0_RXCTRL}]',
            'set_input_delay -clock rx_data_launch -max 1.000 [get_ports {PHY0_RXD[*] PHY0_RXCTRL}]',
            'set_output_delay -clock tx_pad_ref -min 0.000 [get_ports {PHY0_TXD[*] PHY0_TXC PHY0_TXCTRL}]',
            'set_output_delay -clock tx_pad_ref -max 0.000 [get_ports {PHY0_TXD[*] PHY0_TXC PHY0_TXCTRL}]'])+'\n'
        timing = gate.check_timing(self.rtr.read_text(), (self.rtr.parent/'run.log').read_text())
        result = gate.check_database(path, timing, fdc)
        self.assertEqual(len(result['reviewed_referenced_virtual_clocks']), 2)
        with self.assertRaisesRegex(gate.ReleaseError, 'lacks min/max'):
            gate.check_database(path, timing, fdc.replace('-clock rx_data_launch -max', '-clock other_clock -max'))
        with self.assertRaisesRegex(gate.ReleaseError, 'virtual clock declaration'):
            gate.check_database(path, timing, fdc.replace('-period 8.000 -waveform', '-period 8.000 [get_ports bad] -waveform'))
        doc = gate.ET.parse(path)
        row = next(r for r in doc.getroot().find("./table[@id='report_timing_slow_setup']").findall('row')
                   if r.find('./data').text == 'rx_data_launch')
        row.findall('./data')[-1].text = '4'
        self.put(path, gate.ET.tostring(doc.getroot(), encoding='unicode'))
        pair = next(r for r in timing['summaries']['Setup/Slow'] if r['clocks'] == ['rx_data_launch', 'rx125'])
        pair['total_endpoints'] = 4
        with self.assertRaisesRegex(gate.ReleaseError, 'actual I/O timing coverage'):
            gate.check_database(path, timing, fdc)

    def test_clock_outputs_without_io_delay_need_real_clock_and_physical_bound(self):
        path = self.detailed_issue('no_output_delay', ['mic_clk[0]', 'PHY0_MDC'], nested=True)
        fdc = self.fdc+'set_max_delay 7.500 -datapath_only -to [get_ports PHY0_MDC]\n'
        timing = gate.check_timing(self.rtr.read_text(), (self.rtr.parent/'run.log').read_text())
        result = gate.check_database(path, timing, fdc)
        self.assertEqual(set(result['reviewed_generated_clock_outputs']), {'mic_clk[0]', 'PHY0_MDC'})
        with self.assertRaisesRegex(gate.ReleaseError, 'physical delay bound'):
            gate.check_database(path, timing, fdc.replace('7.500', '99.000'))
        self.put(path, path.read_text().replace('<data>PHY0_MDC</data>', '<data>PHY0_TXD[0]</data>'))
        with self.assertRaisesRegex(gate.ReleaseError, 'Unreviewed XML output'):
            gate.check_database(path, timing, fdc)

    def test_only_exact_clock_control_reset_notices_are_reviewed(self):
        path = self.root/'fpga/constraints/timing.fdc'
        fdc = '# Header\n'+gate.RESET_CONTROL_EXCEPTION+'\n'
        notices = [f"C: STA-3006: Object '{p}' is not a valid endpoint." for p in sorted(gate.RESET_CONTROL_ENDPOINTS)]
        notices.append(f'C: STA-3015: [{path}(line number: 2)] No path found for -from -through -to path specification.')
        log = '\n'.join(notices)+'\n'
        self.assertEqual(len(gate.review_timing_diagnostics(log, fdc, path)), 5)
        for invalid in (log.replace(sorted(gate.RESET_CONTROL_ENDPOINTS)[0], 'core/functional_register/C'),
                        log.replace('line number: 2', 'line number: 1'),
                        log.replace('C: STA-3006', 'E: STA-3006'),
                        log+'C: STA-3006: Object missing is not a valid endpoint.\n'):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(gate.ReleaseError, 'Timing diagnostics require review'):
                    gate.review_timing_diagnostics(invalid, fdc, path)
        with self.assertRaisesRegex(gate.ReleaseError, 'Timing diagnostics require review'):
            gate.review_timing_diagnostics(log, fdc.replace('RST_N', 'WRONG'), path)

    def test_only_exact_pll_lock_notices_are_reviewed(self):
        path=self.root/'fpga/constraints/timing.fdc'
        fdc=gate.RESET_CONTROL_EXCEPTION+'\n'+gate.LOCK_STATUS_EXCEPTION+'\n'
        notices=[f"C: STA-3006: Object '{p}' is not a valid endpoint." for p in sorted(gate.RESET_CONTROL_ENDPOINTS)]
        notices += [f"C: STA-3005: Object '{p}' is not a valid startpoint." for p in sorted(gate.LOCK_STATUS_STARTPOINTS)]
        notices += [f'C: STA-3015: [{path}(line number: {i})] No path found for -from -through -to path specification.' for i in (1,2)]
        log='\n'.join(notices)+'\n'
        self.assertEqual(len(gate.review_timing_diagnostics(log,fdc,path)),9)
        with self.assertRaises(gate.ReleaseError):
            gate.review_timing_diagnostics(log.replace(sorted(gate.LOCK_STATUS_STARTPOINTS)[0],'core/data_register/Q'),fdc,path)
        with self.assertRaises(gate.ReleaseError):
            gate.review_timing_diagnostics(log,fdc.replace('/LOCK','/CLKOUT0'),path)

    def test_all_uart_cdc_pairs_need_physical_coverage(self):
        original=self.rtr.read_text()
        for launch,capture in gate.UART_CDC_PAIRS:
            with self.subTest(pair=(launch,capture)):
                self.put(self.rtr,original.replace(f'{launch} {capture} 0.150 0.000 0 7\n',''))
                self.rejected('missing bounded UART CDC paths')

    def test_uart_reference_functional_paths_required(self):
        original=self.rtr.read_text()
        self.put(self.rtr,original.replace('sys27 sys27 0.150 0.000 0 7\n',''))
        self.rejected('missing sys27 functional paths')

    def test_unexpandable_uart_pair_requires_both_bounds(self):
        path=self.rtr.parent/'rtr.db'
        doc=gate.ET.parse(path)
        table=doc.getroot().find("./table[@id='check_timing_summary']")
        row=next(r for r in table.findall('./row') if r.find('./data').text=='unexpandable_clocks')
        row.findall('./data')[1].text='1'
        detail=gate.ET.SubElement(gate.ET.SubElement(gate.ET.SubElement(row,'table_container'),'table'),'row')
        leaf=gate.ET.SubElement(detail,'data')
        leaf.text='Can not find common multiples between the source clock audio122 and destination clock sys27  within 1000 cycles.'
        doc.write(path)
        fdc=''.join(f'set_max_delay 7.500 -datapath_only -from [get_clocks {a}] -to [get_clocks {b}]\nset_false_path -hold -from [get_clocks {a}] -to [get_clocks {b}]\n' for a,b in (('audio122','sys27'),('sys27','audio122')))
        timing=gate.check_timing(self.rtr.read_text(),'Action report_timing: done')
        self.assertEqual(gate.check_database(path,timing,fdc)['check_timing']['unexpandable_clocks'],1)
        with self.assertRaisesRegex(gate.ReleaseError,'Missing UART CDC physical bound'):
            gate.check_database(path,timing,fdc.replace('7.500','8.000'))
        leaf.text=leaf.text.replace('audio122','eth125')
        doc.write(path)
        with self.assertRaisesRegex(gate.ReleaseError,'Unreviewed unexpandable clock pair'):
            gate.check_database(path,timing,fdc)

    def test_pll_validation_requires_current_sources_and_correct_pfd(self):
        data=json.loads((self.build/'pll_validation.json').read_text())
        gate.check_pll_validation(data,self.root)
        data['validated_instances'][0]['pfd_mhz']=125.0
        with self.assertRaises(gate.ReleaseError):gate.check_pll_validation(data,self.root)
        data=json.loads((self.build/'pll_validation.json').read_text())
        data['rtl_sha256']='0'*64
        with self.assertRaises(gate.ReleaseError):gate.check_pll_validation(data,self.root)

    def test_pdm_budget_constants_cannot_drift(self):
        timing = {'clocks': gate.parse_clock_summary(self.rtr.read_text())}
        contract = gate.check_pdm_contract(self.root, self.fdc, timing)
        self.assertEqual(contract['sample_tick'], 19)
        self.assertEqual(contract['effective_sample_interval_cycles'], 17)
        capture = (self.root/'rtl/pdm_capture.sv').read_text()
        self.write('rtl/pdm_capture.sv', capture.replace('SAMPLE_TICK=19', 'SAMPLE_TICK=18'))
        with self.assertRaisesRegex(gate.ReleaseError, 'sample interval constant changed'):
            gate.check_pdm_contract(self.root, self.fdc, timing)
        self.write('rtl/pdm_capture.sv', capture)
        for original, replacement in (('5.000', '6.000'), ('4.000', '5.000')):
            with self.subTest(replacement=replacement):
                with self.assertRaisesRegex(gate.ReleaseError, 'PDM budget requires'):
                    gate.check_pdm_contract(self.root, self.fdc.replace(original, replacement), timing)
        self.write('rtl/mems_array_top.sv', 'pdm_capture #(.SAMPLE_TICK(17)) capture(.clk(clk));')
        with self.assertRaisesRegex(gate.ReleaseError, 'overrides'):
            gate.check_pdm_contract(self.root, self.fdc, timing)

    def test_only_actual_zero_reference_equality_allowed(self):
        path = self.rtr.parent/'rtr.db'
        doc = gate.ET.parse(path)
        table = doc.getroot().find("./table[@id='check_timing_summary']")
        row = next(row for row in table.findall('./row') if row.find('./data').text == 'io_min_max_delay_consistency')
        row.findall('./data')[1].text = '1'
        container = gate.ET.SubElement(row, 'table_container')
        detail = gate.ET.SubElement(gate.ET.SubElement(container, 'table'), 'row')
        leaf = gate.ET.SubElement(gate.ET.SubElement(detail, 'row'), 'data')
        leaf.text = 'pdm_data[0]: Min rise delay is equal to max rise delay.'
        doc.write(path)
        timing = gate.check_timing(self.rtr.read_text(), 'Action report_timing: done')
        fdc = self.fdc+'set_input_delay -min 0 -clock audio122 [get_ports {pdm_data[*]}]\n'
        self.assertEqual(gate.check_database(path, timing, fdc)['check_timing']['io_min_max_delay_consistency'], 1)
        with self.assertRaisesRegex(gate.ReleaseError, 'Unreviewed XML I/O bound issue'):
            gate.check_database(path, timing, self.fdc)

    def test_nested_generated_clock_xml(self):
        path = self.rtr.parent/'rtr.db'
        doc = gate.ET.parse(path)
        table = doc.getroot().find("./table[@id='report_timing_clock_summary']")
        rows = {row.find('./data').text: row for row in table.findall('./row')}
        for child, parent in gate.CLOCK_PARENTS.items():
            table.remove(rows[child])
            rows[parent].append(rows[child])
        doc.write(path)
        os.utime(path, (self.now.timestamp(), self.now.timestamp()))
        self.assertEqual(gate.audit(self.args, self.root)['status'], 'PASS')

    def test_shaped_clock_parent_is_required(self):
        self.put(self.rtr, self.rtr.read_text().replace('Generated (eth250)', 'Generated (ref125)'))
        self.rejected('Clock parent mismatch: eth125')

    def test_engineering_scope_retains_sensitivity_failure(self):
        result = gate.audit(self.args, self.root)
        self.assertEqual(result['scope'], 'engineering_board_bringup')
        self.assertFalse(result['qualification']['unconditional_board_qualification'])
        self.assertEqual(result['qualification']['sensitivity_status'], 'FAIL')
        original = result['physical']['results']['tx']['duty']['conservative_jitter_sensitivity']
        self.assertEqual(original['status'], 'FAIL')
        self.assertTrue(all(c['pass'] is False for c in original['cases']))

    def test_unknown_sensitivity_scope_is_rejected(self):
        original = self.helper_result
        def change(script, arguments, output):
            result = original(script, arguments, output)
            if script.name == 'check_tx_source.py':
                result['duty'].pop('conservative_jitter_sensitivity')
            return result
        self.helper_mock.side_effect = change
        self.rejected('original TX jitter sensitivity')

    def test_native_completions_required_in_addition_to_markers(self):
        path = self.build/'build.log'
        self.put(path, path.read_text().replace('Executing : pnr successfully.\n', ''))
        self.rejected('native successful stage completions')

    def test_tcl_preparse_markers_cannot_claim_completion(self):
        text = ''.join(f'MEMS_PANGO_{s.upper()}_COMPLETE\n' for s in gate.STAGES)
        text += ''.join(f'Executing : {s} successfully.\n' for s in gate.STAGES)
        self.put(self.build/'build.log', text)
        self.rejected('marker precedes actual PDS')

    def test_repeated_native_stage_is_rejected(self):
        path = self.build/'build.log'
        self.put(path, path.read_text()+'Executing : pnr successfully.\n')
        self.rejected('native successful stage completions')

    def test_changed_routed_database_rejected(self):
        self.put(self.routed, b'A different route')
        self.rejected('Routed database hash differs')

    def test_other_database_used_for_bitstream_rejected(self):
        path = self.build/'build.log'
        self.put(path, path.read_text().replace(self.bit_command(), self.bit_command().replace('_pnr.adf', '_old.adf')))
        self.rejected('does not use the audited routed database')

    def test_missing_corner_process_record_rejected(self):
        self.manifest['flow_evidence'].pop(1)
        self.save_json()
        self.rejected('completed PDS process evidence')

    def test_changed_executed_flow_script_rejected(self):
        self.put(self.build/'export_slow.tcl', self.export_command('fast'))
        self.rejected('script path/hash mismatch')

    def staged_floorplan_fixture(self):
        # Synthetic stage evidence exercises binding checks, not PDS timing.
        template = SCRIPT.parents[1]/'constraints/frontend_floorplan.pcf'
        self.write('fpga/constraints/frontend_floorplan.pcf', template.read_text())
        self.mapped = self.build/'device_map'/f'{gate.TOP}_map.adf'
        self.base_pcf = self.build/'device_map'/f'{gate.TOP}_base.pcf'
        self.route_pcf = self.build/'device_map'/f'{gate.TOP}.pcf'
        self.put(self.mapped, b'FIXTURE_NOT_A_MAPPED_DATABASE')
        base = ''.join('def_port {'+p+'} LOC='+v['LOC']+' VCCIO='+v['VCCIO']+' IOSTANDARD='+v['STANDARD']+'\n'
                       for p,v in gate.pins_from_fdc(self.pin_fdc).items())
        self.put(self.base_pcf, base)
        source = self.root/'fpga/constraints/frontend_floorplan.pcf'
        self.put(self.route_pcf, self.base_pcf.read_bytes()+b'\n'+source.read_bytes())
        self.manifest['postmap_constraints'] = {k:gate.sha(p) for k,p in
            [('mapped_db_sha256',self.mapped),('base_pcf_sha256',self.base_pcf),
             ('route_pcf_sha256',self.route_pcf),('template_sha256',source)]}
        self.put(self.build/'build.tcl', '\n'.join(gate.STAGES[:3])+'\n')
        first = self.manifest['flow_evidence'][0]
        first.update(stages=list(gate.STAGES[:3]), script_sha256=gate.sha(self.build/'build.tcl'))
        self.route_command = 'pnr -force_to_run -input_db_file {'+self.mapped.as_posix()+'}'
        route = 'add_constraint {'+self.route_pcf.as_posix()+'}\n'+self.route_command+'\nreport_timing\n'
        self.put(self.build/'route.tcl', route)
        self.manifest['flow_evidence'].insert(1,dict(project='MEMS_Array_route',stages=['pnr','report_timing'],
            script=(self.build/'route.tcl').relative_to(self.root).as_posix(),script_sha256=gate.sha(self.build/'route.tcl'),
            exit_code=0,completed_at=self.now.isoformat()))
        text=self.build_log(gate.STAGES).replace('Executing : pnr successfully.', 'Executing : '+self.route_command+' successfully.')
        text+=''.join('Executing : '+line+' successfully\n' for line in gate.commands(source.read_text()))
        self.put(self.build/'build.log',text)
        self.manifest['source_sha256']=gate.current_build_sources(self.root)
        self.save_json()

    def test_staged_floorplan_release(self):
        self.staged_floorplan_fixture()
        result=gate.audit(self.args,self.root)
        self.assertTrue(result['release_authorized'])
        self.assertEqual(len(result['flow_evidence']),5)

    def test_staged_changed_map_rejected(self):
        self.staged_floorplan_fixture()
        self.put(self.mapped,b'Another synthesis result')
        self.rejected('Postmap input hash mismatch: mapped_db')

    def test_staged_pre_bit_is_not_a_release(self):
        self.staged_floorplan_fixture()
        self.args.pre_bit=True
        self.args.bitstream=None
        self.manifest.update(status='RUNNING')
        for key in ('sources_unchanged','exit_code','completed_at'):
            self.manifest.pop(key)
        self.manifest['flow_evidence'].pop()
        path=self.build/'build.log'
        self.put(path,'\n'.join(line for line in path.read_text().splitlines()
                               if not line.startswith(('Executing : gen_bit_stream','MEMS_PANGO_GEN_BIT_STREAM')))+'\n')
        self.save_json()
        self.assertFalse(gate.audit(self.args,self.root)['release_authorized'])

    def test_staged_rehashed_wrong_port_rejected(self):
        self.staged_floorplan_fixture()
        source=self.root/'fpga/constraints/frontend_floorplan.pcf'
        self.put(self.base_pcf,self.base_pcf.read_text().replace('LOC=A1 ', 'LOC=Z999 ',1))
        self.put(self.route_pcf,self.base_pcf.read_bytes()+b'\n'+source.read_bytes())
        self.manifest['postmap_constraints'].update(base_pcf_sha256=gate.sha(self.base_pcf),route_pcf_sha256=gate.sha(self.route_pcf))
        self.save_json()
        self.rejected('physical PCF pin mismatch')

    def test_staged_pcf_injection_rejected_even_if_rehashed(self):
        self.staged_floorplan_fixture()
        self.put(self.route_pcf,self.route_pcf.read_bytes()+b'\nset_false_path -from [all_clocks]\n')
        self.manifest['postmap_constraints']['route_pcf_sha256']=gate.sha(self.route_pcf)
        self.save_json()
        self.rejected('exact generated base')

    def test_staged_omitted_macro_acceptance_rejected(self):
        self.staged_floorplan_fixture()
        path=self.build/'build.log'
        lines=path.read_text().splitlines()
        index=next(i for i,line in enumerate(lines) if line.startswith('Executing : def_inst_site'))
        del lines[index]
        self.put(path,'\n'.join(lines)+'\n')
        self.rejected('not actually accepted')

    def test_staged_wrong_map_command_rejected(self):
        self.staged_floorplan_fixture()
        path=self.build/'build.log'
        self.put(path,path.read_text().replace(self.route_command,self.route_command.replace('_map.adf','_other.adf')))
        self.rejected('audited mapped database')

    def test_staged_unselected_physical_constraints_rejected(self):
        self.staged_floorplan_fixture()
        path=self.build/'route.tcl'
        self.put(path,self.route_command+'\nreport_timing\n')
        self.manifest['flow_evidence'][1]['script_sha256']=gate.sha(path)
        self.save_json()
        self.rejected('select the audited physical PCF')

    def placed_iteration_fixture(self):
        self.staged_floorplan_fixture()
        self.placed = self.build/'place_route'/f'{gate.TOP}_placed_input.adf'
        self.put(self.placed,b'FIXTURE_NOT_A_PLACED_DATABASE')
        self.manifest['postplace_link']={'placed_db_sha256':gate.sha(self.placed)}
        self.place_command='pnr -place_only -input_db_file {'+self.mapped.as_posix()+'}'
        place=self.build/'place.tcl'
        self.put(place,'add_constraint {'+self.route_pcf.as_posix()+'}\n'+self.place_command+'\n')
        self.manifest['flow_evidence'].insert(1,dict(project='MEMS_Array_place',stages=['place'],
            script=place.relative_to(self.root).as_posix(),script_sha256=gate.sha(place),
            exit_code=0,completed_at=self.now.isoformat()))
        old=self.route_command
        self.route_command=old.replace(self.mapped.as_posix(),self.placed.as_posix())
        route=self.build/'route.tcl'
        self.put(route,route.read_text().replace(old,self.route_command))
        self.manifest['flow_evidence'][2]['script_sha256']=gate.sha(route)
        log=self.build/'build.log'
        text=log.read_text().replace('Executing : '+old+' successfully.',
            'Executing : '+self.place_command+' successfully.\nExecuting : '+self.route_command+' successfully.')
        self.put(log,text.replace('MEMS_PANGO_PNR_COMPLETE','MEMS_PANGO_PLACE_COMPLETE\nMEMS_PANGO_PNR_COMPLETE'))
        self.save_json()

    def test_placed_iteration_release(self):
        self.placed_iteration_fixture()
        result=gate.audit(self.args,self.root)
        self.assertTrue(result['release_authorized'])
        self.assertEqual(len(result['flow_evidence']),6)
        self.assertEqual([s['stage'] for s in result['stage_completions']],
                         ['compile','synthesize','dev_map','place','pnr','report_timing','gen_bit_stream'])

    def test_changed_placement_rejected(self):
        self.placed_iteration_fixture()
        self.put(self.placed,b'Different placement')
        self.rejected('Placement input hash mismatch')

    def test_placed_iteration_pre_bit_not_release(self):
        self.placed_iteration_fixture()
        self.args.pre_bit=True
        self.args.bitstream=None
        self.manifest.update(status='RUNNING')
        for key in ('sources_unchanged','exit_code','completed_at'):
            self.manifest.pop(key)
        self.manifest['flow_evidence'].pop()
        log=self.build/'build.log'
        self.put(log,'\n'.join(line for line in log.read_text().splitlines()
            if not line.startswith(('Executing : gen_bit_stream','MEMS_PANGO_GEN_BIT_STREAM')))+'\n')
        self.save_json()
        self.assertFalse(gate.audit(self.args,self.root)['release_authorized'])

    def test_missing_placement_process_rejected(self):
        self.placed_iteration_fixture()
        self.manifest['flow_evidence'].pop(1)
        self.save_json()
        self.rejected('completed PDS process evidence')

    def test_placement_without_native_completion_rejected(self):
        self.placed_iteration_fixture()
        log=self.build/'build.log'
        self.put(log,log.read_text().replace('Executing : '+self.place_command+' successfully.\n',''))
        self.rejected('native successful stage completions')

    def test_place_only_cannot_prove_routing(self):
        self.placed_iteration_fixture()
        log=self.build/'build.log'
        self.put(log,log.read_text().replace(self.route_command,self.route_command.replace('pnr ','pnr -place_only ')))
        self.rejected('native successful stage completions')

    def test_placement_from_other_map_rejected(self):
        self.placed_iteration_fixture()
        log=self.build/'build.log'
        self.put(log,log.read_text().replace(self.place_command,self.place_command.replace('_map.adf','_old.adf')))
        self.rejected('audited mapped database')

    def test_route_from_other_placement_rejected(self):
        self.placed_iteration_fixture()
        log=self.build/'build.log'
        self.put(log,log.read_text().replace(self.route_command,self.route_command.replace('_placed_input.adf','_old.adf')))
        self.rejected('audited placed database')

    def test_placement_without_selected_pcf_rejected(self):
        self.placed_iteration_fixture()
        place=self.build/'place.tcl'
        self.put(place,self.place_command+'\n')
        self.manifest['flow_evidence'][1]['script_sha256']=gate.sha(place)
        self.save_json()
        self.rejected('select the audited physical PCF')

    def test_extra_placement_without_manifest_rejected(self):
        self.placed_iteration_fixture()
        del self.manifest['postplace_link']
        self.save_json()
        self.rejected('required stages completed once in order')

    def checkpoint_fixture(self):
        self.placed_iteration_fixture()
        self.write('fpga/scripts/finalize_route_checkpoint.py', '# Fixture finalizer, not hardware evidence\n')
        origin = dict(self.manifest, status='FAIL', flow_evidence=self.manifest['flow_evidence'][:2])
        self.origin_manifest = self.build/'checkpoint_selection/source_manifest.json'
        self.optimizer_log = self.build/'checkpoint_selection/optimizer.log'
        self.put(self.origin_manifest, json.dumps(origin))
        prefix = ''.join('Executing : '+s+' successfully.\nMEMS_PANGO_'+s.upper()+'_COMPLETE\n' for s in gate.STAGES[:3])
        prefix += 'Executing : '+self.place_command+' successfully.\nMEMS_PANGO_PLACE_COMPLETE\n'
        prefix += ''.join('Executing : '+line+' successfully\n' for line in gate.commands((self.root/'fpga/constraints/frontend_floorplan.pcf').read_text()))
        prefix += 'Executing : '+self.route_command+'\nI: Current iteration time: 1\n'
        prefix += "No hold violation.\nTotal net: 10, route succeed net: 10\nDesign '"+gate.TOP+"' has been routed successfully.\nSaving design to DB.\nAction pnr: Real time elapsed is 1m\nAction pnr: Peak memory pool usage is 10 MB\n"
        self.put(self.optimizer_log, prefix+'I: Current iteration time: 2\nE: Optional optimizer cancelled\n')
        self.checkpoint = self.build/'place_route/route_constraint_ite_1'/f'{gate.TOP}_pnr.adf'
        self.put(self.checkpoint, self.routed.read_bytes())
        report = self.checkpoint.with_name(gate.TOP+'.rtr')
        self.put(report, self.timing_report())
        self.manifest['route_checkpoint_selection'] = dict(iteration=1,
            source_manifest_sha256=gate.sha(self.origin_manifest), optimizer_log_sha256=gate.sha(self.optimizer_log),
            routed_db_sha256=gate.sha(self.routed), timing_report_sha256=gate.sha(report),
            route_script_sha256=gate.sha(self.build/'route.tcl'),
            finalizer_sha256=gate.sha(self.root/'fpga/scripts/finalize_route_checkpoint.py'))
        self.timing_command = 'report_timing -input_db_file {'+self.routed.as_posix()+'}'
        self.put(self.rtr,self.rtr.read_text().replace('| Tcl Command : report_timing', '| Tcl Command : '+self.timing_command+' -force_to_run'))
        timing_script = self.build/'finalize_timing.tcl'
        self.put(timing_script, self.timing_command+'\n')
        self.manifest['flow_evidence'][2].update(project='MEMS_Array_route_selection',stages=['pnr'],execution_kind='completed_checkpoint_selection')
        self.manifest['flow_evidence'][2].pop('exit_code')
        self.manifest['flow_evidence'].insert(3,dict(project='MEMS_Array_timing',stages=['report_timing'],exit_code=0,
            script=timing_script.relative_to(self.root).as_posix(),script_sha256=gate.sha(timing_script),completed_at=self.now.isoformat()))
        tail = 'MEMS_PANGO_PNR_COMPLETE\nExecuting : '+self.timing_command+' successfully.\nMEMS_PANGO_REPORT_TIMING_COMPLETE\n'
        tail += ''.join('Executing : '+self.export_command(c)+' successfully.\n' for c in ('slow','fast'))
        tail += 'Executing : '+self.bit_command()+' successfully.\nMEMS_PANGO_GEN_BIT_STREAM_COMPLETE\n'
        self.put(self.build/'build.log',prefix+tail)
        self.save_json()

    def alter_checkpoint_transcript(self, before, after):
        for path in (self.optimizer_log,self.build/'build.log'):
            self.put(path,path.read_text().replace(before,after))
        self.manifest['route_checkpoint_selection']['optimizer_log_sha256']=gate.sha(self.optimizer_log)
        self.save_json()

    def test_completed_checkpoint_release(self):
        self.checkpoint_fixture()
        result=gate.audit(self.args,self.root)
        self.assertTrue(result['release_authorized'])
        self.assertEqual(len(result['flow_evidence']),7)
        self.assertIn('completed PNR iteration 1',result['stage_completions'][4]['successful_command'])

    def test_checkpoint_is_not_optimizer_exit_success(self):
        self.checkpoint_fixture()
        self.manifest['flow_evidence'][2]['exit_code']=0
        self.save_json()
        self.rejected('project/stage/exit evidence mismatch')

    def test_checkpoint_unrouted_nets_rejected(self):
        self.checkpoint_fixture()
        self.alter_checkpoint_transcript('route succeed net: 10','route succeed net: 9')
        self.rejected('not fully routed')

    def test_checkpoint_without_native_completion_rejected(self):
        self.checkpoint_fixture()
        self.alter_checkpoint_transcript("Design '"+gate.TOP+"' has been routed successfully.\n",'')
        self.rejected('Missing native completed PNR')

    def test_checkpoint_with_error_before_completion_rejected(self):
        self.checkpoint_fixture()
        self.alter_checkpoint_transcript('Saving design to DB.','E: Routing error\nSaving design to DB.')
        self.rejected('build log contains errors')

    def test_checkpoint_changed_origin_hash_rejected(self):
        self.checkpoint_fixture()
        self.put(self.optimizer_log,self.optimizer_log.read_text()+'Changed archive\n')
        self.rejected('origin evidence hash mismatch')

    def test_checkpoint_changed_log_prefix_rejected(self):
        self.checkpoint_fixture()
        p=self.build/'build.log';self.put(p,'Edited prefix\n'+p.read_text())
        self.rejected('not the original completed route prefix')

    def test_checkpoint_other_route_database_rejected(self):
        self.checkpoint_fixture()
        self.put(self.routed,b'OTHER_ROUTED_RESULT')
        self.rejected('not the completed checkpoint')

    def test_checkpoint_from_other_sources_rejected(self):
        self.checkpoint_fixture()
        origin=json.loads(self.origin_manifest.read_text());origin['source_sha256']={}
        self.put(self.origin_manifest,json.dumps(origin))
        self.manifest['route_checkpoint_selection']['source_manifest_sha256']=gate.sha(self.origin_manifest)
        self.save_json()
        self.rejected('not from this full unchanged build')

    def test_checkpoint_original_timing_failure_rejected(self):
        self.checkpoint_fixture()
        report=self.checkpoint.with_name(gate.TOP+'.rtr')
        self.put(report,report.read_text().replace('All Constraints Met.','Constraints NOT Met.'))
        self.manifest['route_checkpoint_selection']['timing_report_sha256']=gate.sha(report)
        self.save_json()
        self.rejected('did not meet its original timing')

    def test_checkpoint_wrong_fresh_report_database_rejected(self):
        self.checkpoint_fixture()
        wrong=self.timing_command.replace('_pnr.adf','_other.adf')
        p=self.build/'finalize_timing.tcl';self.put(p,wrong+'\n')
        self.manifest['flow_evidence'][3]['script_sha256']=gate.sha(p)
        p=self.build/'build.log';self.put(p,p.read_text().replace(self.timing_command,wrong))
        self.save_json()
        self.rejected('does not use the audited routed database')

    def test_checkpoint_changed_finalizer_rejected(self):
        self.checkpoint_fixture()
        self.write('fpga/scripts/finalize_route_checkpoint.py','# changed\n')
        self.rejected('finalizer changed')

    def test_checkpoint_timing_header_wrong_database_rejected(self):
        self.checkpoint_fixture()
        self.put(self.rtr,self.rtr.read_text().replace('_pnr.adf','_wrong.adf'))
        self.rejected('RTR header does not select')

    def test_checkpoint_filtered_timing_still_rejected(self):
        self.checkpoint_fixture()
        self.put(self.rtr,self.rtr.read_text().replace(' -force_to_run',' -force_to_run -from foo'))
        self.rejected('Unsupported report_timing option')

    def checkpoint_resume_fixture(self):
        self.checkpoint_fixture()
        self.failed_checkpoint = self.build/'checkpoint_selection/failed_audit.json'
        previous = dict(self.manifest,status='FAIL',flow_evidence=self.manifest['flow_evidence'][:6])
        self.put(self.failed_checkpoint,json.dumps(previous))
        self.manifest['checkpoint_resume_records']=[dict(manifest=self.failed_checkpoint.relative_to(self.build).as_posix(),sha256=gate.sha(self.failed_checkpoint))]
        self.save_json()

    def test_checkpoint_resume_keeps_completed_evidence(self):
        self.checkpoint_resume_fixture()
        self.assertTrue(gate.audit(self.args,self.root)['release_authorized'])

    def test_checkpoint_resume_archive_tamper_rejected(self):
        self.checkpoint_resume_fixture()
        self.put(self.failed_checkpoint,self.failed_checkpoint.read_text()+' ')
        self.rejected('resume manifest hash mismatch')

    def test_checkpoint_resume_other_route_rejected(self):
        self.checkpoint_resume_fixture()
        previous=json.loads(self.failed_checkpoint.read_text());previous['routed_db_sha256']='different'
        self.put(self.failed_checkpoint,json.dumps(previous))
        self.manifest['checkpoint_resume_records'][0]['sha256']=gate.sha(self.failed_checkpoint)
        self.save_json()
        self.rejected('resume changed completed build evidence')


class HelperProcessTest(unittest.TestCase):
    def test_exit_status_and_fresh_output_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script, output = root/'mock.py', root/'result.json'
            script.write_text('import json,sys\nfrom pathlib import Path\nPath(sys.argv[-1]).write_text(json.dumps({"status":"PASS"}))\n')
            self.assertEqual(gate.run_helper(script, [], output)['status'], 'PASS')
            with self.assertRaisesRegex(gate.ReleaseError, 'newly generated'):
                gate.run_helper(script, [], output)
            output.unlink()
            script.write_text(script.read_text()+'raise SystemExit(1)\n')
            with self.assertRaisesRegex(gate.ReleaseError, 'rejected physical evidence'):
                gate.run_helper(script, [], output)


if __name__ == '__main__':
    unittest.main()
