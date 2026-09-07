"""output preview - a 16:9 viewport that mimics how clone hero shows lyrics."""

import array
import math
import os
from collections import deque

from PyQt5.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import (
    QColor, QFont, QFontMetricsF, QPainter, QPen, QPolygonF)
from PyQt5.QtMultimedia import (
    QAudioFormat, QAudioProbe, QMediaContent, QMediaPlayer)
from PyQt5.QtWidgets import QApplication, QWidget

from .spectrum import (
    BAND_CENTERS, DB_CEIL, DB_FLOOR, FFT_SIZE, band_levels)

SUNG_COLOR = '#fca101'
UNSUNG_COLOR = '#ffffff'
NEXT_COLOR = '#9d9d9d'

LINE1_CENTER = 0.130
LINE2_CENTER = 0.178
LINE1_SIZE = 0.0430
LINE2_SIZE = 0.0262

SLIDE_S = 0.180
END_FADE_S = 1.0
IDLE_FADE_S = 10.0

BAR_Y = 0.845
BAR_INSET = 0.12
TIME_Y = 0.915
WAVE_COLOR = '#4a4550'
WAVE_PEAK_COLOR = '#fca101'
PANEL_TEXT = '#8d8d96'
EQ_ATTACK = 0.40
EQ_DECAY_DB = 46.0
EQ_PEAK_HOLD_S = 0.85
EQ_PEAK_FALL_DB = 26.0
RIBBON_BARS = 34
RIBBON_TOP = 0.50
RIBBON_BOTTOM = 0.79
RIBBON_WIDTH = 0.62
BEAT_SWEEP_WIDTH = 0.17
BEAT_PULSE = 0.30
RIBBON_STOPS = ((0.00, (255, 94, 122)),
                (0.38, (252, 161, 1)),
                (0.70, (255, 214, 120)),
                (1.00, (120, 224, 255)))
MONO_KEEP = FFT_SIZE * 2

NUDGE_MS = 2000
NUDGE_FLASH_MS = 260.0
VOLUME_TRACK = 0.055
VOLUME_DEFAULT = 85

AUDIO_FILTER = ('audio files (*.ogg *.opus *.mp3 *.wav *.m4a *.flac);;'
                'all files (*)')


