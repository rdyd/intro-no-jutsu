"""qprocess controller that drives the auto-sync worker subprocess."""

import os
import sys
import tempfile

from PyQt5.QtCore import QObject, QProcess, pyqtSignal

from .paths import resource_dir
from worker.models import missing as missing_models
from worker.protocol import (
    overall_fraction, parse_line, stage_label, stages_for, write_job)


def _worker_command(job_path):
    if getattr(sys, 'frozen', False):
        worker_exe = os.path.join(resource_dir(), 'inj-worker.exe')
        return worker_exe, [job_path]
    entry = os.path.join(resource_dir(), 'worker_entry.py')
    return sys.executable, [entry, job_path]


class SyncRunner(QObject):
    progress = pyqtSignal(float, str, str)
    info = pyqtSignal(dict)
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super(SyncRunner, self).__init__(parent)
        self._proc = None
        self._job_path = None
        self._buffer = ''
        self._settled = False
        self._was_cancelled = False
        self._stages = None
        self._result = None
        self._error = None

    def running(self):
        return self._proc is not None

    def start(self, spec):
        if self._proc is not None:
            self.failed.emit('the sync worker was already busy')
            return
        skip = () if missing_models() else ('download',)
        self._stages = stages_for(spec.get('kind'), skip)
        fd, self._job_path = tempfile.mkstemp(prefix='inj_sync_', suffix='.json')
        os.close(fd)
        write_job(spec, self._job_path)

        program, args = _worker_command(self._job_path)
        self._buffer = ''
        self._settled = False
        self._was_cancelled = False
        self._result = None
        self._error = None

        self._proc = QProcess(self)
        self._proc.setProgram(program)
        self._proc.setArguments(args)
        self._proc.readyReadStandardOutput.connect(self._on_stdout)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_error_occurred)
        self._proc.start()

    def cancel(self):
        if self._proc is None:
            return
        self._was_cancelled = True
        self._proc.kill()

    # -- process output -----------------------------------------------------

    def _on_stdout(self):
        chunk = bytes(self._proc.readAllStandardOutput()).decode(
            'utf-8', errors='replace')
        self._buffer += chunk
        while '\n' in self._buffer:
            line, self._buffer = self._buffer.split('\n', 1)
            obj = parse_line(line)
            if obj is not None:
                self._handle(obj)

    def _handle(self, obj):
        kind = obj.get('type')
        if kind == 'progress':
            frac = overall_fraction(obj.get('stage', ''),
                                    obj.get('fraction', 0.0), self._stages)
            stage = obj.get('stage', '')
            label = stage_label(stage)
            note = obj.get('note')
            self.progress.emit(frac, '%s - %s' % (label, note) if note
                               else label, stage)
        elif kind == 'info':
            self.info.emit({k: v for k, v in obj.items() if k != 'type'})
        elif kind == 'done':
            self._settled = True
            self._result = obj.get('result') or {}
        elif kind == 'error':
            self._settled = True
            self._error = obj.get('message') or 'unknown error'

    # -- process lifecycle ---------------------------------------------------

    def _on_finished(self, _exit_code, _exit_status):
        if self._proc is None:
            return
        result, error = self._result, self._error
        cancelled = self._was_cancelled
        self._cleanup()
        if error is not None:
            self.failed.emit(error)
        elif result is not None:
            self.finished.emit(result)
        elif cancelled:
            self.cancelled.emit()
        else:
            self.failed.emit('the worker process ended unexpectedly')

    def _on_error_occurred(self, error):
        if self._proc is None or self._settled or self._was_cancelled:
            return
        if error != QProcess.FailedToStart:
            return
        self._settled = True
        self._cleanup()
        self.failed.emit('could not start the sync worker process')

    def _cleanup(self):
        if self._job_path and os.path.exists(self._job_path):
            try:
                os.remove(self._job_path)
            except OSError:
                pass
        self._job_path = None
        self._result = None
        self._error = None
        proc, self._proc = self._proc, None
        if proc is not None:
            proc.deleteLater()
