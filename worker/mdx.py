"""mdx-net vocal separation through onnxruntime, numpy stft only."""

import numpy as np

N_FFT = 7680
HOP = 1024
DIM_F = 3072
DIM_T = 256
RATE = 44100

_WIN = np.hanning(N_FFT).astype(np.float32)
TRIM = N_FFT // 2
CHUNK = HOP * (DIM_T - 1)
GEN = CHUNK - 2 * TRIM


def _frames(x):
    xp = np.pad(x, ((0, 0), (TRIM, TRIM)), mode='constant')
    n = 1 + (xp.shape[1] - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n)[:, None]
    return np.fft.rfft(xp[:, idx] * _WIN, axis=-1)


def _inverse(spec, length):
    frames = np.fft.irfft(spec, n=N_FFT, axis=-1).astype(np.float32) * _WIN
    c, n, _ = frames.shape
    out = np.zeros((c, TRIM * 2 + (n - 1) * HOP + N_FFT), np.float32)
    norm = np.zeros(out.shape[1], np.float32)
    w2 = _WIN * _WIN
    for i in range(n):
        a = i * HOP
        out[:, a:a + N_FFT] += frames[:, i]
        norm[a:a + N_FFT] += w2
    norm[norm < 1e-8] = 1e-8
    out /= norm
    return out[:, TRIM:TRIM + length]


def separate(mix, model_path, report=None, cancelled=None):
    import onnxruntime as ort

    session = ort.InferenceSession(
        model_path, providers=['CPUExecutionProvider'])
    name = session.get_inputs()[0].name

    n = mix.shape[1]
    if n == 0:
        return np.zeros_like(mix)
    pad = GEN - (n % GEN)
    padded = np.concatenate(
        [np.zeros((2, TRIM), np.float32), mix,
         np.zeros((2, pad + TRIM), np.float32)], axis=1)

    out = np.zeros_like(padded)
    starts = list(range(TRIM, TRIM + n + pad, GEN))
    for k, s in enumerate(starts):
        if cancelled is not None and cancelled():
            break
        seg = padded[:, s - TRIM:s - TRIM + CHUNK]
        if seg.shape[1] < CHUNK:
            seg = np.pad(seg, ((0, 0), (0, CHUNK - seg.shape[1])),
                         mode='constant')
        spec = _frames(seg)[:, :, :DIM_F]
        x = np.stack([spec.real, spec.imag], axis=1).reshape(1, 4, DIM_T, DIM_F)
        x = np.ascontiguousarray(x.transpose(0, 1, 3, 2), dtype=np.float32)

        y = session.run(None, {name: x})[0]
        y = y.transpose(0, 1, 3, 2).reshape(2, 2, DIM_T, DIM_F)
        full = np.zeros((2, DIM_T, N_FFT // 2 + 1), np.complex64)
        full[:, :, :DIM_F] = y[:, 0] + 1j * y[:, 1]

        wav = _inverse(full, CHUNK)
        out[:, s:s + GEN] = wav[:, TRIM:TRIM + GEN]
        if report:
            report(k + 1, len(starts))
    return out[:, TRIM:TRIM + n]
