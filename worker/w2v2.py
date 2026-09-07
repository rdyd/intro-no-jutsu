"""ctc emissions from wav2vec2 and viterbi forced alignment of known words."""

import unicodedata

import numpy as np

from .models import BLANK, CTC_VOCAB, SEPARATOR, VOCAB_SIZE

RATE = 16000
STRIDE = 320
RECEPTIVE = 400
FRAME_S = STRIDE / float(RATE)
NEG = -1e30

HOP_S = 20.0
MARGIN_S = 2.0

SPIKE_P = 0.50
DILATE_S = 0.40
MERGE_GAP_S = 0.60
MIN_BLOCK_S = 0.25

ONES = ('ZERO', 'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN',
        'EIGHT', 'NINE', 'TEN', 'ELEVEN', 'TWELVE', 'THIRTEEN', 'FOURTEEN',
        'FIFTEEN', 'SIXTEEN', 'SEVENTEEN', 'EIGHTEEN', 'NINETEEN')
TENS = ('', '', 'TWENTY', 'THIRTY', 'FORTY', 'FIFTY', 'SIXTY', 'SEVENTY',
        'EIGHTY', 'NINETY')


# -- text -> vocabulary --------------------------------------------------

def _say_number(n):
    if n < 20:
        return ONES[n]
    if n < 100:
        return (TENS[n // 10] + (' ' + ONES[n % 10] if n % 10 else '')).strip()
    if n < 1000:
        rest = n % 100
        return ONES[n // 100] + ' HUNDRED' + (' ' + _say_number(rest) if rest else '')
    if n < 10000:
        return _say_number(n // 100) + (' ' + _say_number(n % 100) if n % 100 else '')
    return ' '.join(ONES[int(d)] for d in str(n))


def normalize(raw):
    text = unicodedata.normalize('NFKD', raw)
    text = ''.join(c for c in text if not unicodedata.combining(c))
    text = text.upper()
    for ch in '’‘´`':
        text = text.replace(ch, "'")
    for ch in '–—-/':
        text = text.replace(ch, ' ')
    pieces = []
    for piece in text.split():
        pieces.append(_say_number(int(piece)) if piece.isdigit() else piece)
    kept = ''.join(c for c in ' '.join(pieces) if c in CTC_VOCAB or c == ' ')
    return ''.join(kept.split())


# -- acoustic model ------------------------------------------------------

def emissions(audio, model_path, report=None, cancelled=None):
    import onnxruntime as ort

    session = ort.InferenceSession(
        model_path, providers=['CPUExecutionProvider'])
    name = session.get_inputs()[0].name

    x = audio.astype(np.float32)
    if len(x) < RECEPTIVE:
        return np.zeros((0, VOCAB_SIZE), np.float32)
    x = (x - x.mean()) / np.sqrt(x.var() + 1e-7)

    hop = int(round(HOP_S * RATE / STRIDE)) * STRIDE
    margin = int(round(MARGIN_S * RATE / STRIDE)) * STRIDE
    margin_frames = margin // STRIDE
    total_frames = (len(x) - RECEPTIVE) // STRIDE + 1

    out = np.zeros((total_frames, VOCAB_SIZE), np.float32)
    filled = 0
    starts = list(range(0, len(x), hop))
    for k, s0 in enumerate(starts):
        if cancelled is not None and cancelled():
            break
        lo = max(0, s0 - margin)
        hi = min(len(x), s0 + hop + margin)
        seg = x[lo:hi]
        if len(seg) < RECEPTIVE:
            break
        logits = session.run(None, {name: seg[None, :]})[0][0]
        m = logits.max(axis=1, keepdims=True)
        logp = logits - m - np.log(np.exp(logits - m).sum(axis=1, keepdims=True))

        drop_lo = 0 if lo == 0 else margin_frames
        drop_hi = 0 if hi == len(x) else margin_frames
        keep = logp[drop_lo:len(logp) - drop_hi] if drop_hi else logp[drop_lo:]
        first = (lo // STRIDE) + drop_lo
        n = min(len(keep), total_frames - first)
        if n > 0:
            out[first:first + n] = keep[:n]
            filled = max(filled, first + n)
        if report:
            report(k + 1, len(starts))
    return out[:filled]


# -- where the singing actually is ---------------------------------------

def speech_blocks(logp):
    if len(logp) == 0:
        return []
    spike = (1.0 - np.exp(logp[:, BLANK])) >= SPIKE_P
    if not spike.any():
        return []
    width = max(1, int(round(2 * DILATE_S / FRAME_S)) | 1)
    on = np.convolve(spike.astype(np.float32), np.ones(width, np.float32),
                     mode='same') > 0.0

    edges = np.diff(on.astype(np.int8))
    starts = list(np.flatnonzero(edges == 1) + 1)
    ends = list(np.flatnonzero(edges == -1) + 1)
    if on[0]:
        starts.insert(0, 0)
    if on[-1]:
        ends.append(len(on))

    blocks = []
    for f0, f1 in zip(starts, ends):
        a, b = f0 * FRAME_S, f1 * FRAME_S
        if blocks and a - blocks[-1][1] <= MERGE_GAP_S:
            blocks[-1][1] = max(blocks[-1][1], b)
        else:
            blocks.append([max(0.0, a), b])
    return [(a, b) for a, b in blocks if b - a >= MIN_BLOCK_S]


# -- forced alignment ----------------------------------------------------

def _viterbi(logp, labels):
    states = np.zeros(2 * len(labels) + 1, np.int64)
    states[1::2] = labels
    states[0::2] = BLANK
    n_states = len(states)
    n_frames = len(logp)

    allowed = np.zeros(n_states, bool)
    allowed[2:] = (states[2:] != BLANK) & (states[2:] != states[:-2])

    emit = logp[:, states]
    prev = np.full(n_states, NEG, np.float32)
    prev[0] = emit[0, 0]
    if n_states > 1:
        prev[1] = emit[0, 1]

    back = np.zeros((n_frames, n_states), np.uint8)
    for t in range(1, n_frames):
        advance = np.empty(n_states, np.float32)
        advance[0] = NEG
        advance[1:] = prev[:-1]
        skip = np.full(n_states, NEG, np.float32)
        skip[2:] = np.where(allowed[2:], prev[:-2], NEG)
        stack = np.stack((prev, advance, skip))
        choice = stack.argmax(0).astype(np.uint8)
        prev = stack[choice, np.arange(n_states)] + emit[t]
        back[t] = choice

    s = int(n_states - 1 if prev[n_states - 1] >= prev[n_states - 2]
            else n_states - 2)
    path = np.zeros(n_frames, np.int64)
    for t in range(n_frames - 1, 0, -1):
        path[t] = s
        s = s - int(back[t, s])
    path[0] = s
    return path


def align_window(logp, words, f0, f1):
    spelled = [normalize(w) or None for w in words]

    labels, spans = [], []
    for text in spelled:
        if text is None:
            spans.append(None)
            continue
        if labels:
            labels.append(SEPARATOR)
        first = len(labels)
        labels.extend(CTC_VOCAB[c] for c in text)
        spans.append(first)
    if not labels:
        return [None] * len(words)

    segment = logp[f0:f1]
    if len(segment) < len(labels) + 1:
        return [None] * len(words)

    path = _viterbi(segment, labels)
    first_frame = {}
    for t, s in enumerate(path):
        if s not in first_frame:
            first_frame[s] = t

    out = []
    for span in spans:
        if span is None:
            out.append(None)
            continue
        frame = first_frame.get(2 * span + 1)
        out.append(None if frame is None else (f0 + frame) * FRAME_S)
    return out


def clamp_windows(windows):
    out = []
    for i, (a, b) in enumerate(windows):
        low = 0.0 if i == 0 else (windows[i - 1][1] + a) / 2.0
        high = 1e9 if i == len(windows) - 1 else (b + windows[i + 1][0]) / 2.0
        lo, hi = max(a, low), min(b, high)
        out.append((lo, hi) if hi > lo else (a, b))
    return out


def fill_gaps(starts, lo_s, hi_s):
    known = [i for i, s in enumerate(starts) if s is not None]
    if not known:
        n = len(starts)
        step = (hi_s - lo_s) / float(n + 1)
        return [lo_s + step * (i + 1) for i in range(n)]
    out = list(starts)
    for i, value in enumerate(out):
        if value is not None:
            continue
        before = next((out[j] for j in range(i - 1, -1, -1)
                       if out[j] is not None), None)
        after = next((starts[j] for j in range(i + 1, len(starts))
                      if starts[j] is not None), None)
        if before is None:
            out[i] = max(lo_s, after - 0.2)
        elif after is None:
            out[i] = min(hi_s, before + 0.2)
        else:
            out[i] = (before + after) / 2.0
    return out
