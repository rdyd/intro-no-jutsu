"""octave-band spectrum analysis for the preview's graphic equaliser."""

import math

BAND_CENTERS = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
BAND_LABELS = ['32Hz', '64Hz', '125Hz', '250Hz', '500Hz',
               '1kHz', '2kHz', '4kHz', '8kHz', '16kHz']

FFT_SIZE = 2048
DB_FLOOR = -30.0
DB_CEIL = 20.0

_window_cache = {}
_bins_cache = {}


def _hann(n):
    w = _window_cache.get(n)
    if w is None:
        w = [0.5 - 0.5 * math.cos(2.0 * math.pi * i / (n - 1)) for i in range(n)]
        _window_cache[n] = w
    return w


def _band_bins(n, rate):
    key = (n, rate)
    cached = _bins_cache.get(key)
    if cached is not None:
        return cached
    root2 = math.sqrt(2.0)
    half = n // 2
    spacing = float(rate) / n
    out = []
    for centre in BAND_CENTERS:
        lo = int(math.floor((centre / root2) / spacing))
        hi = int(math.ceil((centre * root2) / spacing))
        lo = max(1, min(lo, half - 1))
        hi = max(lo + 1, min(hi, half))
        out.append((lo, hi))
    _bins_cache[key] = out
    return out


def _fft(re, im):
    n = len(re)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            re[i], re[j] = re[j], re[i]
            im[i], im[j] = im[j], im[i]

    length = 2
    while length <= n:
        ang = -2.0 * math.pi / length
        wr, wi = math.cos(ang), math.sin(ang)
        half = length >> 1
        for start in range(0, n, length):
            cr, ci = 1.0, 0.0
            for k in range(start, start + half):
                pr, pi = re[k + half], im[k + half]
                vr = pr * cr - pi * ci
                vi = pr * ci + pi * cr
                ur, ui = re[k], im[k]
                re[k] = ur + vr
                im[k] = ui + vi
                re[k + half] = ur - vr
                im[k + half] = ui - vi
                cr, ci = cr * wr - ci * wi, cr * wi + ci * wr
        length <<= 1

_FULLSCALE = 0.25


def band_levels(mono, rate, size=FFT_SIZE, gain_db=12.0):
    n = size
    if len(mono) < n or rate <= 0:
        return None
    chunk = mono[-n:]
    window = _hann(n)
    inv = 1.0 / n
    re = [chunk[i] * window[i] * inv for i in range(n)]
    im = [0.0] * n
    _fft(re, im)

    out = []
    for lo, hi in _band_bins(n, rate):
        power = 0.0
        for k in range(lo, hi):
            power += re[k] * re[k] + im[k] * im[k]
        amp = math.sqrt(power) / _FULLSCALE
        db = 20.0 * math.log10(amp + 1e-12) + gain_db
        out.append(max(DB_FLOOR, min(DB_CEIL, db)))
    return out
