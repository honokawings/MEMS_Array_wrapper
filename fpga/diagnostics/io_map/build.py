"""Build two isolated PG2L200H IO diagnostics; preserve the microphone release."""
from pathlib import Path
from datetime import datetime
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PIN_MAP={**{f'key_n[{i}]':p for i,p in enumerate(('C22','C23','B22','A22','B20'))},
         **{f'led[{i}]':p for i,p in enumerate(('A20','C19','C18','E18','A17'))},
         **{f'mic_clk[{i}]':p for i,p in enumerate(('AC26','AB26','AA23','AA22'))},
         'phy_reset_n':'G25'}

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def q(path): return '{'+str(path).replace('\\','/')+'}'
def write_json(path,value): path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
def need(ok,message):
    if not ok: raise RuntimeError(message)

def snapshot():
    return {p.relative_to(ROOT).as_posix():sha(p) for p in sorted(HERE.rglob('*'))
            if p.is_file() and p.suffix in {'.py','.sv','.do','.bat','.fdc'}}

def execute(command,log,cwd,env=None):
    with log.open('w',encoding='utf-8') as f:
        result=subprocess.run([str(x) for x in command],cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT)
    text=log.read_text(encoding='utf-8',errors='replace')
    need(result.returncode==0,f'Command failed: {log}\n{text[-4000:]}')
    need(not re.search(r'\[TB_ERROR\]|\*\* (?:Error|Fatal)|^\s*E: ',text,re.M),f'Tool error: {log}\n{text[-4000:]}')
    return text

def simulate(args):
    run=ROOT/'log/io_map_diag';run.mkdir(parents=True,exist_ok=True)
    modelsim=Path(args.modelsim)
    library=run/'work'
    ini=run/'modelsim.ini'
    ini.write_text('[Library]\nwork = '+library.as_posix()+'\n',encoding='ascii')
    if not library.exists():execute([modelsim/'vlib.exe',library],run/'vlib.log',run)
    vendor=Path(args.pango)/'arch/vendor/pango/verilog/simulation'
    primitives=[vendor/(name+'.v') for name in ('GTP_GRS','GTP_DFF','GTP_INBUF','GTP_CLKBUFG')]
    sources=primitives+[HERE/'rtl/io_map_diag.sv',HERE/'tb/tb_io_map.sv']
    execute([modelsim/'vlog.exe','-modelsimini',ini,'-sv','-lint','-work',library,*sources],run/'compile.log',run)
    text=execute([modelsim/'vsim.exe','-modelsimini',ini,'-batch','-onfinish','exit',
                  '-wlf',run/'io_map.wlf','work.tb_io_map','-do',HERE/'tb_script/run.do'],run/'simulation.log',run)
    need('[TB_INFO] Simulation Finished!' in text,'Simulation did not finish')
    result={'status':'PASS','completed_at':datetime.now().astimezone().isoformat(),
            'sources_sha256':{p.as_posix():sha(p) for p in sources},
            'checks':int(re.search(r'checks=(\d+)',text)[1]),'exhaustive_key_combinations':32,
            'vendor_primitives':True}
    write_json(run/'result.json',result)
    print('[SIM_PASS] '+str(run/'result.json'),flush=True)
    return run/'result.json'

