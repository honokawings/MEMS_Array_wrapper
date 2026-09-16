"""Generate gain/DC settings from *uncalibrated*, unclipped PCM recordings.

Usage: python calibration.py --silence quiet.npy --tone common_tone.npy
    --frequency 1000 --reference 0 --output doc/calibration/measured
Input arrays: shape (samples,128), signed 24-bit PCM stored in int32.
"""
from common import *
import argparse,json


def estimate(silence,tone,frequency,reference=0):
    for name,a in [('silence',silence),('tone',tone)]:
        if a.ndim!=2 or a.shape[1]!=128 or len(a)<1024:
            raise ValueError(name+' must contain at least 1024 samples x 128 channels')
        if not np.issubdtype(a.dtype,np.integer) or np.any(a<=-2**23) or np.any(a>=2**23-1):
            raise ValueError(name+' must be integer PCM without full-scale clipping')
    if not 20<=frequency<=16000 or not 0<=reference<128:
        raise ValueError('Invalid reference channel or calibration frequency')
    dc=silence.mean(axis=0)/2**23
    t=np.arange(len(tone))/FS_PCM
    basis=np.column_stack((np.cos(2*np.pi*frequency*t),np.sin(2*np.pi*frequency*t),np.ones(len(t))))
    fit=np.linalg.lstsq(basis,tone/2**23,rcond=None)[0]
    phasor=fit[0]-1j*fit[1]
    amp=np.abs(phasor)
    if np.any(amp<1e-5):raise ValueError('Calibration tone is too weak on at least one channel')
    gains=amp[reference]/amp
    if np.any(gains>=2):raise ValueError('Required gain exceeds the Q2.22 range; inspect hardware or reference')
    gain_q=np.floor(gains*2**22+.5).astype(np.int64)
    if np.any(gain_q>=2**23):
        raise ValueError('Gain rounds outside signed 24-bit Q2.22; choose a lower-gain reference')
    offset_q=np.where(dc<0,-np.floor(-dc*2**30+.5),np.floor(dc*2**30+.5)).astype(np.int64)
    # Phase is diagnostic only: one tone cannot identify arbitrary wideband delay.
    phases=np.angle(phasor/phasor[reference])
    return gain_q,offset_q,phases


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--silence',required=True)
    ap.add_argument('--tone',required=True)
    ap.add_argument('--frequency',type=float,required=True)
    ap.add_argument('--reference',type=int,default=0)
    ap.add_argument('--output',required=True)
    a=ap.parse_args()
    gain,offset,phase=estimate(np.load(a.silence,allow_pickle=False),np.load(a.tone,allow_pickle=False),a.frequency,a.reference)
    prefix=Path(a.output);prefix.parent.mkdir(parents=True,exist_ok=True)
    np.savetxt(prefix.with_suffix('.txt'),np.column_stack((gain,offset)),fmt='%d')
    data={'frequency_hz':a.frequency,'reference_channel':a.reference,
        'phase_scope':'Single-tone phase diagnostic only; no wideband delay correction applied.',
        'channels':[{'channel':c,'data_wire':c//2,'lr':'GND' if c%2==0 else 'VDD',
            'gain_q22':int(gain[c]),'offset_q30':int(offset[c]),'measured_phase_deg':float(phase[c]*180/np.pi)}
            for c in range(128)]}
    prefix.with_suffix('.json').write_text(json.dumps(data,indent=2)+'\n')
    print('[MODEL_INFO] Calibration exported; apply while enable=0, then restart acquisition')


if __name__=='__main__':main()
