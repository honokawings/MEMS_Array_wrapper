"""Python integer oracle, independently checked against the C++ reference model."""
from common import *


def cic(pdm):
    pdm = np.asarray(pdm, dtype=np.int64)
    if pdm.ndim == 1:
        pdm = pdm[:, None]
    state = np.zeros((5, pdm.shape[1]), dtype=np.int64)
    delay = np.zeros_like(state)
    result = []
    for n, row in enumerate(pdm):
        new = (state + np.vstack((2*row-1, state[:-1]))) & 0xffffffff
        state = new
        if n % 8 == 7:
            x = state[4].copy()
            for j in range(5):
                old = x.copy()
                x = (x-delay[j]) & 0xffffffff
                delay[j] = old
            x = np.where(x >= 2**31, x-2**32, x)
            result.append(x << 15)
    return np.asarray(result, dtype=np.int64)


def fir(x, h, decimation):
    result = []
    for n in range(decimation-1, len(x), decimation):
        count = min(n+1, len(h))
        acc = np.sum(x[n-count+1:n+1][::-1]*h[:count, None], axis=0, dtype=np.int64)
        result.append(saturate(round_shift(acc, 30), 32))
    return np.asarray(result, dtype=np.int64)


def process(pdm, gains=None, offsets=None):
    h1, h2 = fixed_coefficients()
    y0 = cic(pdm)
    y1 = fir(y0, h1, 4)
    y2 = fir(y1, h2, 2)
    gains = np.full(y2.shape[1], 1 << 22, dtype=np.int64) if gains is None else gains
    offsets = np.zeros(y2.shape[1], dtype=np.int64) if offsets is None else offsets
    pcm = saturate(round_shift((y2-offsets)*gains, 29), 24)
    return y0, y1, y2, pcm
