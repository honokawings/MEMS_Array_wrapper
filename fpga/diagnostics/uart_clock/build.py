"""UART clock diagnostic with vendor-validated PFD31 PLL configuration."""
from pathlib import Path
from datetime import datetime
import argparse, importlib.util, json, os, re
import xml.etree.ElementTree as ET
from check_pll import validate as validate_pll

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
spec=importlib.util.spec_from_file_location('io_build',HERE.parent/'io_map/build.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
sha,q,need,execute,write_json=helper.sha,helper.q,helper.need,helper.execute,helper.write_json
TOP='uart_clock_diag'

def prepare():
    original=(ROOT/'rtl/board/pango_board_clocks.v').read_text(encoding='utf-8')
    need(original.count('module pango_board_clocks (')==1,'Unexpected clock source')
    probe=original.replace('module pango_board_clocks (','module pango_clock_probe (',1)
    probe=probe.replace('    output wire locked\n);','    output wire locked,\n    output wire monitor_ref_clk, monitor_raw125_clk, monitor_clk96,\n    output wire [2:0] monitor_locks\n);',1)
    extra='''    // Independent diagnostic taps; PLL parameters and reset sequencing unchanged.
    GTP_CLKBUFG u_monitor_ref (.CLKIN(clk_27_ibuf), .CLKOUT(monitor_ref_clk));
    GTP_CLKBUFG u_monitor_raw125 (.CLKIN(clk_125_ibuf), .CLKOUT(monitor_raw125_clk));
    assign monitor_clk96 = clk_96;
    assign monitor_locks = {lock_eth, lock_audio, lock_96};
'''
    probe=probe.replace('endmodule',extra+'endmodule',1)
    old='.INPUT_MHZ(125.0), .INPUT_DIV(1),\n                      .FEEDBACK_MULTIPLY(4), .OUTPUT_DIV(4))'
    need(probe.count(old)==1,'Expected one original Ethernet PLL configuration')
    probe=probe.replace(old,'.INPUT_MHZ(125.0), .INPUT_DIV(4),\n                      .FEEDBACK_MULTIPLY(16), .OUTPUT_DIV(4))')
    probe=probe.replace('// 125 / 1 * 4 * 2 = 1000 MHz VCO; 1000 / 4 = 250 MHz.',
        '// PFD=125/4=31.25 MHz, valid for OPTIMIZED bandwidth (10..40 MHz).\n    // 125 / 4 * 16 * 2 = 1000 MHz VCO; 1000 / 4 = 250 MHz.')
    probe=probe.replace('PLL parameters and reset sequencing unchanged.','PLL outputs/reset sequencing unchanged; Ethernet IDIV/MDIV corrected.')
    (HERE/'rtl/pango_clock_probe.v').write_text(probe,encoding='utf-8')
    observer=(HERE.parent/'clock_reset/rtl/clock_observer.sv').read_text(encoding='utf-8')
    observer=observer.replace('output wire [63:0] measured_deltas',
        'output wire [63:0] measured_deltas,\n    output wire [10:0] sampled_status,output wire [3:0] ever_healthy,live_fault')
    observer=observer.replace('    assign led=display;',
        '    assign led=display;\n    assign sampled_status=status_sync;\n    assign ever_healthy=armed;\n    assign live_fault=~healthy;')
    (HERE/'rtl/clock_observer.sv').write_text(observer,encoding='utf-8')
    pins={'sys_clk_27':'D18','sys_clk_125_p':'N3','sys_clk_125_n':'N2','uart_rx':'B24','uart_tx':'C24','phy_reset_n':'G25',
          **{f'mic_clk[{i}]':p for i,p in enumerate(('AC26','AB26','AA23','AA22'))}}
    cdir=HERE/'constraints';cdir.mkdir(exist_ok=True)
    lines=['# MINI hardware manual p.30 UART RX=B24/TX=C24; oscillator IO standards unchanged.']
    for port,pin in pins.items():
        diff=port.startswith('sys_clk_125')
        direction='INPUT' if (port.startswith('sys_clk') or port=='uart_rx') else 'OUTPUT'
        for name,value in [('DIRECTION',direction),('LOC',pin),('VCCIO','1.5' if diff else '3.3'),('STANDARD','SSTL15D_I' if diff else 'LVCMOS33')]:
            lines.append(f'define_attribute {{p:{port}}} {{PAP_IO_{name}}} {{{value}}}')
        if direction=='OUTPUT':
            lines.extend([f'define_attribute {{p:{port}}} {{PAP_IO_DRIVE}} {{4}}',f'define_attribute {{p:{port}}} {{PAP_IO_SLEW}} {{SLOW}}'])
    (cdir/'pins.fdc').write_text('\n'.join(lines)+'\n',encoding='ascii')
    timing='''# Same PLL ratios and physical clock targets as the production image.
create_clock -name sys27 -period 37.037037037 [get_ports sys_clk_27]
create_clock -name ref125 -period 8.000 [get_ports sys_clk_125_p]
create_generated_clock -name audio96 -source [get_ports sys_clk_27] -multiply_by 32 -divide_by 9 [get_pins {clocks.u_pll_96.u_gpll/CLKOUT0}]
create_generated_clock -name audio122 -source [get_pins {clocks.u_pll_96.u_gpll/CLKOUT0}] -multiply_by 32 -divide_by 25 [get_pins {clocks.u_pll_audio.u_gpll/CLKOUT0}]
create_generated_clock -name eth250 -source [get_ports sys_clk_125_p] -multiply_by 2 [get_pins {clocks.u_pll_eth.u_gpll/CLKOUT0}]
create_generated_clock -name eth125 -source [get_pins {clocks.u_pll_eth.u_gpll/CLKOUT0}] -divide_by 2 [get_pins {clocks.u_eth_div/CLKDIVOUT}]
set_clock_uncertainty 0.150 [get_clocks {sys27 ref125 audio96 audio122 eth250 eth125}]
# Registered Gray counters cross to 27 MHz. Bound bus routes below one fastest
# source period; synchronizer-to-synchronizer timing remains fully checked.
'''
    for clk in ('ref125','audio96','audio122','eth125'):
        timing+=f'set_max_delay 7.500 -datapath_only -from [get_clocks {clk}] -to [get_clocks sys27]\n'
        timing+=f'set_false_path -hold -from [get_clocks {clk}] -to [get_clocks sys27]\n'
    timing+='''# UART command creates an asynchronous virtual key in the audio domain.
set_max_delay 7.500 -datapath_only -from [get_clocks sys27] -to [get_clocks audio122]
set_false_path -hold -from [get_clocks sys27] -to [get_clocks audio122]
# UART RX is asynchronous; only the first-stage input is excepted. No exception between synchronizer stages.
set_input_delay -clock sys27 -max 0.000 [get_ports uart_rx]
set_input_delay -clock sys27 -min 0.000 [get_ports uart_rx]
set_false_path -from [get_ports uart_rx]
# LOCK is an asynchronous status. Recovery/removal exceptions target only
# reset-release stages and PLL/divider asynchronous reset controls.
set_false_path -from [get_pins {clocks.u_pll_96.u_gpll/LOCK clocks.u_pll_audio.u_gpll/LOCK clocks.u_pll_eth.u_gpll/LOCK}]
set_false_path -to [get_pins -hierarchical {*release_pipe*/C *release_audio*/C}]
set_false_path -to [get_pins {clocks.u_pll_96.u_gpll/RST clocks.u_pll_audio.u_gpll/RST clocks.u_pll_eth.u_gpll/RST clocks.u_eth_div/RST_N}]
# UART TX pad delay is bounded well below an 8.68 us bit period.
set_output_delay -clock sys27 -max 0.000 [get_ports uart_tx]
set_output_delay -clock sys27 -min 0.000 [get_ports uart_tx]
set_max_delay 20.000 -datapath_only -to [get_ports uart_tx]
set_false_path -hold -to [get_ports uart_tx]
# Four mic clocks and PHY reset are constant low: intentionally no IO delay.
'''
    (cdir/'timing.fdc').write_text(timing,encoding='ascii')
    return pins,[cdir/'pins.fdc',cdir/'timing.fdc']

def sources():
    return [HERE/'rtl/pango_clock_probe.v',HERE/'rtl/clock_observer.sv',HERE/'rtl/uart_clock_diag.sv',HERE/'rtl/uart_8n1.sv',HERE/'rtl/uart_clock_report.sv',
            ROOT/'rtl/net/reset_release.sv',ROOT/'rtl/board_selftest_control.sv']

def snapshot():
    paths=[p for p in HERE.rglob('*') if p.is_file() and p.suffix in ('.py','.sv','.v','.fdc','.do','.bat')]
    paths+=sources()+[ROOT/'rtl/board/pango_board_clocks.v',HERE.parent/'io_map/build.py',HERE.parent/'clock_reset/rtl/clock_observer.sv']
    return {p.relative_to(ROOT).as_posix():sha(p) for p in sorted(set(paths))}

def simulate(args):
    run=ROOT/'log/clock_uart';run.mkdir(parents=True,exist_ok=True)
    library=run/'work';ini=run/'modelsim.ini'
    ini.write_text('[Library]\nwork = '+library.as_posix()+'\n',encoding='ascii')
    modelsim=Path(args.modelsim);vendor=Path(args.pango)/'arch/vendor/pango/verilog/simulation'
    if not library.exists():execute([modelsim/'vlib.exe',library],run/'vlib.log',run)
    primitive=[vendor/(n+'.v') for n in ('GTP_GRS','GTP_DFF','GTP_INBUF','GTP_INBUFDS','GTP_CLKBUFG','GTP_IOCLKDIV_E2','GTP_GPLL')]
    tb=[HERE/'tb/tb_uart_clock.sv',HERE/'tb/tb_uart_protocol.sv']
    all_sources=primitive+sources()+tb
    sim_inputs={str(p):sha(p) for p in all_sources}
    if args.reuse_simulation:
        result=json.loads((run/'result.json').read_text(encoding='utf-8'))
        need(result['status']=='PASS','Previous simulation did not pass')
        need(result['source_sha256']=={str(p):sha(p) for p in all_sources},'Simulation inputs have changed')
        for name,test in result['tests'].items():
            need(sha(run/(name+'.log'))==test['log_sha256'],'Simulation log changed')
        print('[SIM_REUSE_VERIFIED] checks='+str(result['checks']),flush=True)
        return run/'result.json'
    execute([modelsim/'vlog.exe','-modelsimini',ini,'-sv','-lint','-work',library,*all_sources],run/'compile.log',run)
    results={}
    for name in ('tb_uart_protocol','tb_uart_clock'):
        text=execute([modelsim/'vsim.exe','-modelsimini',ini,'-batch','-voptargs=+acc','-t','1fs','-onfinish','exit',
                      '-wlf',run/(name+'.wlf'),'work.'+name,'-do',HERE/'tb_script/run.do'],run/(name+'.log'),run)
        need('[TB_INFO] Simulation Finished!' in text,'Missing simulation success marker')
        results[name]={'checks':int(re.search(r'checks=(\d+)',text)[1]),'log_sha256':sha(run/(name+'.log'))}
    need(sim_inputs=={str(p):sha(p) for p in all_sources},'Simulation source changed while running')
    result={'status':'PASS','completed_at':datetime.now().astimezone().isoformat(),'tests':results,
            'source_sha256':sim_inputs,'checks':sum(v['checks'] for v in results.values())}
    write_json(run/'result.json',result)
    print('[SIM_PASS] checks='+str(result['checks']),flush=True)
    return run/'result.json'

def audit(build,pins):
    dmr=build/'device_map'/(TOP+'.dmr');rtr=build/'report_timing'/(TOP+'.rtr')
    actual={}
    for line in dmr.read_text(encoding='utf-8',errors='replace').splitlines():
        f=[x.strip() for x in line.split('|')]
        if len(f)>=6 and f[2].lower() in ('input','output','inout'):
            need(f[1] not in actual,'Duplicate mapped port')
            actual[f[1]]={'pin':f[3],'direction':f[2].upper(),'voltage':f[4],'standard':f[5]}
    need(set(actual)==set(pins),'Mapped port set mismatch')
    for name,pin in pins.items():
        diff=name.startswith('sys_clk_125')
        expected=dict(pin=pin,direction='INPUT' if (name.startswith('sys_clk') or name=='uart_rx') else 'OUTPUT',
                      voltage='1.5' if diff else '3.3',standard='SSTL15D_I' if diff else 'LVCMOS33')
        need(actual[name]==expected,'Wrong pin assignment: '+name)
    timing=rtr.read_text(encoding='utf-8',errors='replace')
    need('Design Summary : All Constraints Met.' in timing,'Timing constraints not met')
    need('Setup Summary(Slow Corner)' in timing and 'Setup Summary(Fast Corner)' in timing,'Missing timing corners')
    for clk in ('sys27','ref125','audio96','audio122','eth250','eth125'):
        need(re.search(r'\b'+clk+r'\b',timing),'Missing clock '+clk)
    xml=ET.parse(build/'report_timing/rtr.db').getroot()
    issues={r.findtext('data'):int(r.findall('data')[1].text) for r in xml.find("table[@id='check_timing_summary']").findall('row')}
    for name in ('no_clock','loops','latch_loops','latchs','no_input_delay'):
        need(name in issues and issues[name]==0,'Timing check: '+name+'='+str(issues.get(name)))
    need(issues.get('no_output_delay')==5,'Unexpected unconstrained output count')
    # 122.88/27 = 1024/225: the first exact common period exceeds PDS's
    # 1000-cycle expansion search. This observation crossing is Gray/status
    # synchronization, with a physical max-delay bound and false HOLD. It does
    # not depend on a phase-expanded synchronous setup/hold relationship.
    expandable=xml.find(".//table[@id='unexpandable_clocks_detailed_report']")
    details=list(expandable.itertext())
    expected='Can not find common multiples between the source clock audio122 and destination clock sys27  within 1000 cycles.'
    # PDS reports an unordered clock set once, even with crossings in both
    # directions. The actual directional max-delay paths are checked below.
    need(issues['unexpandable_clocks']==1 and expected in details,'Unreviewed unexpandable clock pair')
    cdc={}
    for corner in ('Slow','Fast'):
        block=timing.split(f'Setup Summary({corner} Corner):',1)[1].split('Hold Summary',1)[0]
        for clk in ('ref125','audio96','audio122','eth125'):
            match=re.search(r'^\s*'+clk+r'\s+sys27\s+([\d.-]+)\s+([\d.-]+)\s+(\d+)\s+(\d+)',block,re.M)
            need(match is not None,'Missing bounded CDC timing '+clk)
            wns,tns,fail,endpoints=match.groups()
            need(float(wns)>=0 and float(tns)==0 and int(fail)==0 and int(endpoints)>=16,'CDC timing failed '+clk)
            cdc[corner+'/'+clk]={'wns_ns':float(wns),'endpoints':int(endpoints),'max_datapath_ns':7.5}
        match=re.search(r'^\s*sys27\s+audio122\s+([\d.-]+)\s+([\d.-]+)\s+(\d+)\s+(\d+)',block,re.M)
        need(match is not None,'Missing UART command CDC timing')
        wns,tns,fail,endpoints=match.groups()
        need(float(wns)>=0 and float(tns)==0 and int(fail)==0 and int(endpoints)>=1,'UART command CDC failed')
        cdc[corner+'/sys27_to_audio122']={'wns_ns':float(wns),'endpoints':int(endpoints),'max_datapath_ns':7.5}
    allowed={'virtual_clock':1,'unexpandable_clocks':1,'no_output_delay':5,'io_min_max_delay_consistency':4}
    for name,count in issues.items():
        need(count==allowed.get(name,0),'Unreviewed timing-check notice '+name)
    return {'mapped_ports':actual,'timing_status':'All Constraints Met','check_timing':issues,
            'bounded_cdc_timing':cdc,
            'reviewed_notices':{'unexpandable_clocks':[expected,'Both directional registered Gray/status and virtual-key CDC paths bounded to 7.5 ns; hold excepted.'],
              'virtual_clock':'No virtual clock required: all references are physical/generated clocks.',
              'io_min_max_delay_consistency':'UART RX and TX have equal zero min/max bookkeeping delays; RX asynchronous, TX pad delay separately bounded.'},
            'timing_model':'Pre-silicon' if 'Pre-silicon' in timing else 'see native report',
            'intentional_no_output_delay':['mic_clk[0]','mic_clk[1]','mic_clk[2]','mic_clk[3]','phy_reset_n']}

def build(args,pins,fdcs,sim):
    directory=ROOT/'fpga/build/CLOCK_UART_PFD31';directory.mkdir(parents=True,exist_ok=True)
    for name in ('release.json','manifest.json'):
        p=directory/name
        if p.exists():p.rename(directory/(name+datetime.now().strftime('.%Y%m%d_%H%M%S.bak')))
    pll_validation=ROOT/'log/clock_uart/pll_validation.json'
    inputs=snapshot();manifest={'status':'RUNNING','source_sha256':inputs,'simulation_sha256':sha(sim),'pll_validation_sha256':sha(pll_validation),
                               'started_at':datetime.now().astimezone().isoformat(),'device':'PG2L200H-6-FBB676'}
    write_json(directory/'manifest.json',manifest)
    install=Path(args.pango);env=os.environ.copy()
    if not env.get('PANGO_LICENSE_FILE'):
        licenses=list((install.parent/'license').glob('*.lic'));need(len(licenses)==1,'License not resolved')
        env['PANGO_LICENSE_FILE']=str(licenses[0])
    arch='set_arch -family Logos2 -device PG2L200H -speedgrade -6 -package FBB676'
    script=directory/'build.tcl'
    commands=[arch]+['add_design '+q(p) for p in sources()]+['add_constraint '+q(p) for p in fdcs]
    commands += [f'compile -top_module {TOP} -system_verilog','synthesize -ads -selected_syn_tool_opt 2','dev_map',
                 'pnr -mode performance -fix_hold_violation_in_route TRUE',
                 'report_timing -delay_type min_max -report_io_datasheet -report_exception TRUE -max_path 8']
    script.write_text('\n'.join(commands)+'\n',encoding='utf-8')
    shell=install/'bin/pds_shell.exe'
    try:
        print('[BUILD] CLOCK_UART_PFD31',flush=True)
        text=execute([shell,'-file',script,'-work_dir',directory,'-project_name','CLOCK_UART_PFD31'],directory/'build.log',directory,env)
        for step in ('compile','synthesize','dev_map','pnr','report_timing'):
            need(re.search(r'^Executing : '+step+r'(?: .*)? successfully\.$',text,re.M),step+' not completed')
        checks=audit(directory,pins)
        need(snapshot()==inputs and sha(sim)==manifest['simulation_sha256'],'Source/simulation changed during build')
        routed=directory/'place_route'/(TOP+'_pnr.adf');routed_sha=sha(routed)
        bit_script=directory/'generate_bitstream.tcl'
        bit_script.write_text(arch+'\ngen_bit_stream -create_bit_file TRUE -create_bin_file -persist_pin {Release For USER} -force_to_run -input_db_file '+q(routed)+'\n',encoding='utf-8')
        text=execute([shell,'-file',bit_script,'-work_dir',directory,'-project_name','CLOCK_UART_PFD31_bitstream'],directory/'bitstream.log',directory,env)
        need(re.search(r'^Executing : gen_bit_stream(?: .*)? successfully\.$',text,re.M),'Bitstream did not complete')
        need(sha(routed)==routed_sha and snapshot()==inputs,'Source/routed DB changed')
        evidence={}
        for p in [directory/'generate_bitstream'/(TOP+'.sbit'),directory/'generate_bitstream'/(TOP+'.bin'),
                  directory/'report_timing'/(TOP+'.rtr'),directory/'report_timing/rtr.db',directory/'device_map'/(TOP+'.dmr'),
                  routed,script,bit_script,directory/'build.log',directory/'bitstream.log',sim,
                  pll_validation,ROOT/'log/clock_uart/vendor_pll_check.log',ROOT/'log/clock_uart/validate_vendor_pll.tcl']:
            need(p.is_file() and p.stat().st_size>0,'Missing evidence '+str(p))
            evidence[p.relative_to(ROOT).as_posix()]={'sha256':sha(p),'bytes':p.stat().st_size}
        manifest.update(status='PASS',completed_at=datetime.now().astimezone().isoformat(),sources_unchanged=True)
        write_json(directory/'manifest.json',manifest)
        write_json(directory/'release.json',dict(status='PASS',board_clock_reset_verified=False,source_sha256=inputs,
            manifest_sha256=sha(directory/'manifest.json'),audit=checks,evidence=evidence))
        print('[DIAG_RELEASE_PASS] '+str(directory/'release.json'),flush=True)
    except Exception as exc:
        manifest.update(status='FAIL',error=str(exc));write_json(directory/'manifest.json',manifest);raise

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--pango',default='D:/Application/ElectronicIDE/Pango/PDS_2022.2-SP6.4')
    ap.add_argument('--modelsim',default='D:/Application/ElectronicIDE/Modelsim/2020_4/win64')
    ap.add_argument('--sim-only',action='store_true')
    ap.add_argument('--reuse-simulation',action='store_true',help='Reuse PASS only if every HDL/vendor/TB source and test log hash still matches')
    args=ap.parse_args();pins,fdcs=prepare()
    run=ROOT/'log/clock_uart';run.mkdir(parents=True,exist_ok=True)
    validate_pll(args.pango,run,HERE/'rtl/pango_clock_probe.v')
    sim=simulate(args)
    if not args.sim_only:build(args,pins,fdcs,sim)

if __name__=='__main__':main()
