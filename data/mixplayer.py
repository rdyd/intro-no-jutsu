"""plays the original and the isolated vocal as one stream."""

import audioop
import wave

from PyQt5.QtCore import QIODevice, QObject, QTimer, pyqtSignal
from PyQt5.QtMultimedia import QAudio, QAudioFormat, QAudioOutput

SAMPLE_BYTES = 2
CHANNELS = 2
BLOCK = SAMPLE_BYTES * CHANNELS
TICK_MS = 30
CHUNK_FRAMES = 4096

ORIGINAL_LEVEL = 25
VOCAL_LEVEL = 100


class _MixDevice(QIODevice):
    def __init__(self, original, vocal, parent=None):
        super(_MixDevice, self).__init__(parent)
        self._original = original
        self._vocal = vocal
        self._gain = [ORIGINAL_LEVEL / 100.0, VOCAL_LEVEL / 100.0]
        self._end = min(original.getnframes(), vocal.getnframes())
        self._stop_at = self._end

    def seek_frames(self, first, last):
        self._original.setpos(min(first, self._end))
        self._vocal.setpos(min(first, self._end))
        self._stop_at = max(first, min(last, self._end))

    def set_gain(self, original, vocal):
        self._gain = [original, vocal]

    def readData(self, maxlen):
        wanted = min(int(maxlen) // BLOCK, CHUNK_FRAMES)
        left = self._stop_at - self._original.tell()
        wanted = min(wanted, max(0, left))
        if wanted <= 0:
            return b''
        a = self._original.readframes(wanted)
        b = self._vocal.readframes(wanted)
        size = min(len(a), len(b))
        if size <= 0:
            return b''
        a = audioop.mul(a[:size], SAMPLE_BYTES, self._gain[0])
        b = audioop.mul(b[:size], SAMPLE_BYTES, self._gain[1])
        return audioop.add(a, b, SAMPLE_BYTES)

    def writeData(self, _data):
        return 0

    def bytesAvailable(self):
        left = max(0, self._stop_at - self._original.tell())
        return left * BLOCK + super(_MixDevice, self).bytesAvailable()

    def isSequential(self):
        return True


class MixPlayer(QObject):
    positionChanged = pyqtSignal(float)
    stopped = pyqtSignal()

    def __init__(self, parent=None):
        super(MixPlayer, self).__init__(parent)
        self._original = None
        self._vocal = None
        self._device = None
        self._output = None
        self._rate = 44100
        self._duration = 0.0
        self._start_at = 0.0
        self._levels = (ORIGINAL_LEVEL / 100.0, VOCAL_LEVEL / 100.0)

        self._clock = QTimer(self)
        self._clock.setInterval(TICK_MS)
        self._clock.timeout.connect(self._on_tick)

    # -- sources ---------------------------------------------------------

    def set_sources(self, original_path, vocal_path):
        self.stop()
        self._close()
        try:
            self._original = wave.open(original_path, 'rb')
            self._vocal = wave.open(vocal_path, 'rb')
        except Exception:
            self._close()
            return False
        self._rate = self._original.getframerate() or 44100
        frames = min(self._original.getnframes(), self._vocal.getnframes())
        self._duration = frames / float(self._rate)
        return True

    def ready(self):
        return self._original is not None and self._vocal is not None

    def duration(self):
        return self._duration

    # -- transport -------------------------------------------------------

    def play(self, start_seconds, end_seconds=None):
        if not self.ready():
            return
        self.stop()
        first = max(0, int(round(start_seconds * self._rate)))
        last = (self._original.getnframes() if end_seconds is None
                else int(round(end_seconds * self._rate)))
        if last - first < 1:
            return

        self._device = _MixDevice(self._original, self._vocal, self)
        self._device.set_gain(*self._levels)
        self._device.seek_frames(first, last)
        self._device.open(QIODevice.ReadOnly)

        fmt = QAudioFormat()
        fmt.setSampleRate(self._rate)
        fmt.setChannelCount(CHANNELS)
        fmt.setSampleSize(8 * SAMPLE_BYTES)
        fmt.setCodec('audio/pcm')
        fmt.setByteOrder(QAudioFormat.LittleEndian)
        fmt.setSampleType(QAudioFormat.SignedInt)

        self._output = QAudioOutput(fmt, self)
        self._output.stateChanged.connect(self._on_state)
        self._start_at = first / float(self._rate)
        self._output.start(self._device)
        self._clock.start()
        self.positionChanged.emit(self._start_at)

    def stop(self):
        self._clock.stop()
        output, self._output = self._output, None
        if output is not None:
            output.stateChanged.disconnect(self._on_state)
            output.stop()
            output.deleteLater()
        device, self._device = self._device, None
        if device is not None:
            device.close()
            device.deleteLater()

    def playing(self):
        return self._output is not None and \
            self._output.state() == QAudio.ActiveState

    def position(self):
        if self._output is None:
            return self._start_at
        return self._start_at + self._output.processedUSecs() / 1000000.0

    # -- levels ----------------------------------------------------------

    def set_levels(self, original, vocal):
        self._levels = (max(0.0, original), max(0.0, vocal))
        if self._device is not None:
            self._device.set_gain(*self._levels)

    # -- internals -------------------------------------------------------

    def _on_tick(self):
        self.positionChanged.emit(self.position())

    def _on_state(self, state):
        if state in (QAudio.IdleState, QAudio.StoppedState):
            self.stop()
            self.stopped.emit()

    def _close(self):
        for handle in (self._original, self._vocal):
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
        self._original = self._vocal = None
        self._duration = 0.0

    def release(self):
        self.stop()
        self._close()
