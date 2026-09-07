"""entry point for the standalone worker process. see worker_entry.py."""

import sys

from .pipeline import JOBS
from .protocol import WorkerError, emit_done, emit_error, read_job


def main(argv):
    if 'PyQt5' in sys.modules:
        emit_error('ImportError', 'qt was imported before the worker started')
        return 1
    if not argv:
        emit_error('ValueError', 'no job file given')
        return 1
    try:
        spec = read_job(argv[0])
        handler = JOBS.get(spec.get('kind'))
        if handler is None:
            emit_error('ValueError', 'unknown job kind')
            return 1
        result = handler(spec)
    except WorkerError as e:
        emit_error('WorkerError', str(e))
        return 1
    except MemoryError:
        emit_error('MemoryError', 'ran out of memory on this track')
        return 1
    except ImportError as e:
        emit_error(type(e).__name__,
                   'the worker is missing ' + (getattr(e, 'name', None) or '?'))
        return 1
    except BaseException as e:
        emit_error(type(e).__name__, 'worker failed')
        return 1
    emit_done(result)
    return 0