def constraints(top):
    pins=dict(PIN_MAP)
    walk=top=='io_map_walk'
    if walk:pins['sys_clk_27']='D18'
    directory=HERE/'constraints';directory.mkdir(exist_ok=True)
    lines=['# MINI hardware manual pp.13,34-35; README microphone clock pins.']
    for port,pin in pins.items():
        direction='INPUT' if port.startswith('key_n') or port=='sys_clk_27' else 'OUTPUT'
        for name,value in [('DIRECTION',direction),('LOC',pin),('VCCIO','3.3'),('STANDARD','LVCMOS33')]:
            lines.append(f'define_attribute {{p:{port}}} {{PAP_IO_{name}}} {{{value}}}')
        if direction=='OUTPUT':
            lines += [f'define_attribute {{p:{port}}} {{PAP_IO_DRIVE}} {{4}}',
                      f'define_attribute {{p:{port}}} {{PAP_IO_SLEW}} {{SLOW}}']
    pin_file=directory/(top+'_pins.fdc');pin_file.write_text('\n'.join(lines)+'\n',encoding='ascii')
    timing=['# Human-operated combinational inputs; io_ref is a bookkeeping virtual clock.',
            'create_clock -name io_ref -period 1000.000',
            'set_input_delay -clock io_ref -max 0.000 [get_ports {key_n[*]}]',
            'set_input_delay -clock io_ref -min 0.000 [get_ports {key_n[*]}]']
    if walk:timing += ['create_clock -name ref27 -period 37.037037037 [get_ports sys_clk_27]',
                      'set_clock_uncertainty 0.150 [get_clocks ref27]']
    output_clock='ref27' if walk else 'io_ref'
    timing += [f'set_output_delay -clock {output_clock} -max 0.000 [get_ports {{led[*]}}]',
               f'set_output_delay -clock {output_clock} -min 0.000 [get_ports {{led[*]}}]',
               '# Bound the asynchronous key-to-LED pad path; no sampled receiver exists.',
               'set_max_delay 25.000 -datapath_only -from [get_ports {key_n[*]}] -to [get_ports {led[*]}]',
               'set_false_path -hold -from [get_ports {key_n[*]}]',
               '# mic_clk and phy_reset_n are constant-low outputs, with no timing path.']
    timing_file=directory/(top+'_timing.fdc');timing_file.write_text('\n'.join(timing)+'\n',encoding='ascii')
    return pins,[pin_file,timing_file]

def check_reports(build,top,pins):
    dmr=build/'device_map'/(top+'.dmr')
    rtr=build/'report_timing'/(top+'.rtr')
    text=dmr.read_text(encoding='utf-8',errors='replace')
    actual={}
    for line in text.splitlines():
        f=[x.strip() for x in line.split('|')]
        if len(f)>=6 and f[2].lower() in ('input','output','inout'):
            need(f[1] not in actual,'Duplicate mapped port')
            actual[f[1]]={'pin':f[3],'direction':f[2].upper(),'voltage':f[4],'standard':f[5]}
    need(set(actual)==set(pins),'Mapped port set differs from expected')
    for name,pin in pins.items():
        expected_dir='INPUT' if name.startswith('key_n') or name=='sys_clk_27' else 'OUTPUT'
        need(actual[name]==dict(pin=pin,direction=expected_dir,voltage='3.3',standard='LVCMOS33'),f'Pin mismatch: {name}')
    timing=rtr.read_text(encoding='utf-8',errors='replace')
    need('Design Summary : All Constraints Met.' in timing,'Routed timing failed')
    need('Setup Summary(Slow Corner)' in timing and 'Setup Summary(Fast Corner)' in timing,'Both corners required')
    if top=='io_map_walk':need(re.search(r'ref27\s+37\.037',timing),'27 MHz reference missing')
    return {'mapped_ports':actual,'timing_model':'Pre-silicon' if 'Pre-silicon' in timing else 'see native report',
            'timing_status':'All Constraints Met','timing_report':str(rtr),'map_report':str(dmr)}

