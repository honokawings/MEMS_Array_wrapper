"""Reproducible Pango build in fpga/build; the GUI project is never overwritten."""
from pathlib import Path
import argparse, hashlib, json, os, re, shutil, subprocess, sys
from datetime import datetime

ROOT = Path(__file__).resolve().parents[2]
STAGES = ['compile', 'synthesize', 'dev_map', 'pnr', 'report_timing', 'gen_bit_stream']

def tcl_path(path):
    text = str(path).replace('\\', '/')
    if any(c in text for c in '{}\n\r'):
        raise ValueError('Unsupported brace or newline in path')
    return '{' + text + '}'

def prepare_pins():
    text = (ROOT/'README.md').read_text(encoding='utf-8')
    mapping = {}
    for pin, kind, number in re.findall(r'\b([A-Z]{1,2}\d+)\s*-\s*(DATA|CLK)\s*(\d+)\b',text):
        name = f'pdm_data[{number}]' if kind == 'DATA' else f'mic_clk[{number}]'
        if name in mapping:
            raise ValueError(f'Duplicate logical port in README: {name}')
        mapping[name] = pin
    expected = {f'pdm_data[{i}]' for i in range(64)} | {f'mic_clk[{i}]' for i in range(4)}
    if mapping.keys() != expected:
        raise ValueError(f'Incomplete microphone map: {expected-mapping.keys()}')
    ethernet = dict(re.findall(r'\|\s*(PHY0_[A-Z]+(?:\[\d\])?|RSTN_OUT)\s*\|[^|]*\|\s*([A-Z]{1,2}\d+)\s*\|',text))
    if len(ethernet) != 15:
        raise ValueError('README must contain all 15 PHY pins')
    mapping.update(ethernet)
    mapping.update(sys_clk_27='D18',sys_clk_125_p='N3',sys_clk_125_n='N2',reset_n='C22')
    if len(set(mapping.values())) != len(mapping):
        raise ValueError('Conflicting package-pin assignments; build stopped')
    out = ROOT/'fpga/constraints'
    out.mkdir(exist_ok=True,parents=True)
    lines = ['# Generated from README microphone/PHY map and MINI hardware manual pp.13-14,34.',
             '# Bank L6/L7 must be physically configured for 3.3 V before use.']
    for port,pin in mapping.items():
        direction = 'INPUT'
        if port.startswith('mic_clk') or port.startswith('PHY0_TX') or port in ('PHY0_MDC','RSTN_OUT'):
            direction='OUTPUT'
        elif port == 'PHY0_MDIO':
            direction='INOUT'
        voltage,standard = ('1.5','SSTL15D_I') if port.startswith('sys_clk_125') else ('3.3','LVCMOS33')
        for attr,value in [('DIRECTION',direction),('LOC',pin),('VCCIO',voltage),('STANDARD',standard)]:
            lines.append(f'define_attribute {{p:{port}}} {{PAP_IO_{attr}}} {{{value}}}')
        if direction != 'INPUT':
            drive = '16' if port.startswith('PHY0_TX') else ('8' if port.startswith('mic_clk') else '4')
            lines += [f'define_attribute {{p:{port}}} {{PAP_IO_DRIVE}} {{{drive}}}',
                      f'define_attribute {{p:{port}}} {{PAP_IO_SLEW}} {{FAST}}']
    (out/'board_pins.fdc').write_text('\n'.join(lines)+'\n',encoding='ascii')
    (out/'board_pins.json').write_text(json.dumps(mapping,indent=2)+'\n',encoding='ascii')
    return mapping

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--stage',choices=STAGES,default='report_timing')
    p.add_argument('--start-stage',choices=['compile','dev_map'],default='compile',help='Start a fresh build, or map an existing synthesis database for diagnosis; release builds must start at compile')
    p.add_argument('--pango',default=os.getenv('PANGO_INSTALL','D:/Application/ElectronicIDE/Pango/PDS_2022.2-SP6.4'))
    p.add_argument('--license-file',default=os.getenv('PANGO_LICENSE_FILE'))
    args=p.parse_args()
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
    prepare_pins()
    build=ROOT/'fpga/build/MEMS_Array'
    build.mkdir(parents=True,exist_ok=True)
    sources=sorted(p for p in (ROOT/'rtl').rglob('*') if p.suffix in ('.sv','.v'))
    constraints=[ROOT/'fpga/constraints/board_pins.fdc',ROOT/'fpga/constraints/timing.fdc']
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
             'synthesize':'synthesize -ads -selected_syn_tool_opt 2',
             'dev_map':'dev_map',
             # These are implementation optimization targets, not SDC timing
             # exceptions. A 20 ps positive target avoids spending the repair
             # budget on tens of thousands of already-safe 0..200 ps paths.
             'pnr':'pnr -mode performance -fix_hold_violation_in_route TRUE -fix_hold_violation_threshold_for_clock_path_cross_srb 20 -fix_hold_violation_threshold_for_clk_tree 20 -max_hold_violated_paths_num 50000',
             'report_timing':'report_timing -delay_type min_max -report_io_datasheet -report_max_skew -report_exception TRUE -max_path 8',
             'gen_bit_stream':'gen_bit_stream -create_bit_file TRUE -create_bin_file -persist_pin {Release For USER}'}
    if args.start_stage != 'compile':
        if args.start_stage == 'dev_map':
            actions['dev_map']='dev_map -force_to_run -input_db_file '+tcl_path(build/'synthesize'/f'{top}_syn.adf')
    if args.stage == 'gen_bit_stream' and args.start_stage != 'compile':
        raise ValueError('Release bitstreams require a complete build starting at compile')
    # PDS parses ordinary Tcl expressions before executing its queued flow.
    # File copies and external gates therefore belong in Python, between
    # completed PDS processes, never in a nominally sequential flow Tcl file.
    main_stages=STAGES[STAGES.index(args.start_stage):min(STAGES.index(args.stage),4)+1]
    commands += [actions[stage] for stage in main_stages]
    script=build/'build.tcl'
    script.write_text('\n'.join(commands)+'\n',encoding='utf-8')
    def source_hashes():
        # Re-enumerate to detect newly added or removed RTL/includes as well.
        # Evidence-checker/helper versions are independently hashed before and
        # after their audits. Hardware inputs and this build recipe are frozen
        # for the entire physical build.
        build_inputs=sorted(p for p in (ROOT/'rtl').rglob('*') if p.suffix in ('.sv','.v','.svh'))+constraints+[Path(__file__).resolve()]
        return {str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in build_inputs}
    manifest={'status':'RUNNING','requested_stage':args.stage,'start_stage':args.start_stage,'started_at':datetime.now().astimezone().isoformat(),
              'device':'PG2L200H-6-FBB676','source_sha256':source_hashes(),
              'clock_hz':{'audio':122880000,'ethernet':125000000},'flow_evidence':[]}
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
            if not re.search(r'^Executing : '+re.escape(stage)+r'(?: .*)? successfully\.$',portion,re.M):
                raise RuntimeError(f'No actual successful completion for {stage}')
        with log.open('a',encoding='utf-8') as output:
            for stage in stages:
                if stage in STAGES:
                    output.write(f'MEMS_PANGO_{stage.upper()}_COMPLETE\n')
        manifest['flow_evidence'].append(dict(project=project,stages=stages,
            script=str(flow_script.relative_to(ROOT)).replace('\\','/'),
            script_sha256=hashlib.sha256(flow_script.read_bytes()).hexdigest(),
            completed_at=datetime.now().astimezone().isoformat(),exit_code=result.returncode))
        (build/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    success=False
    failure=None
    try:
        run_pds(script,'MEMS_Array',main_stages,'w')
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
