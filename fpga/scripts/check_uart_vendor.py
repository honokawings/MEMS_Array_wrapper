"""Authenticate required UART GTP gate regression and both routed channel FFs.

The quick gate regression is a real PDS technology netlist simulation, without
SDF. Final board netlists are independently checked after top-level routing.
Neither check claims UART hardware or board timing qualification.
"""
from __future__ import annotations
import argparse,hashlib,importlib.util,json,re
from pathlib import Path
from check_tx_source import parse_cells

ROOT=Path(__file__).resolve().parents[2]
SOURCES=('rtl/diag/uart_audio_control.sv','tb/board/tb_vendor_uart.sv','sim/audio/run_vendor_uart.py')
LOGS=('pds_build.log','vlib.log','vlog.log','vsim.log')
SCHEMA='uart-vendor-and-routed-channel-v1'

class AuditError(ValueError):pass
def need(value,message):
    if not value:raise AuditError(message)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def json_file(path):
    value=json.loads(Path(path).read_text(encoding='utf-8'))
    need(isinstance(value,dict),'UART evidence must be a JSON object');return value
def hashes(values,root=None):
    need(isinstance(values,dict) and values,'Missing UART hashed evidence')
    for name,digest in values.items():
        path=Path(name) if root is None else root/name
        need(path.is_file() and re.fullmatch(r'[0-9a-f]{64}',digest or '') and sha(path)==digest,
            'UART evidence file/hash mismatch: '+name)

