"""Required PDS compile/synthesis/map UART regression against vendor gate models.

No RTL is compiled by ModelSim. A fresh mapped netlist is always generated;
source, tools, models, scripts, netlist and raw logs are hashed in result.json.
This verifies the vendor decimal parser path, not placement/routing timing.
"""
from pathlib import Path
from datetime import datetime
import argparse,hashlib,json,os,re,subprocess,sys,time

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'rtl/diag/uart_audio_control.sv'
TB=ROOT/'tb/board/tb_vendor_uart.sv'
LOG=ROOT/'log/vendor_uart'
DEFAULT_PANGO='D:/Application/ElectronicIDE/Pango/PDS_2022.2-SP6.4'
DEFAULT_MODELSIM='D:/Application/ElectronicIDE/Modelsim/2020_4/win64'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def need(ok,message):
    if not ok:raise RuntimeError(message)
def parse_cells(path):
    text=Path(path).read_text(encoding='utf-8')
    cells={}
    pattern=r'\b((?:V|GTP)_\w+)\s+(?:/\*.*?\*/\s*)?(?:#\((.*?)\)\s*)?(\\\S+|\w+)\s*\((.*?)\);'
    for match in re.finditer(pattern,text,re.S):
        kind,params,name,body=match.groups()
        norm=lambda x:re.sub(r'\s+','',x).lstrip('\\')
        name=name.lstrip('\\')
        need(name not in cells,'Duplicate gate primitive')
        cells[name]={'kind':kind,'ports':{k:norm(v) for k,v in re.findall(r'\.(\w+)\s*\(([^()]*)\)',body)},
            'params':{k:v.strip() for k,v in re.findall(r'\.(\w+)\s*\(([^()]*)\)',params or '')}}
    need(cells,'No vendor gate primitives')
    return cells

