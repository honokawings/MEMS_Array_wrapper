"""Fail-closed PCM5102 pad budget from actual same-route PDS netlists/SDF.

PCM5102 SLAS764B p13 requires 8 ns DIN/LRCK setup/hold; this project enforces
20 ns. External wiring/edge uncertainty is an additional 20 ns contract.
PASS covers engineering bring-up only; it does not certify physical DAC wiring.
"""
from pathlib import Path
import argparse
from datetime import datetime
import hashlib
import json
import re
from check_tx_source import parse_cells,parse_sdf

PORTS=('i2s_sck','i2s_bck','i2s_din','i2s_lrck')
BOUNDS={'i2s_sck':4.0,'i2s_bck':4.0,'i2s_din':20.0,'i2s_lrck':20.0}
TI_SOURCE='https://www.ti.com/lit/ds/symlink/pcm5102.pdf'


def need(condition,message):
    if not condition:raise ValueError(message)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def contract(constraints,rtl):
    lines=[' '.join(x.split()) for x in Path(constraints).read_text().splitlines() if x.strip() and not x.lstrip().startswith('#')]
    reviewed=[]
    for port,bound in BOUNDS.items():
        expected=[f'set_output_delay -clock audio122 -max 0.000 [get_ports {port}]',
                  f'set_output_delay -clock audio122 -min 0.000 [get_ports {port}]',
                  f'set_max_delay {bound:.3f} -datapath_only -to [get_ports {port}]',
                  f'set_false_path -hold -to [get_ports {port}]']
        need(all(lines.count(line)==1 for line in expected),'Missing or changed I2S physical constraint: '+port)
        reviewed.extend(expected)
    actual=[line for line in lines if 'i2s_' in line]
    need(sorted(actual)==sorted(reviewed),'Unreviewed I2S clock/exception/constraint command')
    need(lines.count('set_clock_uncertainty 0.150 [get_clocks {sys27 ref125 eth250 eth125 rx125 audio96 audio122}]')==1,
         'I2S budget requires original audio clock uncertainty')
    text=re.sub(r'/\*.*?\*/|//[^\n]*','',Path(rtl).read_text(),flags=re.S)
    compact=re.sub(r'\s+','',text)
    need(re.findall(r'always\s*@\s*\(\s*([^)]*)\)',text)==['posedge clk','posedge clk'],
         'I2S logic/monitor must launch on the positive audio clock edge only')
    for signature in ('if(sck_half==4)beginsck_half<=0;i2s_sck<=!i2s_sck;end',
                      'if(bck_half==19)beginbck_half<=0;i2s_bck<=!i2s_bck;end',
                      'wirefalling_bck=bck_half==19&&i2s_bck;',
                      'if(falling_bck)begin',
                      'slot_index<=slot_index+1\'b1;',
                      'if(slot_index==0)begin','elseif(slot_index==32)begin'):
        need(compact.count(signature)==1,'I2S RTL divider/edge contract changed: '+signature)
    need(re.search(r'reg\s+\[5:0\]\s+slot_index\s*;',text),'I2S stereo frame must contain 64 slots')
    # Extract the actual falling-edge begin/end block, including nested branches.
    begin=compact.index('if(falling_bck)begin')+len('if(falling_bck)')
    tokens=list(re.finditer(r'begin|end',compact[begin:]));depth=0;finish=None
    for token in tokens:
        depth+=1 if token[0]=='begin' else -1
        if depth==0:finish=begin+token.end();break
    need(finish is not None,'Malformed I2S falling-edge block')
    falling=compact[begin:finish]
    for port in ('i2s_din','i2s_lrck'):
        assignments=re.findall(re.escape(port)+r'<=([^;]+);',compact)
        edge_assignments=re.findall(re.escape(port)+r'<=([^;]+);',falling)
        need(len(assignments)==len(edge_assignments)+1,'I2S data changes outside falling BCK: '+port)
        need(assignments[0]==('0' if port=='i2s_din' else '1'),'I2S reset state changed')
    return {'audio_clock_hz':122880000,'sck_period_cycles':10,'bck_period_cycles':40,
            'lrck_period_cycles':2560,'data_launch_to_bck_rise_cycles':20,
            'pcm5102_minimum_setup_hold_ns':8.0,'enforced_setup_hold_ns':20.0,
            'external_relative_delay_and_edge_budget_ns':20.0,'uncertainty_ns':0.300,
            'datasheet':TI_SOURCE+'#page=13'}