def _fmt_time(ms):
    if ms is None or ms < 0:
        ms = 0
    total = int(ms // 1000)
    return '%02d:%02d' % (total // 60, total % 60)


def _blend(base, accent, amount):
    a, b = QColor(base), QColor(accent)
    return QColor(int(a.red() + (b.red() - a.red()) * amount),
                  int(a.green() + (b.green() - a.green()) * amount),
                  int(a.blue() + (b.blue() - a.blue()) * amount))


class PreviewWindow(QWidget):
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super(PreviewWindow, self).__init__(parent, Qt.Window)
        self.setWindowTitle('output preview')
        self.resize(960, 540)
        self.setMinimumSize(480, 270)
        self.setAutoFillBackground(True)
        self.setStyleSheet('background-color: #000000;')

        self.phrases = []
        self.timing = None
        self._audio_path = None
        self._locking = False
        self._starts = []

        self.player = QMediaPlayer(self)
        self.player.setNotifyInterval(30)
        self.player.setVolume(VOLUME_DEFAULT)
        self.player.positionChanged.connect(self._on_position)
        self.player.stateChanged.connect(self._on_state)

        self._panel_clock = QElapsedTimer()
        self._panel_clock.start()
        self._nudge_at = {'back': -1.0e9, 'ahead': -1.0e9}
        self._scrubbing = False
        self._volume_drag = False

        self._base_ms = 0
        self._since_report = QElapsedTimer()
        self._since_report.start()

        self._mono = deque(maxlen=MONO_KEEP)
        self._analysis = deque()
        self._audio_cursor_ms = 0.0
        self._eq_levels = [DB_FLOOR] * len(BAND_CENTERS)
        self._eq_targets = [DB_FLOOR] * len(BAND_CENTERS)
        self._eq_peaks = [DB_FLOOR] * len(BAND_CENTERS)
        self._eq_peak_age = [0.0] * len(BAND_CENTERS)
        self._have_audio_data = False
        self._anim_clock = QElapsedTimer()
        self._anim_clock.start()
        self.probe = QAudioProbe(self)
        if self.probe.setSource(self.player):
            self.probe.audioBufferProbed.connect(self._on_buffer)

        self._frame = QTimer(self)
        self._frame.setTimerType(Qt.PreciseTimer)
        self._frame.timeout.connect(self.update)
        self._screen_hooked = False
        self._sync_frame_rate()
        self._frame.start()

    def _sync_frame_rate(self):
        hz = 60.0
        handle = self.windowHandle()
        screen = handle.screen() if handle is not None else None
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is not None and screen.refreshRate() > 0:
            hz = screen.refreshRate()
        hz = max(30.0, min(hz, 360.0))
        self._frame.setInterval(max(1, int(round(1000.0 / hz))))

    def showEvent(self, event):
        super(PreviewWindow, self).showEvent(event)
        handle = self.windowHandle()
        if handle is not None and not self._screen_hooked:
            try:
                handle.screenChanged.connect(lambda _s: self._sync_frame_rate())
                self._screen_hooked = True
            except Exception:
                pass
        self._sync_frame_rate()

    # -- waveform ----------------------------------------------------------

    def _on_buffer(self, buf):
        try:
            fmt = buf.format()
            count = buf.byteCount()
            if count <= 0:
                return
            ptr = buf.constData()
            ptr.setsize(count)
            raw = ptr.asstring(count)

            size, kind = fmt.sampleSize(), fmt.sampleType()
            if kind == QAudioFormat.SignedInt and size == 16:
                samples = array.array('h')
                samples.frombytes(raw[:(len(raw) // 2) * 2])
                scale = 1.0 / 32768.0
            elif kind == QAudioFormat.Float and size == 32:
                samples = array.array('f')
                samples.frombytes(raw[:(len(raw) // 4) * 4])
                scale = 1.0
            elif kind == QAudioFormat.UnSignedInt and size == 8:
                samples = array.array('h', [(b - 128) << 8 for b in raw])
                scale = 1.0 / 32768.0
            else:
                return
            if not samples:
                return

            channels = max(1, fmt.channelCount())
            rate = max(1, fmt.sampleRate())
            if channels == 1:
                for v in samples:
                    self._mono.append(v * scale)
            else:
                for i in range(0, len(samples) - channels + 1, channels):
                    self._mono.append(samples[i] * scale)

            span_ms = buf.duration() / 1000.0
            if span_ms <= 0:
                span_ms = (len(samples) / float(channels)) / rate * 1000.0
            audible_at = self._audio_cursor_ms
            self._audio_cursor_ms += span_ms

            if len(self._mono) >= FFT_SIZE:
                levels = band_levels(list(self._mono), rate)
                if levels:
                    self._analysis.append((audible_at, levels))
                    self._have_audio_data = True
        except Exception:
            pass

    def _pump_analysis(self):
        now = self.now_ms()
        while self._analysis and self._analysis[0][0] <= now:
            self._eq_targets = self._analysis.popleft()[1]

    def _advance_eq(self, dt):
        if dt <= 0.0:
            return
        dt = min(dt, 0.1)
        for i, target in enumerate(self._eq_targets):
            level = self._eq_levels[i]
            if target > level:
                level += (target - level) * EQ_ATTACK
            else:
                level = max(target, level - EQ_DECAY_DB * dt)
            self._eq_levels[i] = level

            if level >= self._eq_peaks[i]:
                self._eq_peaks[i] = level
                self._eq_peak_age[i] = 0.0
            else:
                self._eq_peak_age[i] += dt
                if self._eq_peak_age[i] > EQ_PEAK_HOLD_S:
                    self._eq_peaks[i] = max(
                        DB_FLOOR, self._eq_peaks[i] - EQ_PEAK_FALL_DB * dt)

    # -- content -----------------------------------------------------------

    def set_chart(self, phrases, timing):
        self.phrases = phrases
        self.timing = timing
        self._starts = [timing.tick_to_seconds(p.start_tick) for p in phrases]
        self._ends = [timing.tick_to_seconds(p.end_tick) for p in phrases]
        self._first_lyric = [timing.tick_to_seconds(p.syllables[0].tick)
                             for p in phrases]

        self._promote = []
        self._from_silence = []
        for i in range(len(phrases)):
            at = self._starts[i]
            silent = True
            if i > 0:
                if not phrases[i - 1].explicit_end:
                    silent = False
                else:
                    closed = self._ends[i - 1]
                    if self._first_lyric[i] - closed < IDLE_FADE_S:
                        at = min(closed, at)
                        silent = False
            self._promote.append(at)
            self._from_silence.append(silent)

    def set_audio(self, path):
        self._audio_path = path
        self.player.setMedia(QMediaContent(QUrl.fromLocalFile(os.path.abspath(path))))

    def audio_path(self):
        return self._audio_path

    # -- playback ----------------------------------------------------------

    def _reset_analysis(self, ms):
        self._mono.clear()
        self._analysis.clear()
        self._audio_cursor_ms = float(ms)
        self._eq_targets = [DB_FLOOR] * len(BAND_CENTERS)
        self._eq_levels = [DB_FLOOR] * len(BAND_CENTERS)
        self._eq_peaks = [DB_FLOOR] * len(BAND_CENTERS)
        self._eq_peak_age = [0.0] * len(BAND_CENTERS)

    def start_at_tick(self, tick):
        if self.timing is None:
            return
        seconds = max(0.0, self.timing.audio_seconds(tick))
        self._reset_analysis(seconds * 1000.0)
        self.player.setPosition(int(seconds * 1000))
        self._base_ms = int(seconds * 1000)
        self._since_report.restart()
        self.player.play()

    def stop(self):
        self.player.stop()

    def seek_to_ms(self, ms):
        duration = self.player.duration()
        ms = max(0, int(ms))
        if duration > 0:
            ms = min(ms, duration)
        self._reset_analysis(ms)
        self.player.setPosition(ms)
        self._base_ms = ms
        self._since_report.restart()
        self.update()

    def nudge(self, delta_ms):
        self._nudge_at['ahead' if delta_ms > 0 else 'back'] = \
            self._panel_clock.elapsed()
        self.seek_to_ms(self.now_ms() + delta_ms)

    def _nudge_flash(self, key):
        since = self._panel_clock.elapsed() - self._nudge_at[key]
        if since < 0 or since > NUDGE_FLASH_MS:
            return 0.0
        return 1.0 - since / NUDGE_FLASH_MS

    def _on_position(self, ms):
        self._base_ms = ms
        self._since_report.restart()

    def _on_state(self, state):
        if state == QMediaPlayer.StoppedState:
            self._reset_analysis(0.0)
        self._since_report.restart()

    def now_ms(self):
        if self.player.state() == QMediaPlayer.PlayingState:
            return self._base_ms + self._since_report.elapsed()
        return self._base_ms

    def chart_seconds(self):
        seconds = self.now_ms() / 1000.0
        if self.timing is not None:
            seconds -= self.timing.offset
        return seconds

    # -- geometry ----------------------------------------------------------

    def resizeEvent(self, event):
        super(PreviewWindow, self).resizeEvent(event)
        if self._locking:
            return
        target = int(round(self.width() * 9.0 / 16.0))
        if abs(self.height() - target) > 1:
            self._locking = True
            self.resize(self.width(), target)
            self._locking = False

    def _viewport(self):
        w, h = self.width(), self.height()
        if w * 9 > h * 16:
            vh = float(h)
            vw = vh * 16.0 / 9.0
        else:
            vw = float(w)
            vh = vw * 9.0 / 16.0
        return QRectF((w - vw) / 2.0, (h - vh) / 2.0, vw, vh)

    # -- state -------------------------------------------------------------

    def _active_index(self, seconds):
        index = -1
        for i, at in enumerate(self._promote):
            if at <= seconds:
                index = i
            else:
                break
        return index

    def _slide_amount(self, index, seconds):
        if index < 0 or index >= len(self._promote):
            return 0.0
        if self.phrases[index].no_slide or self._from_silence[index]:
            return 0.0
        start = self._promote[index]
        duration = SLIDE_S
        if index + 1 < len(self._promote):
            duration = min(duration, max(0.0, self._promote[index + 1] - start))
        if duration <= 0.0:
            return 0.0
        return max(0.0, 1.0 - (seconds - start) / duration)

    def _phrase_alpha(self, index, seconds):
        if index < 0 or index >= len(self._promote):
            return 0.0
        last = index == len(self._promote) - 1
        if not self.phrases[index].explicit_end and not last:
            return 1.0
        end = self._ends[index]
        if seconds <= end:
            return 1.0
        return max(0.0, 1.0 - (seconds - end) / END_FADE_S)

    # -- painting ----------------------------------------------------------

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.fillRect(self.rect(), QColor('#000000'))

        vp = self._viewport()

        self._draw_panel(p, vp)

        if not self.phrases or self.timing is None:
            p.end()
            return

        seconds = self.chart_seconds()
        index = self._active_index(seconds)

        slide = self._slide_amount(index, seconds)
        gap = (LINE2_CENTER - LINE1_CENTER) * vp.height()
        rise = slide * gap

        alpha = self._phrase_alpha(index, seconds)
        if alpha <= 0.0:
            p.end()
            return

        self._draw_phrase(
            p, vp, self.phrases[index], seconds,
            y=vp.top() + LINE1_CENTER * vp.height() + rise,
            size=LINE1_SIZE * vp.height(),
            karaoke=True, alpha=alpha)

        following = index + 1
        if following < len(self.phrases) and not self._from_silence[following]:
            self._draw_phrase(
                p, vp, self.phrases[following], seconds,
                y=vp.top() + LINE2_CENTER * vp.height() + rise,
                size=LINE2_SIZE * vp.height(),
                karaoke=False, alpha=1.0 - 0.35 * slide)
        p.end()

    def _draw_panel(self, p, vp):
        duration = max(0, self.player.duration())
        position = max(0, self.now_ms())
        if duration:
            position = min(position, duration)
        playing = self.player.state() == QMediaPlayer.PlayingState

        bar = self._bar_rect(vp)
        left, right, width = bar.left(), bar.right(), bar.width()
        self._draw_eq(p, vp)

        # --- progress bar
        by = vp.top() + BAR_Y * vp.height()
        thickness = max(1.0, vp.height() * 0.004)
        p.setPen(QPen(QColor(WAVE_COLOR), thickness))
        p.drawLine(QPointF(left, by), QPointF(right, by))
        if duration > 0:
            frac = min(1.0, position / float(duration))
            p.setPen(QPen(QColor(WAVE_PEAK_COLOR), thickness))
            p.drawLine(QPointF(left, by), QPointF(left + width * frac, by))
            radius = max(2.0, vp.height() * 0.007)
            if self._scrubbing:
                radius *= 1.7
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(WAVE_PEAK_COLOR))
            p.drawEllipse(QPointF(left + width * frac, by), radius, radius)
            p.setBrush(Qt.NoBrush)

        # --- play / pause
        btn = self._button_rect(vp)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(PANEL_TEXT))
        if playing:
            w = btn.width() * 0.30
            p.drawRect(QRectF(btn.left(), btn.top(), w, btn.height()))
            p.drawRect(QRectF(btn.right() - w, btn.top(), w, btn.height()))
        else:
            p.drawPolygon(QPolygonF([
                QPointF(btn.left(), btn.top()),
                QPointF(btn.right(), btn.center().y()),
                QPointF(btn.left(), btn.bottom())]))
        p.setBrush(Qt.NoBrush)

        # --- nudge
        hint = QFont('Segoe UI')
        hint.setPixelSize(max(7, int(vp.height() * 0.019)))
        for ahead, key in ((False, 'back'), (True, 'ahead')):
            rect = self._nudge_rect(vp, ahead)
            color = _blend(PANEL_TEXT, WAVE_PEAK_COLOR, self._nudge_flash(key))
            self._draw_nudge(p, rect, ahead, color)
            p.setPen(color)
            p.setFont(hint)
            p.drawText(QRectF(rect.left() - rect.width() * 0.5,
                              rect.bottom() + rect.height() * 0.16,
                              rect.width() * 2.0, rect.height()),
                       Qt.AlignHCenter | Qt.AlignTop, '%ds' % (NUDGE_MS // 1000))

        # --- volume
        self._draw_volume(p, vp)

        # --- clock
        font = QFont('Segoe UI')
        font.setPixelSize(max(9, int(vp.height() * 0.027)))
        p.setFont(font)
        p.setPen(QColor(PANEL_TEXT))
        label = '%s / %s' % (_fmt_time(position), _fmt_time(duration))
        ty = vp.top() + TIME_Y * vp.height()
        p.drawText(QRectF(vp.left(), ty - vp.height() * 0.035,
                          vp.width(), vp.height() * 0.07),
                   Qt.AlignHCenter | Qt.AlignVCenter, label)

    @staticmethod
    def _ribbon_color(u):
        stops = RIBBON_STOPS
        for i in range(len(stops) - 1):
            a, ca = stops[i]
            b, cb = stops[i + 1]
            if u <= b or i == len(stops) - 2:
                f = 0.0 if b <= a else max(0.0, min(1.0, (u - a) / (b - a)))
                return tuple(ca[k] + (cb[k] - ca[k]) * f for k in range(3))
        return stops[-1][1]

    def _draw_eq(self, p, vp):
        self._pump_analysis()
        self._advance_eq(self._anim_clock.restart() / 1000.0)

        bands = self._eq_levels
        span = DB_CEIL - DB_FLOOR
        top = vp.top() + RIBBON_TOP * vp.height()
        bottom = vp.top() + RIBBON_BOTTOM * vp.height()
        cy = (top + bottom) / 2.0
        reach = (bottom - top) / 2.0
        total = RIBBON_WIDTH * vp.width()
        left = vp.center().x() - total / 2.0
        colw = total / RIBBON_BARS
        barw = colw * 0.56
        radius = barw * 0.5

        phase = 0.0
        if self.timing is not None:
            phase = self.timing.beats_at(max(0.0, self.chart_seconds())) % 1.0
        kick = (1.0 - phase) ** 3

        p.setPen(Qt.NoPen)
        last = len(bands) - 1
        for i in range(RIBBON_BARS):
            u = i / float(RIBBON_BARS - 1)
            f = u * last
            lo = int(f)
            hi = min(lo + 1, last)
            t = f - lo
            t = t * t * (3.0 - 2.0 * t)
            db = bands[lo] + (bands[hi] - bands[lo]) * t
            level = max(0.0, min(1.0, (db - DB_FLOOR) / span))

            d = abs(u - phase)
            d = min(d, 1.0 - d)
            glow = math.exp(-(d / BEAT_SWEEP_WIDTH) ** 2)

            h = reach * level * (1.0 + BEAT_PULSE * kick * 0.5 + glow * 0.30)
            h = max(1.2, min(reach, h))

            r, g, b = self._ribbon_color(u)
            boost = glow * 0.85 + kick * 0.12
            p.setBrush(QColor(int(min(255, r + (255 - r) * boost)),
                              int(min(255, g + (255 - g) * boost)),
                              int(min(255, b + (255 - b) * boost))))
            x = left + i * colw + (colw - barw) / 2.0
            p.drawRoundedRect(QRectF(x, cy - h, barw, h * 2.0), radius, radius)
        p.setBrush(Qt.NoBrush)

    def _button_rect(self, vp):
        size = vp.height() * 0.040
        cx = vp.left() + (BAR_INSET * 0.5) * vp.width()
        cy = vp.top() + BAR_Y * vp.height()
        return QRectF(cx - size / 2.0, cy - size / 2.0, size, size)

    def _nudge_rect(self, vp, ahead):
        base = self._button_rect(vp)
        step = base.width() * 1.45
        return base.translated(step if ahead else -step, 0.0)

    def _bar_rect(self, vp):
        left = vp.left() + BAR_INSET * vp.width()
        right = vp.right() - BAR_INSET * vp.width()
        by = vp.top() + BAR_Y * vp.height()
        grab = max(6.0, vp.height() * 0.024)
        return QRectF(left, by - grab, right - left, grab * 2.0)

    def _volume_rect(self, vp):
        width = VOLUME_TRACK * vp.width()
        height = max(3.0, vp.height() * 0.010)
        right = vp.right() - 0.022 * vp.width()
        cy = vp.top() + BAR_Y * vp.height()
        return QRectF(right - width, cy - height / 2.0, width, height)

    @staticmethod
    def _draw_nudge(p, rect, ahead, color):
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        w = rect.width() * 0.46
        for index in range(2):
            x = rect.left() + index * w
            if ahead:
                p.drawPolygon(QPolygonF([
                    QPointF(x, rect.top()),
                    QPointF(x + w, rect.center().y()),
                    QPointF(x, rect.bottom())]))
            else:
                p.drawPolygon(QPolygonF([
                    QPointF(x + w, rect.top()),
                    QPointF(x, rect.center().y()),
                    QPointF(x + w, rect.bottom())]))
        p.setBrush(Qt.NoBrush)

    @staticmethod
    def _draw_speaker(p, rect, color, level):
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        body = QRectF(rect.left(), rect.top() + rect.height() * 0.33,
                      rect.width() * 0.32, rect.height() * 0.34)
        p.drawRect(body)
        p.drawPolygon(QPolygonF([
            QPointF(body.right(), rect.top() + rect.height() * 0.16),
            QPointF(rect.left() + rect.width() * 0.66,
                    rect.top() + rect.height() * 0.16),
            QPointF(rect.left() + rect.width() * 0.66,
                    rect.bottom() - rect.height() * 0.16),
            QPointF(body.right(), rect.bottom() - rect.height() * 0.16)]))
        p.setBrush(Qt.NoBrush)
        if level > 0.0:
            pen = QPen(color)
            pen.setWidthF(max(1.0, rect.width() * 0.09))
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            arc = QRectF(rect.left() + rect.width() * 0.48,
                         rect.top() + rect.height() * 0.14,
                         rect.width() * 0.62, rect.height() * 0.72)
            p.drawArc(arc, -55 * 16, 110 * 16)
            p.setPen(Qt.NoPen)

    def _draw_volume(self, p, vp):
        track = self._volume_rect(vp)
        level = max(0.0, min(1.0, self.player.volume() / 100.0))
        icon = QRectF(track.left() - vp.width() * 0.032,
                      track.center().y() - vp.height() * 0.017,
                      vp.width() * 0.021, vp.height() * 0.034)
        self._draw_speaker(p, icon, QColor(PANEL_TEXT), level)

        radius = track.height() / 2.0
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(WAVE_COLOR))
        p.drawRoundedRect(track, radius, radius)
        if level > 0.0:
            p.setBrush(QColor(WAVE_PEAK_COLOR))
            p.drawRoundedRect(
                QRectF(track.left(), track.top(),
                       track.width() * level, track.height()),
                radius, radius)
        knob = max(2.5, track.height() * 1.15)
        p.setBrush(QColor(WAVE_PEAK_COLOR if level > 0.0 else PANEL_TEXT))
        p.drawEllipse(
            QPointF(track.left() + track.width() * level, track.center().y()),
            knob, knob)
        p.setBrush(Qt.NoBrush)

    def _apply_scrub(self, x):
        bar = self._bar_rect(self._viewport())
        duration = self.player.duration()
        if duration <= 0 or bar.width() <= 0:
            return
        frac = max(0.0, min(1.0, (x - bar.left()) / bar.width()))
        self.seek_to_ms(frac * duration)

    def _apply_volume(self, x):
        track = self._volume_rect(self._viewport())
        if track.width() <= 0:
            return
        frac = max(0.0, min(1.0, (x - track.left()) / track.width()))
        self.player.setVolume(int(round(frac * 100)))
        self.update()

    def toggle_play(self):
        if self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            vp = self._viewport()
            pos = event.pos()
            if self._button_rect(vp).adjusted(-8, -8, 8, 8).contains(pos):
                self.toggle_play()
                return
            for ahead, step in ((False, -NUDGE_MS), (True, NUDGE_MS)):
                hit = self._nudge_rect(vp, ahead).adjusted(-6, -6, 6, 6)
                if hit.contains(pos):
                    self.nudge(step)
                    return
            if self._volume_rect(vp).adjusted(-8, -10, 8, 10).contains(pos):
                self._volume_drag = True
                self._apply_volume(pos.x())
                return
            if self._bar_rect(vp).contains(pos):
                self._scrubbing = True
                self._apply_scrub(pos.x())
                return
        super(PreviewWindow, self).mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._scrubbing:
            self._apply_scrub(event.pos().x())
            return
        if self._volume_drag:
            self._apply_volume(event.pos().x())
            return
        super(PreviewWindow, self).mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._scrubbing or self._volume_drag:
            self._scrubbing = False
            self._volume_drag = False
            self.update()
            return
        super(PreviewWindow, self).mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            self.toggle_play()
            return
        if event.key() == Qt.Key_Left:
            self.nudge(-NUDGE_MS)
            return
        if event.key() == Qt.Key_Right:
            self.nudge(NUDGE_MS)
            return
        super(PreviewWindow, self).keyPressEvent(event)

    # -- run layout --------------------------------------------------------

    @staticmethod
    def _font_for(style, size):
        font = QFont('Segoe UI')
        px = size
        if style.sub or style.sup:
            px = size * 0.62
        font.setPixelSize(max(7, int(round(px))))
        font.setBold(style.bold)
        font.setItalic(style.italic)
        if style.smallcaps:
            font.setCapitalization(QFont.SmallCaps)
        if style.cspace:
            font.setLetterSpacing(QFont.AbsoluteSpacing, style.cspace * size)
        return font

    def _pieces(self, phrase, size):
        out = []
        for i, syl in enumerate(phrase.syllables):
            runs = list(syl.runs)
            for j, run in enumerate(runs):
                text = run.style.apply_text(run.text)
                if j == len(runs) - 1:
                    if syl.join == '=':
                        text += '-'
                    elif syl.join != '-' and i < len(phrase.syllables) - 1:
                        text += ' '
                if not text:
                    continue
                font = self._font_for(run.style, size)
                fm = QFontMetricsF(font)
                if run.style.mspace > 0:
                    advance = run.style.mspace * size
                    width = advance * len(text)
                else:
                    width = fm.horizontalAdvance(text)
                out.append((syl.tick, text, run.style, font, width, fm))

        while out and not out[-1][1].strip():
            out.pop()
        while out and not out[0][1].strip():
            out.pop(0)
        if out:
            tick, text, style, font, _w, fm = out[-1]
            trimmed = text.rstrip()
            if trimmed != text:
                if style.mspace > 0:
                    width = style.mspace * size * len(trimmed)
                else:
                    width = fm.horizontalAdvance(trimmed)
                out[-1] = (tick, trimmed, style, font, width, fm)
        return out

    def _draw_phrase(self, p, vp, phrase, seconds, y, size, karaoke, alpha):
        pieces = self._pieces(phrase, size)
        if not pieces:
            return
        total = sum(w for _t, _x, _s, _f, w, _m in pieces)
        x = vp.center().x() - total / 2.0

        for tick, text, style, font, width, fm in pieces:
            sung = karaoke and self.timing.tick_to_seconds(tick) <= seconds
            if sung:
                color = QColor(style.sung_color or SUNG_COLOR)
            elif style.base_color:
                color = QColor(style.base_color)
            else:
                color = QColor(UNSUNG_COLOR if karaoke else NEXT_COLOR)
            if not color.isValid():
                color = QColor(SUNG_COLOR if sung else UNSUNG_COLOR)
            color.setAlphaF(max(0.0, min(1.0, alpha)))

            offset = -style.voffset * size
            if style.sup:
                offset -= size * 0.30
            elif style.sub:
                offset += size * 0.16

            p.setPen(color)
            p.setFont(font)
            baseline = y + fm.capHeight() / 2.0 + offset
            if style.mspace > 0:
                advance = style.mspace * size
                cx = x
                for ch in text:
                    p.drawText(QRectF(cx, baseline - fm.ascent(), advance, fm.height()),
                               Qt.AlignHCenter | Qt.AlignVCenter, ch)
                    cx += advance
            else:
                p.drawText(QRectF(x, baseline - fm.ascent(), width + 2, fm.height()),
                           Qt.AlignLeft | Qt.AlignVCenter, text)
            x += width

    # -- lifecycle ---------------------------------------------------------

    def closeEvent(self, event):
        self._frame.stop()
        self.player.stop()
        self.closed.emit()
        super(PreviewWindow, self).closeEvent(event)
