"""Shared paths and exact arithmetic contract. No simulator dependency."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if (ROOT / 'lib/.deps').is_dir():
    sys.path.insert(0, str(ROOT / 'lib/.deps'))

import numpy as np

FS_PDM = 3_072_000
FS_PCM = 48_000
CHANNELS = 128
COEF_FRAC = 30
DATA_FRAC = 30
TAPS1, TAPS2 = 63, 127


def round_shift(x, bits):
    """Round to nearest, ties away from zero (also for negative numbers)."""
    x = np.asarray(x, dtype=np.int64)
    return np.where(x < 0, -((-x + (1 << (bits-1))) >> bits),
                    (x + (1 << (bits-1))) >> bits)


def saturate(x, width):
    return np.clip(x, -(1 << (width-1)), (1 << (width-1))-1)


def coefficients():
    return [np.load(ROOT / f'lib/coeff/fir{i}_float.npy') for i in (1, 2)]


def fixed_coefficients():
    return [np.loadtxt(ROOT / f'lib/coeff/fir{i}_q30.txt', dtype=np.int64)
            for i in (1, 2)]
