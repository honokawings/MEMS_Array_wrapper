"""Independent floating model: finite convolution, not CIC accumulator recursion."""
from common import *
from scipy import signal


def cic_impulse():
    h = np.ones(1)
    for _ in range(5):
        h = np.convolve(h, np.ones(8)/8)
    # Registered integrator chain contributes four PDM periods of common delay.
    return np.r_[np.zeros(4), h]


def process(pdm):
    x = 2*np.asarray(pdm, dtype=np.float64)-1
    if x.ndim == 1:
        x = x[:, None]
    h1, h2 = coefficients()
    y0 = signal.lfilter(cic_impulse(), [1], x, axis=0)[7::8]
    y1 = signal.lfilter(h1, [1], y0, axis=0)[3::4]
    y2 = signal.lfilter(h2, [1], y1, axis=0)[1::2]
    return y0, y1, y2


def ideal_audio(pdm):
    """Offline reference with a much longer direct PDM-rate decimation filter."""
    h = signal.firwin(4097, 20_000, fs=FS_PDM, window=('kaiser', 14))
    return signal.upfirdn(h, 2*np.asarray(pdm, dtype=float)-1, down=64)
