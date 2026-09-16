"""Deterministic adversarial vectors, cross-checked by independent integer models."""
from common import *
import fixed
import subprocess
import json


def write_hex(path, values, bits):
    mask = (1 << bits)-1
    path.write_text(''.join(''.join(f'{int(v)&mask:0{bits//4}x}' for v in row[::-1])+'\n'
                            for row in np.asarray(values)))


def main():
    out = ROOT/'tb/vectors'
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(0x72D128)
    n = 16384
    t = np.arange(n)/FS_PDM
    pdm = rng.integers(0, 2, (n,CHANNELS), dtype=np.uint8)
    pdm[:,0]=1
    pdm[:,1]=0
    pdm[:,2]=np.arange(n)%2
    pdm[:,3]=1-pdm[:,2]
    pdm[:,4]=(np.arange(n)%17 < 12)
    pdm[:,5]=(np.arange(n)//257)%2
    pdm[:,9]=pdm[:,8]
    e1=np.zeros(16)
    e2=np.zeros(16)
    for k in range(n):
        x=.30*np.sin(2*np.pi*(1000+np.arange(16)*719)*t[k]+np.arange(16)*.13)
        u=x-2*e1+e2
        y=np.where(u>=0,1.,-1.)
        e2=e1.copy()
        e1=y-u
        pdm[k,16:32]=(y>0)
    gains=np.full(CHANNELS,1<<22,dtype=np.int64)
    offsets=np.zeros(CHANNELS,dtype=np.int64)
    gains[0]=(1<<23)-1
    gains[1]=(1<<23)-1
    gains[32:48]=1<<21
    gains[48:64]=-(1<<22)
    gains[127]=0
    offsets[64:80]=np.arange(16)*17321-120000
    np.savetxt(out/'calibration.txt',np.column_stack((gains,offsets)),fmt='%d')
    write_hex(out/'calibration.hex', ((gains & 0xffffff)<<32 | (offsets & 0xffffffff))[:,None],56)
    packed=np.packbits(pdm,axis=1,bitorder='little')
    (out/'pdm.bin').write_bytes(packed.tobytes())
    (out/'pdm.hex').write_text(''.join(row.tobytes()[::-1].hex()+'\n' for row in packed))
    expected=fixed.process(pdm,gains,offsets)
    subprocess.run([str(ROOT/'log/build/mems_rm.exe'),str(out/'pdm.bin'),str(ROOT/'lib/coeff'),
                    str(out/'expected'),str(out/'calibration.txt')],check=True)
    checks={}
    for name,ref in zip(('cic','fir1','fir2','pcm'),expected):
        actual=np.fromfile(out/f'expected_{name}.bin',dtype='<i4').reshape(-1,CHANNELS)
        if not np.array_equal(ref,actual):
            raise AssertionError(f'{name}: Python/C++ mismatch at {np.argwhere(ref!=actual)[0].tolist()}')
        write_hex(out/f'expected_{name}.hex',actual,24 if name=='pcm' else 32)
        checks[name]={'frames':len(actual),'samples_compared':int(actual.size),'mismatches':0}
    from golden import process
    g0,_,_=process(pdm[:4096,8:10])
    assert np.array_equal(g0*2**30, expected[0][:len(g0),8:10])
    assert np.array_equal(expected[3][:,8],expected[3][:,9])
    # Calibrator recovery on a known uniform synthetic calibration field.
    from calibration import estimate
    ct=np.arange(4096)/FS_PCM
    channel=np.arange(128)
    dc=(channel-64)*1e-5
    amp=.02*(1+channel*.002)
    phase=channel*.0005
    quiet=np.rint(np.tile(dc,(4096,1))*2**23).astype(np.int32)
    tone=np.rint((amp[None,:]*np.cos(2*np.pi*1000*ct[:,None]+phase[None,:])+dc[None,:])*2**23).astype(np.int32)
    cg,co,cp=estimate(quiet,tone,1000)
    assert np.max(np.abs(cg/2**22-amp[0]/amp))<2e-6
    assert np.max(np.abs(co/2**30-dc))<1e-7
    assert np.max(np.abs(cp-phase))<5e-6
    manifest={'seed':'0x72D128','pdm_periods':n,'pcm_frames':n//64,'channels':CHANNELS,
              'integer_model_comparison':checks,'golden_cic_exact':True,
              'opposite_lr_identical_signal_exact':True,'calibration_recovery_128_channels':True}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('[MODEL_INFO] Python/C++ bit-exact: '+str(sum(v['samples_compared'] for v in checks.values()))+' samples')


if __name__=='__main__':main()