def build_one(args,top,pins,fdcs,sim_result):
    build=ROOT/'fpga/build'/('IO_DIAG_'+top.removeprefix('io_map_').upper())
    build.mkdir(parents=True,exist_ok=True)
    # Preserve previous attempts rather than mixing new evidence with an old success.
    for name in ('release.json','manifest.json'):
        p=build/name
        if p.exists():p.rename(build/(name+datetime.now().strftime('.%Y%m%d_%H%M%S.bak')))
    inputs=snapshot()
    manifest={'status':'RUNNING','top':top,'device':'PG2L200H-6-FBB676','started_at':datetime.now().astimezone().isoformat(),
              'source_sha256':inputs,'sim_result':str(sim_result),'sim_sha256':sha(sim_result),
              'scope':'IO mapping diagnostic only; physical board confirmation required'}
    write_json(build/'manifest.json',manifest)
    env=os.environ.copy();install=Path(args.pango)
    if not env.get('PANGO_LICENSE_FILE'):
        licenses=list((install.parent/'license').glob('*.lic'))
        need(len(licenses)==1,'Set PANGO_LICENSE_FILE to a valid installed license')
        env['PANGO_LICENSE_FILE']=str(licenses[0])
    arch='set_arch -family Logos2 -device PG2L200H -speedgrade -6 -package FBB676'
    steps=['compile','synthesize','dev_map','pnr','report_timing']
    commands=[arch,'add_design '+q(HERE/'rtl/io_map_diag.sv')]+['add_constraint '+q(p) for p in fdcs]
    commands += [f'compile -top_module {top} -system_verilog','synthesize -ads -selected_syn_tool_opt 2',
                 'dev_map','pnr -mode performance -fix_hold_violation_in_route TRUE',
                 'report_timing -delay_type min_max -report_io_datasheet -report_exception TRUE -max_path 8']
    script=build/'build.tcl';script.write_text('\n'.join(commands)+'\n',encoding='utf-8')
    shell=install/'bin/pds_shell.exe'
    try:
        print('[BUILD] '+top,flush=True)
        text=execute([shell,'-file',script,'-work_dir',build,'-project_name',build.name],build/'build.log',build,env)
        for step in steps:need(re.search(r'^Executing : '+step+r'(?: .*)? successfully\.$',text,re.M),f'{step} incomplete')
        audit=check_reports(build,top,pins)
        need(snapshot()==inputs and sha(sim_result)==manifest['sim_sha256'],'Sources or simulation changed during build')
        routed=build/'place_route'/(top+'_pnr.adf');routed_sha=sha(routed)
        bit_script=build/'generate_bitstream.tcl'
        bit_script.write_text(arch+'\ngen_bit_stream -create_bit_file TRUE -create_bin_file -persist_pin {Release For USER} -force_to_run -input_db_file '+q(routed)+'\n',encoding='utf-8')
        text=execute([shell,'-file',bit_script,'-work_dir',build,'-project_name',build.name+'_bitstream'],build/'bitstream.log',build,env)
        need(re.search(r'^Executing : gen_bit_stream(?: .*)? successfully\.$',text,re.M),'Bitstream incomplete')
        need(sha(routed)==routed_sha and snapshot()==inputs,'Build evidence changed during bit generation')
        evidence={}
        for name,p in {'sbit':build/'generate_bitstream'/(top+'.sbit'),'bin':build/'generate_bitstream'/(top+'.bin'),
                       'timing':Path(audit['timing_report']),'mapping':Path(audit['map_report']),
                       'routed_db':routed,'build_log':build/'build.log','bitstream_log':build/'bitstream.log',
                       'flow_script':script,'bitstream_script':bit_script}.items():
            need(p.is_file() and p.stat().st_size>0,f'Missing evidence {name}')
            evidence[name]={'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size}
        manifest.update(status='PASS',completed_at=datetime.now().astimezone().isoformat(),sources_unchanged=True)
        write_json(build/'manifest.json',manifest)
        release=dict(status='PASS',board_mapping_confirmed=False,scope=manifest['scope'],
                     source_sha256=inputs,simulation_sha256=sha(sim_result),manifest_sha256=sha(build/'manifest.json'),
                     audit=audit,evidence=evidence)
        write_json(build/'release.json',release)
        print('[DIAG_RELEASE_PASS] '+str(build/'release.json'),flush=True)
    except Exception as exc:
        manifest.update(status='FAIL',error=str(exc),completed_at=datetime.now().astimezone().isoformat())
        write_json(build/'manifest.json',manifest)
        raise

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--pango',default='D:/Application/ElectronicIDE/Pango/PDS_2022.2-SP6.4')
    ap.add_argument('--modelsim',default='D:/Application/ElectronicIDE/Modelsim/2020_4/win64')
    ap.add_argument('--sim-only',action='store_true')
    ap.add_argument('--variant',choices=('direct','walk','both'),default='both')
    args=ap.parse_args()
    sim_result=simulate(args)
    if args.sim_only:return
    # Generate both constraint sets before freezing any source hashes.
    prepared={top:constraints(top) for top in ('io_map_direct','io_map_walk')}
    for top,(pins,fdcs) in prepared.items():
        if args.variant=='both' or top.endswith(args.variant):build_one(args,top,pins,fdcs,sim_result)

if __name__=='__main__':
    main()
