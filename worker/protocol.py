"""json-lines wire protocol between the gui process and the worker subprocess."""

import json
import sys

STAGES = (
    ('download', 'downloading models', 0.30),
    ('decode', 'reading audio', 0.05),
    ('separate', 'isolating vocals', 0.45),
    ('emit', 'listening for words', 0.20),
    ('align', 'aligning words', 1.00),
)

COUNTED_STAGES = ('separate', 'emit')

JOB_STAGES = {
    'fake': ('download', 'decode', 'separate', 'emit', 'align'),
    'prepare': ('download', 'decode', 'separate', 'emit'),
    'prefill': ('align',),
    'blocks': ('align',),
    'align': ('align',),
}


class WorkerError(Exception):
    pass


def emit_progress(stage, fraction, note=None):
    message = {'type': 'progress', 'stage': stage, 'fraction': fraction}
    if note:
        message['note'] = note
    _emit(message)


def emit_info(payload):
    message = {'type': 'info'}
    message.update(payload)
    _emit(message)


def emit_done(result):
    _emit({'type': 'done', 'result': result})


def emit_error(kind, message):
    _emit({'type': 'error', 'error_type': kind, 'message': message})


def _emit(obj):
    sys.stdout.write(json.dumps(obj) + '\n')
    sys.stdout.flush()


def parse_line(text):
    text = text.strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
    except ValueError:
        return None
    if not isinstance(obj, dict) or 'type' not in obj:
        return None
    return obj


def stage_weight(stage_key):
    for key, _label, weight in STAGES:
        if key == stage_key:
            return weight
    return 0.0


def stage_label(stage_key):
    for key, label, _weight in STAGES:
        if key == stage_key:
            return label
    return stage_key


def stages_for(kind, skip=()):
    return tuple(key for key in JOB_STAGES.get(kind, ()) if key not in skip)


def overall_fraction(stage_key, fraction_within_stage, stages=None):
    keys = tuple(key for key, _label, _weight in STAGES) if stages is None \
        else tuple(stages)
    total = sum(stage_weight(key) for key in keys)
    if total <= 0.0 or stage_key not in keys:
        return 0.0
    before = 0.0
    for key in keys:
        if key == stage_key:
            break
        before += stage_weight(key)
    frac = max(0.0, min(1.0, fraction_within_stage))
    return (before + stage_weight(stage_key) * frac) / total


def write_job(job, path):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(job, f)


def read_job(path):
    with open(path, encoding='utf-8-sig') as f:
        return json.load(f)
