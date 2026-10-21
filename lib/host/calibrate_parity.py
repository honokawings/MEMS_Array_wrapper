"""Measure fixed R/L gain from uncalibrated M128 common-field captures.

Use receive_pcm.py output prefixes for --tone and --silence. Both captures
must use unity parity/per-channel gains, the same wiring and microphone power.
The tone capture must expose every pair to a known equal-amplitude sound field.
This tool writes a proposal; it never configures hardware or changes the ROM.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import median

CHANNELS=128
FRAME_BYTES=384
UNITY_Q22=1 << 22


def capture_statistics(prefix: Path, settle_frames: int=96, minimum_frames: int=1024) -> dict:
    """Read signed PCM with metadata; skip faults, rails and startup after gaps."""
    pcm_path=Path(str(prefix)+'.pcm24le')
    metadata_path=Path(str(prefix)+'.frames.jsonl')
    size=pcm_path.stat().st_size
    if not size or size % FRAME_BYTES:
        raise ValueError(f'{pcm_path}: incomplete 128-channel PCM frame')
    sums=[0]*CHANNELS;squares=[0]*CHANNELS;clipped=[False]*CHANNELS
    accepted=total=0;previous=None;settle=settle_frames;skipped={}
    digest=hashlib.sha256()
    with pcm_path.open('rb') as pcm,metadata_path.open(encoding='utf-8') as metadata:
        for line in metadata:
            row=json.loads(line)
            raw=pcm.read(FRAME_BYTES)
            if len(raw)!=FRAME_BYTES or row.get('byte_offset')!=total*FRAME_BYTES:
                raise ValueError('PCM/metadata count or byte_offset mismatch')
            digest.update(raw);total+=1
            for field in ('epoch','frame_id','flags'):
                if type(row.get(field)) is not int:
                    raise ValueError(f'Metadata {field} must be an integer')
            flags=row['flags']
            if not 0<=flags<=0x3f or (flags & 0x20 and not flags & 0x10):
                raise ValueError('Invalid M128 flags in capture metadata')
            if type(row.get('source_ip')) is not str or type(row.get('source_port')) is not int:
                raise ValueError('Missing source identity in capture metadata')
            if not 0<=row['frame_id']<1 << 64 or not 0<=row['epoch']<1 << 32:
                raise ValueError('Frame id or epoch outside protocol range')
            identity=(row['source_ip'],row['source_port'],row['epoch'],row['frame_id'])
            continuous=previous is not None and identity[:3]==previous[:3] and identity[3]==((previous[3]+1)&((1 << 64)-1))
            if not continuous:settle=settle_frames
            previous=identity
            samples=[int.from_bytes(raw[i:i+3],'little',signed=True) for i in range(0,FRAME_BYTES,3)]
            rails=[c for c,x in enumerate(samples) if x in (-(1 << 23),(1 << 23)-1)]
            for c in rails:clipped[c]=True
            reason=None
            if flags:reason='fault_or_selftest_flags'
            elif row.get('frame_status') in ('duplicate','out_of_order','before_capture'):reason='non_forward_frame'
            elif rails:reason='full_scale_samples'
            elif settle:reason='settling_after_start_or_gap'
            if settle:settle-=1
            if reason:
                skipped[reason]=skipped.get(reason,0)+1
                continue
            accepted+=1
            for c,x in enumerate(samples):sums[c]+=x;squares[c]+=x*x
        if pcm.read(1):raise ValueError('PCM contains frames missing from metadata')
    if accepted<minimum_frames:
        raise ValueError(f'{prefix}: only {accepted} clean settled frames; need {minimum_frames}')
    # Integer numerators avoid subtracting nearly equal floating-point DC terms.
    variance=[max(0,(accepted*squares[c]-sums[c]*sums[c])/(accepted*accepted)) for c in range(CHANNELS)]
    return {'prefix':str(prefix),'frames_total':total,'frames_used':accepted,'skipped':skipped,
            'pcm_sha256':digest.hexdigest(),'metadata_sha256':hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
            'dc_pcm':[s/accepted for s in sums],'variance_pcm':variance,
            'clipped_channels':[c for c in range(CHANNELS) if clipped[c]]}


def estimate(tone: dict, silence: dict, minimum_snr_db: float=20.0,
             minimum_rms_dbfs: float=-80.0, minimum_pairs: int=64,
             pair_tolerance_db: float=0.5) -> dict:
    """Estimate odd/even amplitude ratio with a robust median across DATA pairs."""
    floor=(10**(minimum_rms_dbfs/20)*(1 << 23))**2
    clipped=set(tone['clipped_channels'])|set(silence['clipped_channels'])
    pairs=[];logs=[]
    for pair in range(64):
        e=2*pair;o=e+1
        signal=[max(0.0,tone['variance_pcm'][c]-silence['variance_pcm'][c]) for c in (e,o)]
        noise=[silence['variance_pcm'][c] for c in (e,o)]
        # null means a zero measured noise power (not an invented finite SNR).
        snr=[10*math.log10(s/n) if s>0 and n>0 else None for s,n in zip(signal,noise)]
        rejection=None
        if e in clipped or o in clipped:rejection='channel_clipped_in_capture'
        elif min(signal)<floor:rejection='signal_below_rms_floor'
        elif any(s<=0 or (n>0 and 10*math.log10(s/n)<minimum_snr_db) for s,n in zip(signal,noise)):
            rejection='insufficient_signal_to_noise'
        row={'data_wire':pair,'even_channel':e,'odd_channel':o,
             'even_lr':'GND','odd_lr':'VDD','signal_rms_pcm':[math.sqrt(s) for s in signal],
             'snr_db':snr,'accepted':rejection is None,'rejection':rejection}
        if rejection is None:
            ratio=math.sqrt(signal[1]/signal[0])
            row['odd_over_even']=ratio;logs.append(math.log(ratio))
        pairs.append(row)
    if len(logs)<minimum_pairs:
        raise ValueError(f'Only {len(logs)} clean adequately excited pairs; need {minimum_pairs}')
    ratio=math.exp(median(logs))
    # Attenuate only the stronger group: preserve headroom and the Q2.22 range.
    even_gain=min(1.0,ratio);odd_gain=min(1.0,1.0/ratio)
    eq=int(math.floor(even_gain*UNITY_Q22+0.5));oq=int(math.floor(odd_gain*UNITY_Q22+0.5))
    if not 0<eq<=UNITY_Q22 or not 0<oq<=UNITY_Q22:
        raise ValueError('Required attenuation rounds to zero; inspect hardware and calibration field')
    residuals=[]
    for row in pairs:
        if row['accepted']:
            residual=20*math.log10(row['odd_over_even']*oq/eq)
            row['predicted_odd_over_even_residual_db']=residual;residuals.append(residual)
    maximum=max(abs(x) for x in residuals)
    return {'status':'PASS' if maximum<=pair_tolerance_db else 'NEEDS_PER_CHANNEL_CALIBRATION',
            'scope':'Coefficient proposal from declared uniform acoustic field; requires independent post-configuration capture.',
            'method':'median log ratio of DC-removed, noise-power-subtracted paired RMS; attenuate stronger parity',
            'valid_pairs':len(logs),'required_pairs':minimum_pairs,'odd_over_even_median':ratio,
            'even_gain_q22':eq,'odd_gain_q22':oq,'even_gain':eq/UNITY_Q22,'odd_gain':oq/UNITY_Q22,
            'pair_tolerance_db':pair_tolerance_db,'maximum_predicted_pair_residual_db':maximum,
            'median_predicted_residual_db':median(residuals),'pairs':pairs,
            'minimum_snr_db':minimum_snr_db,'minimum_rms_dbfs':minimum_rms_dbfs,
            'hardware_configured':False,'independent_post_calibration_verified':False}


def main(argv: list[str] | None=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tone',type=Path,required=True,help='uncalibrated common-field capture prefix')
    parser.add_argument('--silence',type=Path,required=True,help='uncalibrated quiet capture prefix')
    parser.add_argument('--output',type=Path,required=True,help='new JSON proposal file; will not overwrite')
    parser.add_argument('--known-common-field',action='store_true',required=True,
                        help='declare equal acoustic amplitude across each DATA pair and unity gains in both captures')
    parser.add_argument('--settle-frames',type=int,default=96)
    parser.add_argument('--minimum-frames',type=int,default=1024)
    parser.add_argument('--minimum-snr-db',type=float,default=20)
    parser.add_argument('--minimum-rms-dbfs',type=float,default=-80)
    parser.add_argument('--minimum-pairs',type=int,default=64)
    parser.add_argument('--pair-tolerance-db',type=float,default=0.5)
    args=parser.parse_args(argv)
    if args.settle_frames<0 or args.minimum_frames<2 or not 1<=args.minimum_pairs<=64:
        parser.error('invalid frame/pair limit')
    if not all(math.isfinite(x) for x in (args.minimum_snr_db,args.minimum_rms_dbfs,args.pair_tolerance_db)) or args.pair_tolerance_db<=0:
        parser.error('thresholds must be finite and tolerance must be positive')
    if args.output.exists():parser.error('output already exists')
    try:
        tone=capture_statistics(args.tone,args.settle_frames,args.minimum_frames)
        silence=capture_statistics(args.silence,args.settle_frames,args.minimum_frames)
        report=estimate(tone,silence,args.minimum_snr_db,args.minimum_rms_dbfs,args.minimum_pairs,args.pair_tolerance_db)
        report.update({'tone_capture':tone,'silence_capture':silence,
                       'declared_assumptions':{'known_equal_amplitude_pair_field':True,'unity_parity_and_channel_gains':True}})
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x',encoding='utf-8') as out:json.dump(report,out,ensure_ascii=False,indent=2,allow_nan=False);out.write('\n')
    except (ValueError,OSError) as exc:parser.error(str(exc))
    print(json.dumps({key:report[key] for key in ('status','valid_pairs','even_gain_q22','odd_gain_q22','maximum_predicted_pair_residual_db')},indent=2))
    return 0 if report['status']=='PASS' else 2


if __name__=='__main__':raise SystemExit(main())
