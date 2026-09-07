"""audio decode through pyav."""

import numpy as np

MIX_RATE = 44100
MODEL_RATE = 16000


def decode_stereo(path, rate=MIX_RATE):
    import av
    from av.audio.resampler import AudioResampler

    container = av.open(path)
    try:
        stream = container.streams.audio[0]
        resampler = AudioResampler(format='fltp', layout='stereo', rate=rate)
        chunks = []
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray())
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray())
    finally:
        container.close()

    if not chunks:
        return np.zeros((2, 0), np.float32)
    data = np.concatenate(chunks, axis=1).astype(np.float32)
    if data.shape[0] == 1:
        data = np.vstack([data[0], data[0]])
    return data[:2]


def to_mono(stereo, rate=MIX_RATE, out_rate=MODEL_RATE):
    mono = stereo.mean(axis=0)
    if rate == out_rate or len(mono) == 0:
        return mono.astype(np.float32)
    count = int(round(len(mono) * float(out_rate) / rate))
    source = np.arange(len(mono), dtype=np.float64)
    target = np.linspace(0.0, len(mono) - 1, count)
    return np.interp(target, source, mono).astype(np.float32)


def write_wav(path, stereo, rate):
    import wave

    data = np.ascontiguousarray(np.clip(stereo, -1.0, 1.0).T)
    pcm = (data * 32767.0).astype('<i2').tobytes()
    handle = wave.open(path, 'wb')
    try:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(int(rate))
        handle.writeframes(pcm)
    finally:
        handle.close()


def peaks(mono, rate, peaks_hz):
    if len(mono) == 0:
        return b''
    step = max(1, int(round(rate / float(peaks_hz))))
    count = (len(mono) + step - 1) // step
    padded = np.zeros(count * step, np.float32)
    padded[:len(mono)] = np.abs(mono)
    column = padded.reshape(count, step).max(axis=1)
    top = float(column.max())
    if top <= 0.0:
        return bytes(count)
    return (np.clip(column / top, 0.0, 1.0) * 255.0).astype(np.uint8).tobytes()
