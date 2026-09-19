"""Reproducible Pango build in fpga/build; the GUI project is never overwritten."""
from pathlib import Path
import argparse, hashlib, json, os, re, shutil, subprocess, sys
from datetime import datetime
from check_pll_parameters import validate as validate_plls

ROOT = Path(__file__).resolve().parents[2]
STAGES = ['compile', 'synthesize', 'dev_map', 'pnr', 'report_timing', 'gen_bit_stream']
# PG2L200H_FBB676.bsm package map from PDS 2022.2-SP6.4; MINI manual
# pp.12,21-27: L5 is fixed 3.3 V; L6/L7 use the adjustable board supply.
MIC_BANK_PINS = {
    'L5': 'M19 R14 R15 P14 N14 P15 P16 N16 N17 R16 R17 P18 N18 K25 K26 M20 L20 L24 L25 M24 M25 L22 L23 M21 M22 N21 N22 P20 P21 N23 N24 P19 N19 P23 P24 R20 R21 R25 P25 N26 M26 T24 T25 R26 P26 T22 R22 T23 R23 R18',
    'L6': 'U24 U25 U26 V26 W26 AB26 AC26 W25 Y26 Y25 AA25 V24 W24 AA24 AB25 AA22 AA23 AB24 AC24 V23 W23 Y22 Y23 U22 V22 U21 V21 W21 Y21 T20 U20 W20 Y20 T19 U19 V19 W19 V18 W18 T14 T15 T17 T18 U15 U16 U14 V14 V16 V17 U17',
    'L7': 'AB22 AE25 AE26 AC22 AC23 AF24 AF25 AD25 AD26 AE23 AF23 AD23 AD24 AD21 AE21 AF19 AF20 AE22 AF22 AD20 AE20 AB21 AC21 AA20 AB20 AA19 AB19 AC19 AD19 AC18 AD18 AE18 AF18 Y18 AA18 AE17 AF17 AA17 AB17 AC17 AD17 Y16 Y17 AB16 AC16 Y15 AA15 W14 W15 W16',
}
MIC_PIN_BANK = {pin: bank for bank,pins in MIC_BANK_PINS.items() for pin in pins.split()}

def microphone_electrical(port, pin, l5_level_shifted=False):
    bank = MIC_PIN_BANK.get(pin)
    if bank not in ('L5','L6','L7'):
        raise ValueError(f'Unreviewed microphone package pin: {port}={pin}')
    if bank == 'L5':
        if port.startswith('mic_clk') or not l5_level_shifted:
            raise ValueError(f'{port}={pin} is on fixed 3.3 V Bank L5: 1.8 V direct connection is unsupported; move DATA to L6/L7 or explicitly select external L5 level translation')
        return '3.3','LVCMOS33'
    return '1.8','LVCMOS18'

def tcl_path(path):
    text = str(path).replace('\\', '/')
    if any(c in text for c in '{}\n\r'):
        raise ValueError('Unsupported brace or newline in path')
    return '{' + text + '}'

