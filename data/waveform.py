"""the isolated-vocal waveform the blocks are laid over."""

import math

from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QScrollArea, QSizePolicy, QWidget

PX_PER_S_DEFAULT = 30.0
PX_PER_S_MIN = 6.0
PX_PER_S_MAX = 400.0
ZOOM_STEPS = 100

WAVE_HEIGHT = 170
RULER_HEIGHT = 16
CLICK_SLOP = 4

BACKDROP = '#101010'
VOCAL_COLOR = '#7fd6c0'
GRID_COLOR = '#2a2a2e'
RULER_TEXT = '#7d7d88'
BLOCK_FILL = '#20262b'
BLOCK_EDGE = '#3b4b5a'
LIVE_FILL = '#3a3020'
LIVE_EDGE = '#fca101'
PLAYHEAD = '#ff5e7a'


def zoom_to_slider(px_per_s):
    span = math.log(PX_PER_S_MAX / PX_PER_S_MIN)
    ratio = math.log(max(PX_PER_S_MIN, px_per_s) / PX_PER_S_MIN) / span
    return int(round(max(0.0, min(1.0, ratio)) * ZOOM_STEPS))


def slider_to_zoom(value):
    ratio = max(0, min(ZOOM_STEPS, value)) / float(ZOOM_STEPS)
    return PX_PER_S_MIN * (PX_PER_S_MAX / PX_PER_S_MIN) ** ratio


