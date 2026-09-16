"""Generate reproducible linear-phase decimators and all coefficient views."""
from common import *
from scipy import signal
import json
import argparse


def cic_response(f):
    f = np.asarray(f)
    return (np.sinc(f * 8 / FS_PDM) / np.sinc(f / FS_PDM)) ** 5


def design(update=False):
    # Piecewise-linear inverse-CIC target, with a broad don't-care transition.
    grid = np.linspace(0, 16_000, 65)
    bands = np.column_stack((grid[:-1], grid[1:])).ravel().tolist()
    desired = np.column_stack((1/cic_response(grid[:-1]),
                               1/cic_response(grid[1:]))).ravel().tolist()
    h1 = signal.firls(TAPS1, bands + [80_000, 192_000], desired + [0, 0],
                      weight=[1]*64 + [100], fs=384_000)
    h2 = signal.remez(TAPS2, [0, 16_000, 24_000, 48_000], [1, 0],
                      weight=[1, 10], fs=96_000, maxiter=100)
    out = ROOT / 'lib/coeff'
    out.mkdir(parents=True, exist_ok=True)
    specs = []
    for i, h in enumerate((h1, h2), 1):
        h /= h.sum()
        q = np.where(h < 0, -np.floor(-h*2**30+.5), np.floor(h*2**30+.5)).astype(np.int64)
        # Odd-length symmetric FIR: adjust only the centre for exactly unity DC.
        q[len(q)//2] += 2**30 - q.sum()
        assert np.array_equal(q, q[::-1])
        assert np.abs(q).sum() * (2**31) < 2**63
        frozen=out / f'fir{i}_q30.txt'
        if frozen.exists() and not update:
            if not np.array_equal(np.loadtxt(frozen,dtype=np.int64),q):
                raise RuntimeError('Generated coefficients differ from the frozen specification. '
                                   'Check dependency versions; use --update only with a specification revision.')
        np.save(out / f'fir{i}_float.npy', h)
        np.savetxt(out / f'fir{i}_q30.txt', q, fmt='%d')
        (out / f'fir{i}_q30.hex').write_text(''.join(f'{int(v)&0xffffffff:08x}\n' for v in q))
        # Explicit synthesizable ROM avoids working-directory-dependent readmemh.
        cases = '\n'.join(f'            {k}: coefficient = 32\'h{int(v)&0xffffffff:08x};'
                          for k,v in enumerate(q))
        (ROOT / f'rtl/fir{i}_coeff.svh').write_text(cases+'\n')
        specs.append({'stage':i, 'taps':len(q), 'fraction_bits':30,
                      'sum_q30':int(q.sum()), 'l1_norm':float(np.abs(q).sum()/2**30)})
    (out / 'manifest.json').write_text(json.dumps(specs, indent=2)+'\n')
    print('[MODEL_INFO] Coefficients generated: 63 /4 and 127 /2, signed Q2.30')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--update',action='store_true',help='Explicitly replace the frozen coefficient set')
    design(parser.parse_args().update)
