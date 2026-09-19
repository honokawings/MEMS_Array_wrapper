"""Verify BIST PCM and delivery continuity from captured files or RTL payloads.

python lib/host/verify_selftest.py --capture captures/bist --min-frames 48000
python lib/host/verify_selftest.py --payloads log/selftest/payloads.hex --min-frames 96
"""
from __future__ import annotations
import argparse,json,hashlib
from pathlib import Path
try:
    from .pcm_protocol import Packet,Frame,ContinuityTracker,ProtocolError,decode_payload
except ImportError:
    from pcm_protocol import Packet,Frame,ContinuityTracker,ProtocolError,decode_payload


class SelftestVerifier:
    def __init__(self):
        self.oracle=(Path(__file__).with_name('selftest_pcm.bin')).read_bytes()
        if len(self.oracle)!=16*384:raise ProtocolError('Invalid self-test reference length')
        self.tracker=ContinuityTracker()
        self.packets=0;self.frames=0;self.normal_packets=0;self.mismatches=0;self.error_packets=0
        self.first_mismatch=None;self.arrivals={}

    def observe(self,packet,source=('file',0),arrival_ns=None):
        if not packet.flags&16:
            self.normal_packets+=1;return
        self.tracker.observe(packet,source)
        self.packets+=1;self.error_packets+=bool(packet.flags&0x2f)
        if arrival_ns is not None:
            key=(*source,packet.epoch)
            row=self.arrivals.setdefault(key,[arrival_ns,arrival_ns,0])
            row[1]=arrival_ns;row[2]+=1
        for frame in packet.frames:
            self.frames+=1
            offset=(frame.frame_id%16)*384;expected=self.oracle[offset:offset+384]
            if frame.frame_id<96 or frame.pcm!=expected:
                self.mismatches+=1
                if self.first_mismatch is None:
                    channel=next((i//3 for i in range(384) if frame.pcm[i]!=expected[i]),None)
                    self.first_mismatch={'epoch':packet.epoch,'sequence':packet.sequence,
                        'frame_id':frame.frame_id,'channel':channel}

    def result(self,min_frames=48000):
        streams=self.tracker.summary();continuity_errors=0
        for stream in streams:
            for kind in ('packets','frames'):
                continuity_errors+=sum(stream[kind][k] for k in
                    ('missing_observed_range','duplicates','out_of_order','before_capture'))
        rates=[]
        for key,(first,last,count) in self.arrivals.items():
            if last>first and count>1:
                span=(last-first)/1e9
                rates.append({'source_ip':key[0],'source_port':key[1],'epoch':key[2],
                    'observed_span_seconds':span,'packets_per_second':(count-1)/span,
                    'pcm_frames_per_second':3*(count-1)/span,'udp_payload_mbit_per_second':1208*8*(count-1)/span/1e6})
        return {'status':'PASS' if self.frames>=min_frames and not(self.mismatches or self.error_packets or continuity_errors) else 'FAIL',
            'pattern_id':1,'selftest_packets':self.packets,'selftest_frames':self.frames,
            'samples_compared':self.frames*128,'normal_packets_skipped':self.normal_packets,
            'mismatching_frames':self.mismatches,'first_mismatch':self.first_mismatch,
            'error_flag_packets':self.error_packets,'continuity_errors':continuity_errors,
            'minimum_frames':min_frames,'streams':streams,'arrival_rates':rates,
            'oracle_sha256':hashlib.sha256(self.oracle).hexdigest(),
            'rate_note':'PC arrival timing includes OS scheduling; not an FPGA clock frequency measurement'}


def verify_payloads(path,min_frames=48000):
    checker=SelftestVerifier()
    with Path(path).open(encoding='ascii') as f:
        for line in f:
            line=line.split('//')[0].strip()
            if line:checker.observe(decode_payload(bytes.fromhex(line)))
    return checker.result(min_frames)


def verify_capture(prefix,min_frames=48000):
    checker=SelftestVerifier();offset=0
    with Path(str(prefix)+'.pcm24le').open('rb') as pcm, Path(str(prefix)+'.frames.jsonl').open(encoding='utf-8') as meta:
        while True:
            line=meta.readline()
            if not line:break
            rows=[json.loads(line)]
            for _ in range(2):
                line=meta.readline()
                if not line:raise ProtocolError('Truncated three-frame packet metadata')
                rows.append(json.loads(line))
            first=rows[0];frames=[]
            for i,row in enumerate(rows):
                if row['record_in_packet']!=i or row['byte_offset']!=offset:
                    raise ProtocolError('Metadata record/byte offset mismatch')
                if any(row[k]!=first[k] for k in ('epoch','packet_sequence','flags','source_ip','source_port','arrival_monotonic_ns')):
                    raise ProtocolError('Inconsistent metadata within packet')
                data=pcm.read(384)
                if len(data)!=384:raise ProtocolError('Truncated PCM file')
                frames.append(Frame(row['frame_id'],data));offset+=384
            checker.observe(Packet(first['packet_sequence'],first['epoch'],first['flags'],tuple(frames)),
                            (first['source_ip'],first['source_port']),first['arrival_monotonic_ns'])
        if pcm.read(1):raise ProtocolError('Unreferenced trailing PCM bytes')
    result=checker.result(min_frames)
    summary=json.loads(Path(str(prefix)+'.summary.json').read_text(encoding='utf-8'))
    stats=summary.get('capture',{})
    result['host_capture_errors']={key:stats.get(key,0) for key in
        ('host_queue_dropped_packets','invalid_payload_packets','queued_packets_not_saved')}
    if any(result['host_capture_errors'].values()):result['status']='FAIL'
    if summary['saved_pcm_bytes']!=offset:raise ProtocolError('Capture summary length mismatch')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--capture',type=Path);group.add_argument('--payloads',type=Path)
    p.add_argument('--min-frames',type=int,default=48000)
    p.add_argument('--output',type=Path)
    a=p.parse_args()
    if a.min_frames<48:p.error('--min-frames must be >=48 (three complete 16-frame patterns)')
    try:result=verify_capture(a.capture,a.min_frames) if a.capture else verify_payloads(a.payloads,a.min_frames)
    except (OSError,ValueError,KeyError,TypeError) as e:result={'status':'FAIL','error':str(e)}
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if a.output:
        a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(text+'\n',encoding='utf-8')
    print(text)
    raise SystemExit(0 if result['status']=='PASS' else 1)


if __name__=='__main__':main()