def channel_ff_audit(cells):
    traced=[]
    for bit in range(7):
        port=f'desired_channel[{bit}]'
        outputs=[(n,c) for n,c in cells.items() if c['kind'] in {'V_OBUF','GTP_OUTBUF'} and c['ports'].get('O')==port]
        need(len(outputs)==1,f'{port}: expected one physical output buffer')
        output_name,output=outputs[0]
        net=output['ports']['I'];buffers=[]
        for _ in range(8):
            ffs=[(n,c) for n,c in cells.items() if c['kind'] in {'V_FFSYN','V_FFASYN','GTP_DFF_RE'} and c['ports'].get('Q')==net]
            if ffs:break
            bufs=[(n,c) for n,c in cells.items() if c['kind'] in {'V_BUF','GTP_BUF'} and c['ports'].get('O')==net]
            need(len(bufs)==1,f'{port}: not driven by a variable physical FF: {net}')
            name,buf=bufs[0];buffers.append(name);net=buf['ports']['I']
        need(len(ffs)==1,f'{port}: no unique variable FF')
        name,cell=ffs[0]
        need(cell['ports'].get('D') not in {"1'b0","1'b1","1'h0","1'h1"},f'{port}: constant FF D')
        traced.append({'bit':bit,'ff_instance':name,'kind':cell['kind'],'ports':cell['ports'],
            'params':cell['params'],'output_buffer':output_name,'intermediate_buffers':buffers})
    need(len({t['ff_instance'] for t in traced})==7,'Channel FFs are merged')
    return traced

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pango',default=os.getenv('PANGO_INSTALL',DEFAULT_PANGO))
    ap.add_argument('--modelsim',default=os.getenv('MODELSIM_BIN',DEFAULT_MODELSIM))
    ap.add_argument('--build-name',default='uart_audio_vendor_probe_20261009')
    args=ap.parse_args()
    need(re.fullmatch(r'[A-Za-z0-9_-]+',args.build_name),'Invalid build name')
    build=ROOT/'fpga/build'/args.build_name
    build.mkdir(parents=True,exist_ok=True);LOG.mkdir(parents=True,exist_ok=True)
    install=Path(args.pango);modelsim=Path(args.modelsim);shell=install/'bin/pds_shell.exe'
    models=install/'arch/vendor/pango/verilog/simulation'
    need(shell.is_file(),'PDS shell unavailable')
    env=os.environ.copy()
    if not env.get('PANGO_LICENSE_FILE'):
        licenses=list((install.parent/'license').glob('*.lic'))
        need(len(licenses)==1,'Set PANGO_LICENSE_FILE')
        env['PANGO_LICENSE_FILE']=str(licenses[0])
    before={p.relative_to(ROOT).as_posix():sha(p) for p in (SOURCE,TB,Path(__file__))}
    result={'status':'RUNNING','scope':'vendor_uart_technology_netlist_functional','started_at':datetime.now().astimezone().isoformat(),
        'sources_sha256':before,'device':{'family':'Logos2','device':'PG2L200H','speedgrade':'-6','package':'FBB676'},
        'sdf_annotated':False,'placement_routing_tested':False,'flow_evidence':[]}
    result_path=LOG/'result.json'
    result_path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    begin=time.monotonic()
    def run(command,cwd,log,timeout=300,pds_stages=()):
        with log.open('w',encoding='utf-8') as out:
            proc=subprocess.run([str(x) for x in command],cwd=cwd,env=env,stdout=out,stderr=subprocess.STDOUT,timeout=timeout)
        text=log.read_text(encoding='utf-8',errors='replace')
        need(proc.returncode==0 and not re.search(r'^[ \t]*E: |^[ \t]*[ECW]: Internal-|\[TB_ERROR\]|\*\* (?:Error|Fatal)',text,re.M),f'Failed: {log}')
        for stage in pds_stages:
            need(re.search(r'^Executing : '+stage+r'[^\r\n]* successfully\.$',text,re.M),f'No actual completion: {stage}')
        return text
    try:
        timing=build/'probe_timing.fdc'
        timing.write_text('create_clock -name probe_sys -period 37.037 [get_ports {clk}]\n',encoding='ascii')
        flow=build/'build.tcl'
        flow.write_text(f'set_arch -family Logos2 -device PG2L200H -speedgrade -6 -package FBB676\nadd_design {{{SOURCE.as_posix()}}}\nadd_constraint {{{timing.as_posix()}}}\ncompile -top_module uart_audio_control -system_verilog\nsynthesize -ads -selected_syn_tool_opt 2 -fanout_guide 256\ndev_map\n',encoding='utf-8')
        print('[RUN] PDS UART compile/synthesize/dev_map',flush=True)
        run([shell,'-file',flow,'-work_dir',build,'-project_name','UART_VENDOR_PROBE'],build,LOG/'pds_build.log',pds_stages=('compile','synthesize','dev_map'))
        mapped=build/'device_map/uart_audio_control_map.adf';need(mapped.is_file(),'Mapped database absent')
        # PDS gen_netlist only accepts a routed PNR database. Its actual
        # synthesis output is already a GTP technology netlist; simulate that
        # unmodified output with the installed vendor models, after dev_map.
        netlist=build/'synthesize/uart_audio_control_syn.vm'
        need(netlist.is_file(),'Technology simulation netlist absent')
        cells=parse_cells(netlist)
        result['desired_channel_ff']=channel_ff_audit(cells)
        kinds=sorted({c['kind'] for c in cells.values()})
        # LUT and RAM primitives instantiate vendor UDP/mux submodels. Resolve
        # their real installed files recursively; never stub missing models.
        model_index={p.stem:p for p in models.glob('*.v')}
        required=set(kinds);pending=list(kinds)
        while pending:
            kind=pending.pop();need(kind in model_index,f'Vendor primitive model absent: {kind}')
            for child in re.findall(r'\b(?:GTP|INT)_\w+\b',model_index[kind].read_text(errors='replace')):
                if child in model_index and child not in required:required.add(child);pending.append(child)
        libraries=[model_index[kind] for kind in sorted(required)]
        need(all(p.is_file() for p in libraries),'Vendor primitive model absent')
        work=build/'modelsim_work';ini=build/'modelsim.ini'
        ini.write_text('[Library]\nwork = '+work.as_posix()+'\n',encoding='ascii')
        run([modelsim/'vlib.exe',work],build,LOG/'vlib.log')
        run([modelsim/'vlog.exe','-modelsimini',ini,'-sv','-work','work',*libraries,netlist,TB],build,LOG/'vlog.log')
        print('[RUN] vendor gate all 128 channels and rejection/gain/OFF cases',flush=True)
        transcript=run([modelsim/'vsim.exe','-modelsimini',ini,'-batch','-voptargs=+acc','-t','1ps','-onfinish','exit','-wlf',LOG/'vendor_uart.wlf','work.tb_vendor_uart','-do','onerror {quit -f -code 1}; onbreak {quit -f -code 1}; run -all; quit -f -code 0'],build,LOG/'vsim.log')
        need('[TB_INFO] Simulation Finished!' in transcript,'Simulation completion marker missing')
        match=re.search(r'gate_channels=128 channel_bit_zero_mask=7f channel_bit_one_mask=7f checks=(\d+) lines=(\d+)',transcript)
        need(match is not None,'All-channel physical behavior evidence absent')
        after={p.relative_to(ROOT).as_posix():sha(p) for p in (SOURCE,TB,Path(__file__))}
        need(before==after,'Source changed during vendor UART verification')
        result.update(status='PASS',channels=128,checks=int(match[1]),response_lines=int(match[2]),
            primitive_kinds=kinds,tools_sha256={str(p):sha(p) for p in (shell,modelsim/'vlib.exe',modelsim/'vlog.exe',modelsim/'vsim.exe')},
            vendor_models_sha256={str(p):sha(p) for p in libraries},
            artifacts_sha256={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in (flow,timing,mapped,netlist)},
            raw_logs_sha256={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in (LOG/'pds_build.log',LOG/'vlib.log',LOG/'vlog.log',LOG/'vsim.log')})
        result['flow_evidence']=[{'stage':s,'actual_success_marker':True} for s in ('compile','synthesize','dev_map')]
    except Exception as exc:
        result.update(status='FAIL',error=str(exc));raise
    finally:
        result.update(seconds=round(time.monotonic()-begin,3),completed_at=datetime.now().astimezone().isoformat())
        result_path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(f"[PASS] vendor_uart {result['channels']} channels, seven variable FFs, {result['checks']} checks; {result['seconds']:.3f}s",flush=True)

if __name__=='__main__':main()
