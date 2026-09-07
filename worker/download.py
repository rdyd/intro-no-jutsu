"""first-use model fetch. stdlib only, sha256 verified, atomic replace."""

import hashlib
import os

from .models import MODELS, missing, model_dir, model_path
from .protocol import WorkerError

CHUNK = 1 << 18
MB = 1 << 20
TIMEOUT = 60


def fetch_missing(report=None):
    keys = missing()
    if not keys:
        return
    os.makedirs(model_dir(), exist_ok=True)
    total = sum(MODELS[key]['size'] for key in keys)
    done = 0
    for key in keys:
        _discard(model_path(key) + '.part')
        done = _fetch(key, done, total, report)


def _fetch(key, done, total, report):
    spec = MODELS[key]
    target = model_path(key)
    part = target + '.part'
    why = 'no url worked'
    for url in spec['urls']:
        try:
            _stream(url, part, done, total, report)
            if os.path.getsize(part) != spec['size']:
                raise WorkerError('wrong size')
            if _sha256(part) != spec['sha256']:
                raise WorkerError('checksum mismatch')
        except Exception as e:
            why = str(e) if isinstance(e, WorkerError) else type(e).__name__
            _discard(part)
            continue
        os.replace(part, target)
        return done + spec['size']
    raise WorkerError(
        'could not download %s (%s)' % (spec['name'], why.lower()))


def _stream(url, part, done, total, report):
    import urllib.request

    request = urllib.request.Request(
        url, headers={'User-Agent': 'intro-no-jutsu'})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        with open(part, 'wb') as out:
            got = done
            while True:
                block = response.read(CHUNK)
                if not block:
                    break
                out.write(block)
                got += len(block)
                if report:
                    done = min(got, total)
                    report(done, total, '%d of %d mb'
                           % (done // MB, total // MB))


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(CHUNK), b''):
            digest.update(block)
    return digest.hexdigest()


def _discard(path):
    try:
        os.remove(path)
    except OSError:
        pass