def prepare_pins(l5_level_shifted=False):
    text = (ROOT/'README.md').read_text(encoding='utf-8')
    mapping = {}
    for pin, kind, number in re.findall(r'\b([A-Z]{1,2}\d+)\s*-\s*(DATA|CLK)\s*(\d+)\b',text):
        name = f'pdm_data[{number}]' if kind == 'DATA' else f'mic_clk[{number}]'
        if name in mapping:
            raise ValueError(f'Duplicate logical port in README: {name}')
        mapping[name] = pin
    expected = {f'pdm_data[{i}]' for i in range(64)} | {f'mic_clk[{i}]' for i in range(8)}
    if mapping.keys() != expected:
        raise ValueError(f'Incomplete microphone map: missing={expected-mapping.keys()}, extra={mapping.keys()-expected}')
    microphone_standards = {port:microphone_electrical(port,pin,l5_level_shifted) for port,pin in mapping.items()}
    ethernet = dict(re.findall(r'\|\s*(PHY0_[A-Z]+(?:\[\d\])?|RSTN_OUT)\s*\|[^|]*\|\s*([A-Z]{1,2}\d+)\s*\|',text))
    if len(ethernet) != 15:
        raise ValueError('README must contain all 15 PHY pins')
    mapping.update(ethernet)
    mapping.update(sys_clk_27='D18',sys_clk_125_p='N3',sys_clk_125_n='N2',reset_n='C22')
    mapping.update(selftest_key_n='C23',uart_rx='B24',uart_tx='C24')
    mapping.update({f'led[{i}]':pin for i,pin in enumerate(('A20','C19','C18','E18','A17'))})
    if len(set(mapping.values())) != len(mapping):
        raise ValueError('Conflicting package-pin assignments; build stopped')
    out = ROOT/'fpga/constraints'
    out.mkdir(exist_ok=True,parents=True)
    lines = ['# Generated from README microphone/PHY map and MINI hardware manual pp.13-14,34.',
             '# MEMS VDD=1.8 V. Set physical Bank L6/L7 VCCIO=1.8 V before connecting.',
             '# L5 DATA, if present, requires external 1.8-to-3.3 V translation.']
    for port,pin in mapping.items():
        direction = 'INPUT'
        if port.startswith(('mic_clk','PHY0_TX','led[')) or port in ('PHY0_MDC','RSTN_OUT','uart_tx'):
            direction='OUTPUT'
        elif port == 'PHY0_MDIO':
            direction='INOUT'
        voltage,standard = ('1.5','SSTL15D_I') if port.startswith('sys_clk_125') else ('3.3','LVCMOS33')
        if port in microphone_standards:
            voltage,standard = microphone_standards[port]
        for attr,value in [('DIRECTION',direction),('LOC',pin),('VCCIO',voltage),('STANDARD',standard)]:
            lines.append(f'define_attribute {{p:{port}}} {{PAP_IO_{attr}}} {{{value}}}')
        if direction != 'INPUT':
            drive = '16' if port.startswith(('PHY0_TX','mic_clk')) else '4'
            lines += [f'define_attribute {{p:{port}}} {{PAP_IO_DRIVE}} {{{drive}}}',
                      f'define_attribute {{p:{port}}} {{PAP_IO_SLEW}} {{FAST}}']
    (out/'board_pins.fdc').write_text('\n'.join(lines)+'\n',encoding='ascii')
    (out/'board_pins.json').write_text(json.dumps(mapping,indent=2)+'\n',encoding='ascii')
    return mapping

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--stage',choices=STAGES,default='report_timing')
    p.add_argument('--build-name',default='MEMS_Array_uart_clk8_18v_spread5',help='Separate output folder under fpga/build; preserves earlier released project')
    p.add_argument('--place-seed',type=int,default=2,help='Global placement seed; fixed FIR macro sites and timing requirements are unchanged')
    p.add_argument('--placement-decongestion',type=int,choices=range(10),default=5,help='PDS placement spreading; does not change timing constraints')
    p.add_argument('--placement-initial-method',choices=['Quad','Center'],default='Center')
    p.add_argument('--pnr-timeout-minutes',type=int,default=120,help='Whole PNR action time limit, including automatic route iterations')
    p.add_argument('--mems-l5-level-shifted',action='store_true',help='Build for external 1.8-to-3.3 V translators on L5 DATA; never for direct 1.8 V wiring')
    p.add_argument('--start-stage',choices=['compile','dev_map'],default='compile',help='Start a fresh build, or map an existing synthesis database for diagnosis; release builds must start at compile')
    p.add_argument('--pango',default=os.getenv('PANGO_INSTALL','D:/Application/ElectronicIDE/Pango/PDS_2022.2-SP6.4'))
    p.add_argument('--license-file',default=os.getenv('PANGO_LICENSE_FILE'))
    args=p.parse_args()
    if args.place_seed<1:raise ValueError('Placement seed must be positive')
    if args.pnr_timeout_minutes<1:raise ValueError('PNR timeout must be positive')
    if STAGES.index(args.start_stage)>STAGES.index(args.stage):
        raise ValueError('The final stage must not precede --start-stage')
    install=Path(args.pango)
    shell=install/'bin/pds_shell.exe'
    if not shell.is_file(): raise RuntimeError('Set --pango to the installed Pango directory')
    env=os.environ.copy()
    if args.license_file: env['PANGO_LICENSE_FILE']=args.license_file
    if not env.get('PANGO_LICENSE_FILE'):
        licenses=list((install.parent/'license').glob('*.lic'))
        if len(licenses)==1: env['PANGO_LICENSE_FILE']=str(licenses[0])
        else: raise RuntimeError('Set PANGO_LICENSE_FILE or --license-file to an existing valid license')
    prepare_pins(args.mems_l5_level_shifted)
    if not re.fullmatch(r'[A-Za-z0-9_-]+',args.build_name):raise ValueError('Invalid build folder name')
    build=ROOT/'fpga/build'/args.build_name
    build.mkdir(parents=True,exist_ok=True)
    sources=sorted(p for p in (ROOT/'rtl').rglob('*') if p.suffix in ('.sv','.v'))
    constraints=[ROOT/'fpga/constraints/board_pins.fdc',ROOT/'fpga/constraints/timing.fdc']
    floorplan=ROOT/'fpga/constraints/frontend_floorplan.pcf'
    floorplan_commands=[s.strip() for s in floorplan.read_text(encoding='ascii').splitlines() if s.strip() and not s.lstrip().startswith('#')]
    if len(floorplan_commands)!=176 or any(not re.fullmatch(r'def_inst_site \{core/frontend/fir[12]/[^{}]+\} (?:APM|DRM)_\d+_\d+ (?:XAPM_CORE_[UD]|DRM0)',s) for s in floorplan_commands):
        raise ValueError('Unexpected frontend floorplan commands')
    includes=[ROOT/'rtl',ROOT/'rtl/board']
    top='mems_array_pg2l200h'
    gate_base=[sys.executable,str(ROOT/'fpga/scripts/check_release.py'),
        '--manifest',str(build/'manifest.json'),
        '--regression',str(ROOT/'log/full_regression.json'),
        '--timing-report',str(build/'report_timing'/f'{top}.rtr'),
        '--constraints-report',str(build/'constraint_check/constraint_check.ccr'),
        '--map-report',str(build/'device_map'/f'{top}.dmr'),
        '--build-log',str(build/'build.log')]
    commands=['set_arch -family Logos2 -device PG2L200H -speedgrade -6 -package FBB676']
    commands += ['add_design '+tcl_path(p) for p in sources]
    commands += ['add_constraint '+tcl_path(p) for p in constraints]
    compile_options=f'-top_module {top} -system_verilog -include_path '+'{'+ ' '.join(tcl_path(p) for p in includes)+'}'
    actions={'compile':f'compile {compile_options}',
             # The default 10000 fanout guide leaves saturation/select nets
             # driving thousands of loads. 256 duplicates their logic locally;
             # it changes neither RTL behavior nor any timing requirement.
             'synthesize':'synthesize -ads -selected_syn_tool_opt 2 -fanout_guide 256',
             'dev_map':'dev_map',
             # These are implementation optimization targets, not SDC timing
             # exceptions. A 20 ps positive target avoids spending the repair
             # budget on tens of thousands of already-safe 0..200 ps paths.
             # Cap serial CE/RS chains to remove the routed FIR final_sum
             # enable bottleneck. Clock/IO timing requirements are unchanged.
             # PDS derives priority routing commands for paths below +50 ps.
             # This is a physical search target, not a relaxed timing exception.
             # It repairs the reset-distribution near miss seen after ARP gating.
             'pnr':'pnr -mode performance -max_ctrl_chain_length 8 -enable_route_constraint_iterate -route_constraint_iterate_times 2 -route_constraint_slack 0.050 -route_constraint_max_timing_path 8 -fix_hold_violation_in_route TRUE -fix_hold_violation_threshold_for_clock_path_cross_srb 20 -fix_hold_violation_threshold_for_clk_tree 20 -max_hold_violated_paths_num 50000 -dump_router_congestion_plot TRUE -action_timeout '+str(args.pnr_timeout_minutes),
             'report_timing':'report_timing -delay_type min_max -report_io_datasheet -report_max_skew -report_exception TRUE -max_path 8',
             'gen_bit_stream':'gen_bit_stream -create_bit_file TRUE -create_bin_file -persist_pin {Release For USER}'}
    actions['pnr']+=' -gplace_seed '+str(args.place_seed)
    actions['pnr']+=' -plc_decongestion '+str(args.placement_decongestion)+' -plc_initial_method '+args.placement_initial_method
    if args.start_stage != 'compile':
        if args.start_stage == 'dev_map':
            actions['dev_map']='dev_map -force_to_run -input_db_file '+tcl_path(build/'synthesize'/f'{top}_syn.adf')
    # PDS 2022.2 route-constraint iteration accepts PLC, not MAP, databases.
    # Produce that placement in this build, then freeze a separate input copy.
    place_action=re.sub(r' -enable_route_constraint_iterate -route_constraint_iterate_times 2 -route_constraint_slack 0\.050 -route_constraint_max_timing_path 8', '', actions['pnr'])+' -place_only'
    if args.stage == 'gen_bit_stream' and args.start_stage != 'compile':
        raise ValueError('Release bitstreams require a complete build starting at compile')
    # PDS parses ordinary Tcl expressions before executing its queued flow.
    # File copies and external gates therefore belong in Python, between
    # completed PDS processes, never in a nominally sequential flow Tcl file.
    main_stages=STAGES[STAGES.index(args.start_stage):min(STAGES.index(args.stage),4)+1]
    setup_commands=commands.copy()
    # PDS rewrites the physical PCF in dev_map. End that process before
    # appending the reviewed macro locations; resume from its exact map DB.
    split_route='pnr' in main_stages
    first_stages=main_stages[:main_stages.index('pnr')] if split_route else main_stages
    commands += [actions[stage] for stage in first_stages]
    script=build/'build.tcl'
    script.write_text('\n'.join(commands)+'\n',encoding='utf-8')
    def source_hashes():
        # Re-enumerate to detect newly added or removed RTL/includes as well.
        # Evidence-checker/helper versions are independently hashed before and
        # after their audits. Hardware inputs and this build recipe are frozen
        # for the entire physical build.
        build_inputs=sorted(p for p in (ROOT/'rtl').rglob('*') if p.suffix in ('.sv','.v','.svh'))+constraints+[floorplan,Path(__file__).resolve(),ROOT/'fpga/scripts/check_pll_parameters.py']
        return {str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in build_inputs}
    manifest={'status':'RUNNING','requested_stage':args.stage,'start_stage':args.start_stage,'started_at':datetime.now().astimezone().isoformat(),
              'device':'PG2L200H-6-FBB676','source_sha256':source_hashes(),
              'clock_hz':{'audio':122880000,'ethernet':125000000},
              'mems_electrical':{'vdd_volts':1.8,'clock_outputs':8,'clock_drive_ma':16,'clock_slew':'FAST',
                  'required_bank_l6_l7_vccio_volts':1.8,'l5_external_level_translation':args.mems_l5_level_shifted,
                  'hardware_voltage_verified':False},
              'implementation':{'fanout_guide':256,'explicit_control_maxfan':256,'placement_decongestion':args.placement_decongestion,'placement_initial_method':args.placement_initial_method,'placement_seed':args.place_seed,'pnr_timeout_minutes':args.pnr_timeout_minutes,'congestion_dump':True,'floorplan':'frontend_floorplan.pcf','control_chain_max_length':8,'route_constraint_iteration':{'maximum':2,'target_slack_ns':0.050,'max_paths':8}},
              'flow_evidence':[]}
    (build/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    log=build/'build.log'
    if log.exists():
        archive=build/'logs'; archive.mkdir(exist_ok=True)
        (archive/f'build_{datetime.now():%Y%m%d_%H%M%S}.log').write_bytes(log.read_bytes())
    print(f'[PANGO] {args.stage}; log: {log}',flush=True)
    def run_pds(flow_script,project,stages,mode='a'):
        with log.open(mode,encoding='utf-8') as output:
            offset=output.tell()
            result=subprocess.run([str(shell),'-file',str(flow_script),'-work_dir',str(build),'-project_name',project],cwd=build,env=env,stdout=output,stderr=subprocess.STDOUT)
        with log.open('r',encoding='utf-8',errors='replace') as output:
            output.seek(offset)
            portion=output.read()
        if result.returncode or re.search(r'^[ \t]*E: |^[ \t]*[ECW]: Internal-',portion,re.M):
            raise RuntimeError(f'PDS process {project} failed; inspect {log}')
        # Markers are emitted only after PDS exits successfully and confirms
        # the real action completed. A Tcl queue/parse message is insufficient.
        for stage in stages:
            native='pnr' if stage=='place' else stage
            matches=re.findall(r'^Executing : '+re.escape(native)+r'([^\r\n]*) successfully\.$',portion,re.M)
            if not matches or (stage=='place' and not any(re.search(r'\s-place_only(?:\s|$)',m) for m in matches)):
                raise RuntimeError(f'No actual successful completion for {stage}')
        with log.open('a',encoding='utf-8') as output:
            for stage in stages:
                if stage in STAGES or stage=='place':
                    output.write(f'MEMS_PANGO_{stage.upper()}_COMPLETE\n')
        manifest['flow_evidence'].append(dict(project=project,stages=stages,
            script=str(flow_script.relative_to(ROOT)).replace('\\','/'),
            script_sha256=hashlib.sha256(flow_script.read_bytes()).hexdigest(),
            completed_at=datetime.now().astimezone().isoformat(),exit_code=result.returncode))
        (build/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    validate_plls(install,build,ROOT/'rtl/board/pango_board_clocks.v')
    success=False
    failure=None
    try:
        run_pds(script,'MEMS_Array',first_stages,'w')
        if split_route:
            mapped_db=build/'device_map'/f'{top}_map.adf'
            physical_pcf=build/'device_map'/f'{top}.pcf'
            base_pcf=build/'device_map'/f'{top}_base.pcf'
            if not mapped_db.is_file() or not physical_pcf.is_file():
                raise RuntimeError('Missing fresh map DB or generated physical PCF')
            base_pcf.write_bytes(physical_pcf.read_bytes())
            physical_pcf.write_bytes(base_pcf.read_bytes()+b'\n'+floorplan.read_bytes())
            manifest['postmap_constraints']={
                'mapped_db_sha256':hashlib.sha256(mapped_db.read_bytes()).hexdigest(),
                'base_pcf_sha256':hashlib.sha256(base_pcf.read_bytes()).hexdigest(),
                'route_pcf_sha256':hashlib.sha256(physical_pcf.read_bytes()).hexdigest(),
                'template_sha256':hashlib.sha256(floorplan.read_bytes()).hexdigest()}
            (build/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
            place_script=build/'place.tcl'
            place_script.write_text('\n'.join(setup_commands+['add_constraint '+tcl_path(physical_pcf),
                place_action+' -force_to_run -input_db_file '+tcl_path(mapped_db)])+'\n',encoding='utf-8')
            run_pds(place_script,'MEMS_Array_place',['place'])
            placed_source=build/'place_route'/f'{top}_plc.adf'
            placed_input=build/'place_route'/f'{top}_placed_input.adf'
            if not placed_source.is_file():
                raise RuntimeError('Missing fresh placement database')
            shutil.copy2(placed_source,placed_input)
            placed_hash=hashlib.sha256(placed_input.read_bytes()).hexdigest()
            manifest['postplace_link']={'placed_db_sha256':placed_hash}
            (build/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
            route_stages=main_stages[main_stages.index('pnr'):]
            route_script=build/'route.tcl'
            route_commands=setup_commands+['add_constraint '+tcl_path(physical_pcf),
                actions['pnr']+' -force_to_run -input_db_file '+tcl_path(placed_input)]
            route_commands += [actions[s] for s in route_stages if s!='pnr']
            route_script.write_text('\n'.join(route_commands)+'\n',encoding='utf-8')
            run_pds(route_script,'MEMS_Array_route',route_stages)
            if hashlib.sha256(placed_input.read_bytes()).hexdigest()!=placed_hash:
                raise RuntimeError('Placement input changed during route iteration')
            for field,path in [('mapped_db_sha256',mapped_db),('base_pcf_sha256',base_pcf),('route_pcf_sha256',physical_pcf),('template_sha256',floorplan)]:
                if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest['postmap_constraints'][field]:
                    raise RuntimeError('Intermediate build input changed during routing: '+field)
        if args.stage == 'gen_bit_stream':
            routed_db=build/'place_route'/f'{top}_pnr.adf'
            if not routed_db.is_file():
                raise RuntimeError('Missing routed database for corner exports')
            routed_hash=hashlib.sha256(routed_db.read_bytes()).hexdigest()
            manifest['routed_db_sha256']=routed_hash
            clock_audit=build/'clock_audit'; clock_audit.mkdir(exist_ok=True)
            for corner in ('slow','fast'):
                export_script=build/f'export_{corner}.tcl'
                export_script.write_text(commands[0]+'\n'+f'gen_netlist -force_to_run -input_db_file {tcl_path(routed_db)} -sdf_annotate FALSE -process_corner {corner}\n',encoding='utf8')
                run_pds(export_script,f'MEMS_Array_{corner}_sdf',['gen_netlist'])
                for suffix in ('sta.sdf','sim.v'):
                    shutil.copy2(build/'generate_netlist'/f'{top}_{suffix}',clock_audit/f'{corner}_{suffix}')
            if hashlib.sha256(routed_db.read_bytes()).hexdigest()!=routed_hash:
                raise RuntimeError('Routed database changed during evidence export')
            gate=gate_base+['--pre-bit','--output',str(build/'pre_bit_check.json')]
            if subprocess.run(gate,cwd=ROOT).returncode:
                raise RuntimeError('Pre-bit evidence gate rejected the build')
            bit_script=build/'generate_bitstream.tcl'
            bit_script.write_text(commands[0]+'\n'+actions['gen_bit_stream']+' -force_to_run -input_db_file '+tcl_path(routed_db)+'\n',encoding='utf8')
            run_pds(bit_script,'MEMS_Array_bitstream',['gen_bit_stream'])
            if hashlib.sha256(routed_db.read_bytes()).hexdigest()!=routed_hash:
                raise RuntimeError('Routed database changed during bitstream generation')
            manifest['routed_db_sha256']=routed_hash
        success=True
    except (OSError,RuntimeError,ValueError) as error:
        failure=str(error)
    content=log.read_text(encoding='utf-8',errors='replace')
    unchanged=source_hashes()==manifest['source_sha256']
    success=success and unchanged
    manifest.update(status='PASS' if success else 'FAIL',exit_code=0 if success else 1,sources_unchanged=unchanged,completed_at=datetime.now().astimezone().isoformat())
    if failure: manifest['error']=failure
    (build/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    if success and args.stage == 'gen_bit_stream':
        gate=gate_base+['--bitstream',str(build/'generate_bitstream'/f'{top}.sbit'),
                       '--bin',str(build/'generate_bitstream'/f'{top}.bin'),
                       '--output',str(build/'release.json')]
        checked=subprocess.run(gate,cwd=ROOT)
        if checked.returncode:
            success=False
            manifest.update(status='FAIL',release_error='Final evidence gate rejected the bitstream')
            (build/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(content[-8000:])
    if not success: raise RuntimeError(failure or f'Pango {args.stage} failed; inspect {log}')

if __name__=='__main__':
    try: main()
    except (RuntimeError,ValueError) as error:
        print('[PANGO_ERROR]',error,file=sys.stderr);sys.exit(1)