def verify_probe(root,path):
    root=Path(root).resolve();path=Path(path).resolve()
    need(path==root/'log/vendor_uart/result.json','UART probe result must be the required regression output')
    result=json_file(path)
    need(result.get('status')=='PASS' and result.get('scope')=='vendor_uart_technology_netlist_functional',
         'Required UART vendor gate regression did not pass')
    need(result.get('sdf_annotated') is False and result.get('placement_routing_tested') is False,
         'UART technology gate scope incorrectly asserts routed timing')
    need(result.get('device')=={'family':'Logos2','device':'PG2L200H','speedgrade':'-6','package':'FBB676'},'UART vendor probe device changed')
    expected={name:sha(root/name) for name in SOURCES}
    need(result.get('sources_sha256')==expected,'UART vendor probe source set/hash changed')
    need(result.get('flow_evidence')==[{'stage':s,'actual_success_marker':True} for s in ('compile','synthesize','dev_map')],
         'UART probe lacks actual compile/synthesis/map completions')
    logs=result.get('raw_logs_sha256',{})
    need(set(logs)=={'log/vendor_uart/'+name for name in LOGS},'UART probe raw log set incomplete')
    hashes(logs,root)
    for name in LOGS:
        text=(root/'log/vendor_uart'/name).read_text(errors='replace')
        need(not re.search(r'^[ \t]*E: |^[ \t]*[ECW]: Internal-|\[TB_ERROR\]|\*\* (?:Error|Fatal)',text,re.M),
             'UART vendor log contains actual failure: '+name)
    text=(root/'log/vendor_uart/pds_build.log').read_text(errors='replace')
    for stage in ('compile','synthesize','dev_map'):
        need(re.search(r'^Executing : '+stage+r'[^\r\n]* successfully\.$',text,re.M),
             'UART actual vendor stage did not complete: '+stage)
    transcript=(root/'log/vendor_uart/vsim.log').read_text(errors='replace')
    match=re.search(r'gate_channels=128 channel_bit_zero_mask=7f channel_bit_one_mask=7f checks=(\d+) lines=(\d+)',transcript)
    need('[TB_INFO] Simulation Finished!' in transcript and match is not None,
         'UART vendor gate lacks all 128 channels and seven-bit transition evidence')
    need(result.get('channels')==128 and result.get('checks')==int(match[1]) and int(match[1])>=1000 and
         result.get('response_lines')==int(match[2]) and int(match[2])==143,'UART vendor gate count mismatch')
    artifacts=result.get('artifacts_sha256',{})
    need(len(artifacts)==4,'UART probe artifact set incomplete')
    hashes(artifacts,root)
    netlists=[root/p for p in artifacts if p.endswith('/synthesize/uart_audio_control_syn.vm')]
    need(len(netlists)==1,'UART probe lacks one real technology netlist')
    build=netlists[0].parents[1]
    expected_artifacts={p.relative_to(root).as_posix() for p in
        (build/'build.tcl',build/'probe_timing.fdc',build/'device_map/uart_audio_control_map.adf',netlists[0])}
    need(set(artifacts)==expected_artifacts and build.parent==root/'fpga/build','UART probe artifact provenance changed')
    flow=(build/'build.tcl').read_text()
    expected_flow=(f'set_arch -family Logos2 -device PG2L200H -speedgrade -6 -package FBB676\n'
        f'add_design {{{(root/SOURCES[0]).as_posix()}}}\nadd_constraint {{{(build/"probe_timing.fdc").as_posix()}}}\n'
        'compile -top_module uart_audio_control -system_verilog\nsynthesize -ads -selected_syn_tool_opt 2 -fanout_guide 256\ndev_map\n')
    need(flow==expected_flow,'UART vendor flow changed or substitutes another source')
    toolhash=result.get('tools_sha256',{})
    need({Path(p).name.lower() for p in toolhash}=={'pds_shell.exe','vlib.exe','vlog.exe','vsim.exe'},'UART tool set incomplete')
    need(len(toolhash)==4,'UART tool set is duplicated')
    hashes(toolhash)
    modelhash=result.get('vendor_models_sha256',{})
    hashes(modelhash)
    runner_path=root/SOURCES[2]
    spec=importlib.util.spec_from_file_location('_uart_vendor_runner_audit',runner_path)
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    cells=runner.parse_cells(netlists[0]);traced=runner.channel_ff_audit(cells)
    need(result.get('desired_channel_ff')==traced,'UART recorded FF trace differs from actual synthesis netlist')
    kinds=sorted({c['kind'] for c in cells.values()})
    need(result.get('primitive_kinds')==kinds,'UART primitive kind evidence changed')
    need({Path(p).stem for p in modelhash}.issuperset(kinds),'UART used incomplete vendor primitive models')
    model_dirs={Path(p).resolve().parent for p in modelhash}
    need(len(model_dirs)==1,'UART vendor models came from mixed libraries')
    model_dir=next(iter(model_dirs));index={p.stem:p for p in model_dir.glob('*.v')}
    required=set(kinds);pending=list(kinds)
    while pending:
        kind=pending.pop();need(kind in index,'UART vendor primitive model is missing')
        for child in re.findall(r'\b(?:GTP|INT)_\w+\b',index[kind].read_text(errors='replace')):
            if child in index and child not in required:required.add(child);pending.append(child)
    need({Path(p).resolve() for p in modelhash}=={index[k].resolve() for k in required},
         'UART vendor model dependency set changed')
    pango=next(Path(p).resolve().parents[1] for p in toolhash if Path(p).name.lower()=='pds_shell.exe')
    need(model_dir==pango/'arch/vendor/pango/verilog/simulation','UART models are not from the recorded PDS installation')
    # Vlog transcript must compile only the vendor models, generated netlist and
    # testbench. Source RTL is never compiled by the gate simulator.
    vlog=(root/'log/vendor_uart/vlog.log').read_text(errors='replace')
    normalized=vlog.replace('\\','/')
    need(str(root/SOURCES[0]).replace('\\','/') not in normalized,
         'UART gate simulator compiled RTL in place of technology netlist')
    expected_inputs={str(Path(p).resolve()).replace('\\','/') for p in modelhash}|{netlists[0].as_posix(),(root/SOURCES[1]).as_posix()}
    actual_inputs={p.strip('"') for p in re.findall(r'(?:"[^"\r\n]+\.(?:v|sv|vm)"|[^ \r\n]+\.(?:v|sv|vm))(?=\s|$)',normalized)}
    need(actual_inputs==expected_inputs,'UART gate compilation inputs differ from the hashed technology netlist/models/TB')
    return {'status':'PASS','scope':result['scope'],'channels':128,'variable_ff_count':7,
            'checks':result['checks'],'response_lines':143,'result_sha256':sha(path),
            'sources_sha256':expected,'artifacts_sha256':artifacts,'raw_logs_sha256':logs,
            'tools_sha256':toolhash,'vendor_models_sha256':modelhash,'desired_channel_ff':traced}