def trace_outputs(cells,delays):
    def driver(net,allowed):
        found=[(name,c,port) for name,c in cells.items() for port in allowed.get(c['kind'],()) if c['ports'].get(port)==net]
        need(len(found)==1,'Unknown or ambiguous physical driver: '+net)
        return found[0]
    def arc(name,key):
        need(name in delays and delays[name]['kind']==cells[name]['kind'],'I2S SDF/netlist cell mismatch: '+name)
        need(key in delays[name]['delays'],'Missing I2S SDF arc: '+name+' '+str(key))
        values=delays[name]['delays'][key]
        need(all(0<=v<1000 for v in values),'Negative/nonfinite/excessive I2S arc delay')
        return values
    # These actual PDS primitives launch on positive CK; any other/inverted
    # primitive requires a new clock polarity budget and is rejected.
    ffs={'V_FFSYN':('Q',),'V_FFASYN':('Q',)}
    allowed={**ffs,'V_BUF':('Z',)}
    def launch_for_port(port):
        pad_name,pad,_=driver(port,{'V_OBUF':('O',),'V_OBUFT':('O',)})
        need(pad['ports'].get('T',"1'b0")=="1'b0",'I2S output may be tristated: '+port)
        pairs=[arc(pad_name,('PORT','I')),arc(pad_name,('IOPATH','I','O'))]
        net=pad['ports']['I'];visited=set();buffers=[]
        while True:
            name,cell,_=driver(net,allowed)
            need(name not in visited,'Cycle in I2S output connectivity');visited.add(name)
            if cell['kind']!='V_BUF':break
            buffers.append(name);pairs.extend((arc(name,('PORT','I')),arc(name,('IOPATH','I','Z'))));net=cell['ports']['I']
        pairs.append(arc(name,('IOPATH','CK','Q')))
        branch=arc(name,('PORT','CK'))[0]
        pad_delay=[sum(pair[e] for pair in pairs) for e in (0,1)]
        return {'port':port,'pad_cell':pad_name,'launch_ff':name,'launch_primitive':cell['kind'],
                'clock_net':cell['ports']['CK'],'clock_branch_ns':branch,'output_buffers':buffers,
                'ff_to_pad_rise_ns':pad_delay[0],'ff_to_pad_fall_ns':pad_delay[1],
                'global_clock_output_to_pad_upper_ns':branch+max(pad_delay),
                'physical_lower_bound_ns':0.0}
    mic=launch_for_port('mic_clk[0]')
    outputs={port:launch_for_port(port) for port in PORTS}
    clock_nets={item['clock_net'] for item in outputs.values()}|{mic['clock_net']}
    need(len(clock_nets)==1,'I2S pads and PDM source do not share the audio clock net')
    clock_net=next(iter(clock_nets))
    name,buffer,_=driver(clock_net,{'V_USCM':('CLKOUT',)})
    need(buffer['params'].get('USCM_MODE')=='"BUF_A"','I2S audio clock buffer is not the reviewed ungated BUF_A')
    return {'clock_net':clock_net,'global_clock_buffer':name,'mic_reference_launch_ff':mic['launch_ff'],'outputs':outputs}


def audit(paths):
    result={'schema':'i2s-routed-budget-v1','status':'FAIL','scope':'engineering_board_bringup',
            'unconditional_board_qualification':False,'generated_at':datetime.now().astimezone().isoformat(),
            'checker_sha256':sha(__file__),'dependency_sha256':sha(Path(__file__).with_name('check_tx_source.py')),
            'evidence':{}}
    try:
        result['evidence']={k:{'path':str(v.resolve()),'sha256':sha(v)} for k,v in paths.items()}
        cfg=contract(paths['constraints'],paths['rtl'])
        result['contract']=cfg
        report=paths['timing_report'].read_text()
        need('Design Summary : All Constraints Met.' in report,'I2S requires complete passing routed timing report')
        need(any(abs(float(v))>=0.300-0.001 for v in re.findall(r'clock uncertainty\s+([\d.+-]+)',report)),
             'Missing original detailed timing uncertainty')
        corners={};baseline=None;period=1e9/cfg['audio_clock_hz']
        for corner in ('slow','fast'):
            header=paths[corner+'_sdf'].read_text()[:250]
            need(corner.title()+' Corner' in header,'Mismatched I2S SDF corner label')
            cells=parse_cells(paths[corner+'_netlist']);delays=parse_sdf(paths[corner+'_sdf'])
            need(baseline is None or baseline==cells,'I2S slow and fast netlists describe different routed circuits');baseline=cells
            data=trace_outputs(cells,delays)
            for port,item in data['outputs'].items():
                need(max(item['ff_to_pad_rise_ns'],item['ff_to_pad_fall_ns'])<=BOUNDS[port]+0.001,
                     'I2S real routed FF-to-pad bound exceeded: '+port)
            bck_upper=data['outputs']['i2s_bck']['global_clock_output_to_pad_upper_ns']
            data['receiver_margins']={}
            for port in ('i2s_din','i2s_lrck'):
                upper=data['outputs'][port]['global_clock_output_to_pad_upper_ns']
                # OCV lower bounds are zero, never a scalar SDF value claimed as
                # a silicon minimum. Shared global-buffer insertion cancels.
                setup=20*period-upper-20.0-0.300-20.0-0.001
                hold=20*period-bck_upper-20.0-0.300-20.0-0.001
                need(setup>0 and hold>0,'I2S external setup/hold budget exhausted: '+port)
                data['receiver_margins'][port]={'setup_remaining_ns':setup,'hold_remaining_ns':hold}
            data['clock_pulse_margins']={}
            for port,half_cycles,minimum in (('i2s_sck',5,9.0),('i2s_bck',20,16.0)):
                item=data['outputs'][port]
                # The identical positive CK branch cancels between this FF's
                # consecutive launches; allow full FF/pad asymmetry plus the
                # stated external edge and uncertainty budget.
                width=half_cycles*period-max(item['ff_to_pad_rise_ns'],item['ff_to_pad_fall_ns'])-20.0-0.300-0.001
                need(width>minimum,'I2S external clock pulse budget exhausted: '+port)
                data['clock_pulse_margins'][port]={'high_low_width_lower_ns':width,'device_minimum_ns':minimum,'remaining_ns':width-minimum}
            corners[corner]=data
        result.update(status='PASS',corners=corners,
            qualification='Physical wiring, receiver 3.3 V supply and <=20 ns relative propagation/edge budget remain unmeasured.')
    except (OSError,ValueError,KeyError,TypeError) as error:result['error']=str(error)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('timing-report','constraints','rtl','slow-sdf','slow-netlist','fast-sdf','fast-netlist','output'):
        parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();paths={k:v for k,v in vars(args).items() if k!='output'}
    result=audit(paths);args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    print(json.dumps({k:result[k] for k in ('status','error') if k in result}));return 0 if result['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