def _fmt(seconds):
    total = int(max(0.0, seconds))
    return '%d:%02d' % (total // 60, total % 60)


def _ruler_step(px_per_s):
    for step in (1, 2, 5, 10, 15, 30, 60, 120, 300):
        if step * px_per_s >= 58:
            return step
    return 600


class WaveformView(QWidget):
    panned = pyqtSignal(int)
    zoomChanged = pyqtSignal(float)
    clicked = pyqtSignal(float)

    def __init__(self, parent=None):
        super(WaveformView, self).__init__(parent)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setMinimumHeight(WAVE_HEIGHT + RULER_HEIGHT)
        self.setCursor(Qt.OpenHandCursor)
        self.setFocusPolicy(Qt.NoFocus)

        self._vocal = b''
        self._peaks_hz = 100.0
        self._duration = 0.0
        self._px_per_s = PX_PER_S_DEFAULT
        self._regions = []
        self._current = 0
        self._live = -1
        self._position = 0.0
        self._pan_from = None
        self._pressed_at = None
        self._moved = 0

    # -- content ---------------------------------------------------------

    def set_audio(self, duration, peaks_hz, vocal):
        self._duration = max(0.0, float(duration))
        self._peaks_hz = float(peaks_hz) or 100.0
        self._vocal = vocal or b''
        self._resize()

    def set_lines(self, count):
        self._regions = [None] * count
        self._current = 0
        self._live = -1
        self.update()

    def set_regions(self, spans):
        for index, span in enumerate(spans):
            if index < len(self._regions):
                self._regions[index] = span
        self.update()

    def regions(self):
        return list(self._regions)

    def region(self, index):
        if 0 <= index < len(self._regions):
            return self._regions[index]
        return None

    def set_region(self, index, span):
        if 0 <= index < len(self._regions):
            self._regions[index] = span
            self.update()

    def current(self):
        return self._current

    def set_current(self, index):
        if 0 <= index < len(self._regions) and index != self._current:
            self._current = index
            self.update()

    def set_live(self, index):
        if index != self._live:
            self._live = index
            self.update()

    def live(self):
        return self._live

    def block_at(self, seconds):
        for index, span in enumerate(self._regions):
            if span is not None and span[0] <= seconds <= span[1]:
                return index
        return -1

    def set_position(self, seconds):
        self._position = max(0.0, float(seconds))
        self.update()

    def duration(self):
        return self._duration

    # -- zoom ------------------------------------------------------------

    def px_per_second(self):
        return self._px_per_s

    def set_px_per_second(self, value):
        value = max(PX_PER_S_MIN, min(PX_PER_S_MAX, float(value)))
        if abs(value - self._px_per_s) < 1e-6:
            return
        self._px_per_s = value
        self._resize()
        self.zoomChanged.emit(value)

    def _resize(self):
        width = max(1, int(round(self._duration * self._px_per_s)))
        self.setFixedWidth(width)
        self.update()

    # -- coordinates -----------------------------------------------------

    def x_for(self, seconds):
        return seconds * self._px_per_s

    def seconds_at(self, x):
        if self._duration <= 0.0:
            return 0.0
        return max(0.0, min(self._duration, x / self._px_per_s))

    # -- painting --------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        clip = event.rect()
        wave_bottom = self.height() - RULER_HEIGHT
        mid = wave_bottom / 2.0

        painter.fillRect(clip, QColor(BACKDROP))
        self._draw_ruler(painter, clip, wave_bottom)
        self._draw_regions(painter, clip, wave_bottom)

        painter.setPen(QPen(QColor(GRID_COLOR), 1))
        painter.drawLine(clip.left(), int(mid), clip.right(), int(mid))
        self._draw_peaks(painter, clip, mid, wave_bottom / 2.0 - 2)

        head = self.x_for(self._position)
        if clip.left() - 2 <= head <= clip.right() + 2:
            painter.setPen(QPen(QColor(PLAYHEAD), 1))
            painter.drawLine(int(head), 0, int(head), int(wave_bottom))

    def _draw_peaks(self, painter, clip, mid, scale):
        data = self._vocal
        if not data or self._duration <= 0.0:
            return
        painter.setPen(QPen(QColor(VOCAL_COLOR), 1))
        per_px = self._peaks_hz / self._px_per_s
        count = len(data)
        for x in range(max(0, clip.left()), clip.right() + 1):
            lo = int(x * per_px)
            hi = max(lo + 1, int((x + 1) * per_px))
            if lo >= count:
                break
            top = max(data[lo:min(hi, count)]) / 255.0
            if top <= 0.0:
                continue
            half = top * scale
            painter.drawLine(x, int(mid - half), x, int(mid + half))

    def _draw_regions(self, painter, clip, bottom):
        painter.setFont(self.font())
        for index, span in enumerate(self._regions):
            if span is None:
                continue
            lit = index == self._current or index == self._live
            self._draw_span(painter, clip, span, bottom, index + 1,
                            LIVE_FILL if lit else BLOCK_FILL,
                            LIVE_EDGE if lit else BLOCK_EDGE)

    def _draw_span(self, painter, clip, span, bottom, number, fill, edge):
        left, right = self.x_for(span[0]), self.x_for(span[1])
        if right < clip.left() - 1 or left > clip.right() + 1:
            return
        rect = QRectF(left, 0.0, max(1.0, right - left), float(bottom))
        painter.fillRect(rect, QColor(fill))
        painter.setPen(QPen(QColor(edge), 1))
        painter.drawLine(int(left), 0, int(left), int(bottom))
        painter.drawLine(int(right), 0, int(right), int(bottom))
        painter.drawText(QRectF(left + 3, 1, 40, 14), Qt.AlignLeft,
                         str(number))

    def _draw_ruler(self, painter, clip, top):
        if self._duration <= 0.0:
            return
        step = _ruler_step(self._px_per_s)
        painter.setPen(QPen(QColor(RULER_TEXT), 1))
        first = int(self.seconds_at(clip.left()) // step) * step
        last = self.seconds_at(clip.right()) + step
        seconds = first
        while seconds <= last:
            x = self.x_for(seconds)
            painter.drawLine(int(x), int(top), int(x), int(top + 4))
            painter.drawText(QRectF(x + 3, top + 1, 60, RULER_HEIGHT - 2),
                             Qt.AlignLeft, _fmt(seconds))
            seconds += step

    # -- panning ---------------------------------------------------------

    def tool_cursor(self, armed):
        self.setCursor(Qt.CrossCursor if armed else Qt.OpenHandCursor)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        self._pan_from = event.globalPos().x()
        self._pressed_at = event.pos().x()
        self._moved = 0

    def mouseMoveEvent(self, event):
        if self._pan_from is None or not (event.buttons() & Qt.LeftButton):
            return
        x = event.globalPos().x()
        self._moved += abs(x - self._pan_from)
        self.panned.emit(x - self._pan_from)
        self._pan_from = x

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or self._pan_from is None:
            return
        pressed, moved = self._pressed_at, self._moved
        self._pan_from = self._pressed_at = None
        self._moved = 0
        if moved <= CLICK_SLOP and pressed is not None:
            self.clicked.emit(self.seconds_at(event.pos().x()))


class WaveformPane(QScrollArea):
    def __init__(self, parent=None):
        super(WaveformPane, self).__init__(parent)
        self.view = WaveformView(self)
        self.setWidget(self.view)
        self.setWidgetResizable(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setMinimumHeight(WAVE_HEIGHT + RULER_HEIGHT + 16)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.view.panned.connect(self._on_panned)

    def resizeEvent(self, event):
        super(WaveformPane, self).resizeEvent(event)
        height = self.viewport().height()
        self.view.setMinimumHeight(height)
        self.view.resize(self.view.width(), height)

    def _on_panned(self, delta):
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - delta)

    def wheelEvent(self, event):
        if not (event.modifiers() & Qt.ControlModifier):
            super(WaveformPane, self).wheelEvent(event)
            return
        bar = self.horizontalScrollBar()
        under = self.view.seconds_at(bar.value() + event.pos().x())
        steps = event.angleDelta().y() / 120.0
        self.view.set_px_per_second(self.view.px_per_second() * (1.2 ** steps))
        bar.setValue(int(round(self.view.x_for(under) - event.pos().x())))

    def center_on(self, seconds):
        bar = self.horizontalScrollBar()
        x = self.view.x_for(seconds)
        bar.setValue(int(round(x - self.viewport().width() / 2.0)))

    def keep_visible(self, seconds, margin=60):
        bar = self.horizontalScrollBar()
        x = self.view.x_for(seconds)
        width = self.viewport().width()
        if x < bar.value() + margin or x > bar.value() + width - margin:
            bar.setValue(int(round(x - width / 2.0)))