def board_trace(path):
    path=Path(path);cells=parse_cells(path);text=path.read_text(encoding='utf-8')
    pattern=r'\b(V_FF\w+)\s*/\*\s*(g_uart\.diagnostics/control/desired_channel\[(\d+)\]/[^*]+?)\s*\*/\s*#\((.*?)\)\s*(\\\S+|\w+)\s*\((.*?)\);'
    matches=list(re.finditer(pattern,text,re.S));need(len(matches)==7,'Routed board must retain seven desired_channel FFs')
    bits={};constant=lambda net:bool(re.fullmatch(r"\d+'[sbhdSBHD][0-9a-fA-FxzXZ_]+",net or '') or net in {'0','1',''})
    for match in matches:
        kind,semantic,bit,params,name,body=match.groups();bit=int(bit);name=name.lstrip('\\')
        need(bit in range(7) and bit not in bits,'Routed channel FF bit set is not unique')
        cell=cells[name];ports=cell['ports']
        need(kind in {'V_FFSYN','V_FFASYN'} and cell['kind']==kind,'Unreviewed channel FF launch polarity')
        need(all(key in ports for key in ('Q','D','CK','CE','SR')),'Incomplete routed channel FF ports')
        need(not constant(ports['D']) and not constant(ports['Q']) and
             (not constant(ports['CE']) or ports['CE'] in {"1'b1","1'h1",'1'}),
             'Routed channel FF is constant or disabled')
        need(ports['Q']==f'g_uart.diagnostics/desired_channel[{bit}]','Routed channel FF Q lost the actual configuration channel net')
        consumers=[n for n,c in cells.items() if n!=name and ports['Q'] in c['ports'].values()]
        need(consumers,'Routed channel FF Q has no actual logic consumers')
        bits[bit]={'bit':bit,'instance':name,'semantic_source':semantic.strip(),'kind':kind,'ports':ports,'params':cell['params'],'consumer_count':len(consumers)}
    need(set(bits)==set(range(7)) and len({b['instance'] for b in bits.values()})==7,'Routed desired channel FFs are missing or merged')
    clocks={b['ports']['CK'] for b in bits.values()};need(len(clocks)==1,'Routed channel FFs have mixed clock sources')
    net=next(iter(clocks));clock_path=[]
    drivers=[(n,c) for n,c in cells.items() if c['kind']=='V_USCM' and c['ports'].get('CLKOUT')==net]
    need(len(drivers)==1 and drivers[0][1]['params'].get('USCM_MODE')=='"BUF_A"','Channel FFs lack the reviewed ungated global clock buffer')
    name,cell=drivers[0];clock_path.append({'instance':name,'kind':cell['kind'],'ports':cell['ports'],'params':cell['params']});net=cell['ports']['CLK0']
    for _ in range(8):
        # PDS's actual V_BUF primitive is (Z,I), unlike V_IBUF (O,I).
        bufs=[(n,c) for n,c in cells.items() if c['kind']=='V_BUF' and c['ports'].get('Z')==net]
        if not bufs:break
        need(len(bufs)==1,'Ambiguous supervisor clock buffer');name,cell=bufs[0]
        clock_path.append({'instance':name,'kind':cell['kind'],'ports':cell['ports'],'params':cell['params']});net=cell['ports']['I']
    inputs=[(n,c) for n,c in cells.items() if c['kind']=='V_IBUF' and c['ports'].get('O')==net]
    need(len(inputs)==1 and inputs[0][1]['ports'].get('I')=='sys_clk_27','Channel FF physical CK does not originate at sys_clk_27')
    name,cell=inputs[0];clock_path.append({'instance':name,'kind':cell['kind'],'ports':cell['ports'],'params':cell['params']})
    return {'variable_ff_count':7,'bits':[bits[i] for i in range(7)],'clock_path':clock_path,'clock_input':'sys_clk_27'}

def audit(root,paths):
    result={'schema':SCHEMA,'status':'FAIL','scope':'engineering_board_bringup',
        'checker_sha256':sha(__file__),'dependency_sha256':sha(Path(__file__).with_name('check_tx_source.py')),
        'evidence':{key:{'path':str(Path(path).resolve()),'sha256':sha(path)} for key,path in paths.items()}}
    try:
        probe=verify_probe(root,paths['probe_result'])
        corners={c:board_trace(paths[c+'_netlist']) for c in ('slow','fast')}
        need(corners['slow']==corners['fast'],'Slow/fast routed channel FF identities or connections differ')
        for item in result['evidence'].values():need(sha(item['path'])==item['sha256'],'UART raw input changed during audit')
        for key in ('sources_sha256','artifacts_sha256','raw_logs_sha256'):hashes(probe[key],Path(root).resolve())
        for key in ('tools_sha256','vendor_models_sha256'):hashes(probe[key])
        result.update(status='PASS',probe=probe,corners=corners)
    except (ValueError,OSError,KeyError,TypeError,RuntimeError) as error:result['error']=str(error)
    return result

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',type=Path,default=ROOT)
    for key in ('probe-result','slow-netlist','fast-netlist','output'):ap.add_argument('--'+key,type=Path,required=True)
    args=ap.parse_args();paths={k:v for k,v in vars(args).items() if k not in {'root','output'}}
    result=audit(args.root,paths);args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('status','error') if k in result}));return 0 if result['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
