"""the actual auto-sync work, split across two jobs."""

import base64
import os
import time

from . import audio as audio_io
from . import models
from .protocol import STAGES, WorkerError, emit_info, emit_progress

JOBS = {}

PEAKS_HZ = 100


def job(kind):
    def register(fn):
        JOBS[kind] = fn
        return fn
    return register


def _reporter(stage, every=0.15):
    last = [0.0, -1.0]

    def report(done, total, note=None):
        now = time.time()
        fraction = done / float(total) if total else 1.0
        if fraction >= 1.0 or now - last[0] >= every:
            if fraction != last[1]:
                last[0], last[1] = now, fraction
                emit_progress(stage, fraction, note)
    return report


# -- phase one: decode, isolate vocals, run the acoustic model -----------

@job('prepare')
def run_prepare(spec):
    import numpy as np

    from . import mdx, w2v2
    from .download import fetch_missing

    path = spec.get('audio') or ''
    if not os.path.exists(path):
        raise WorkerError('that audio file is gone')
    out_path = spec.get('emissions')
    wav_original = spec.get('wav_original')
    wav_vocal = spec.get('wav_vocal')
    if not out_path or not wav_original or not wav_vocal:
        raise WorkerError('no place to put the analysis')

    fetch_missing(_reporter('download', 0.30))

    report = _reporter('decode')
    report(0, 1)
    mix = audio_io.decode_stereo(path, mdx.RATE)
    if mix.shape[1] < mdx.RATE:
        raise WorkerError('that file has no audio in it')
    report(1, 1)
    duration = mix.shape[1] / float(mdx.RATE)
    emit_info({'duration': duration})

    stem = mdx.separate(mix, models.model_path('mdx'), _reporter('separate'))

    audio_io.write_wav(wav_original, mix, mdx.RATE)
    del mix
    audio_io.write_wav(wav_vocal, stem, mdx.RATE)

    vocals = audio_io.to_mono(stem, mdx.RATE, w2v2.RATE)
    vocal_peaks = audio_io.peaks(vocals, w2v2.RATE, PEAKS_HZ)
    del stem

    logp = w2v2.emissions(vocals, models.model_path('w2v2'),
                          _reporter('emit'))
    del vocals
    if len(logp) == 0:
        raise WorkerError('the vocal track came out empty')
    np.save(out_path, logp)

    return {
        'duration': duration,
        'frames': int(len(logp)),
        'peaks_hz': PEAKS_HZ,
        'vocal_peaks': base64.b64encode(vocal_peaks).decode('ascii'),
    }


# -- phase two: a first guess with no input at all -----------------------

@job('prefill')
def run_prefill(spec):
    from . import w2v2

    logp = _load_emissions(spec)
    lines = spec.get('lines') or []
    groups = [line.get('words') or [] for line in lines]
    flat = [word for words in groups for word in words]
    if not flat:
        return {'starts': [[] for _ in groups]}

    report = _reporter('align', 0.05)
    report(0, 2)
    placed = w2v2.align_window(logp, flat, 0, len(logp))
    filled = w2v2.fill_gaps(placed, 0.0, len(logp) * w2v2.FRAME_S)
    report(2, 2)

    starts, at = [], 0
    for words in groups:
        starts.append(filled[at:at + len(words)])
        at += len(words)
    return {'starts': starts}


# -- phase two, the other way round: no lyrics, just show me the singing --

@job('blocks')
def run_blocks(spec):
    from . import w2v2

    logp = _load_emissions(spec)
    report = _reporter('align', 0.05)
    report(0, 2)
    blocks = w2v2.speech_blocks(logp)
    report(2, 2)
    return {'blocks': [[a, b] for a, b in blocks]}


# -- phase three: re-align only the windows the user corrected -----------

@job('align')
def run_align(spec):
    from . import w2v2

    logp = _load_emissions(spec)
    total = len(logp)
    lines = spec.get('lines') or []

    windows = w2v2.clamp_windows(
        [(float(line['start']), float(line['end'])) for line in lines])

    wanted = [i for i, line in enumerate(lines)
              if line.get('align', True) and line.get('words')]
    report = _reporter('align', 0.05)
    starts = [None] * len(lines)
    for done, index in enumerate(wanted):
        a, b = windows[index]
        f0 = max(0, int(a / w2v2.FRAME_S))
        f1 = min(total, int(b / w2v2.FRAME_S) + 1)
        placed = w2v2.align_window(logp, lines[index]['words'], f0, f1)
        starts[index] = w2v2.fill_gaps(placed, a, b)
        report(done + 1, len(wanted))
    report(1, 1)

    return {'starts': starts}


def _load_emissions(spec):
    import numpy as np

    path = spec.get('emissions') or ''
    if not os.path.exists(path):
        raise WorkerError('the analysis went missing, run it again')
    return np.load(path)


# -- the plumbing smoke test, kept: it needs no models and no audio ------

@job('fake')
def run_fake_job(spec):
    steps = 6
    for key, _label, _weight in STAGES:
        for i in range(1, steps + 1):
            time.sleep(0.15)
            emit_progress(key, i / float(steps))
    return {'kind': 'fake', 'word_count': int(spec.get('word_count', 0))}
