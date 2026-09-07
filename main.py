"""intro no jutsu - a lyric editor for clone hero .chart files."""

import base64
import configparser
import math
import os
import re
import sys
import tempfile
import time

import chardet
from PyQt5.QtCore import (
    QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer)
from PyQt5.QtGui import (
    QColor, QFont, QFontMetrics, QIcon, QIntValidator, QKeySequence, QPainter,
    QPalette, QPen, QPixmap, QTextCursor, QTextFormat)
from PyQt5.QtWidgets import (
    QAction, QApplication, QDialog, QDialogButtonBox, QFileDialog, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QRadioButton, QShortcut, QGraphicsDropShadowEffect, QSizeGrip, QSizePolicy,
    QSlider, QSplitter, QStackedWidget, QTextEdit, QToolButton, QVBoxLayout,
    QWhatsThis, QWidget, QWidgetAction, QAbstractSpinBox, QDoubleSpinBox)

from data import img  # noqa: F401
from data.colorpicker import ColorPicker
from data.Highlighter import Highlighter
from data.LCJutsu import LyricColorJutsu
from data.paths import app_dir, resource_dir, settings_path
from data.preview import AUDIO_FILTER, PreviewWindow
from data.syncrunner import SyncRunner
from data.timing import ChartTiming, parse_phrases
from data.mixplayer import ORIGINAL_LEVEL, VOCAL_LEVEL, MixPlayer
from data.waveform import (
    PX_PER_S_DEFAULT, ZOOM_STEPS, WaveformPane, slider_to_zoom, zoom_to_slider)
from data import sfx
from worker import models as sync_models
from worker.protocol import COUNTED_STAGES
from data.theme import apply_theme, system_prefers_dark

APP_VERSION = 'v0.7.0'
APP_NAME = 'intro no jutsu'

PHRASE_START_RE = re.compile(r'^\s*(\d+)\s*=\s*E\s*"phrase_start"\s*$')
PHRASE_END_RE = re.compile(r'^\s*(\d+)\s*=\s*E\s*"phrase_end"\s*$')
TICK_RE = re.compile(r'^\s*(\d+)\s*=')
LYRIC_RE = re.compile(r'^\s*(\d+)\s*=\s*E\s*"lyric ?(.*)"\s*$')
SECTION_RE = re.compile(r'^\s*(\d+)\s*=\s*E\s*"section (.*)"\s*$')
SECTION_HEAD_RE = re.compile(r'^\s*\[([^\]]+)\]\s*$')

FORK_URL = 'https://masterthe8.github.io/eLJe-LyricJutsuEditor/'
SPEC_URL = ('https://docs.google.com/document/d/'
            '1v2v0U-9HQ5qHeccpExDOLJ5CMPZZ3QytPmAG5WF0Kzs/'
            'edit?tab=t.0#heading=h.db6ovgw5uat6')
CHARTER_URL = 'https://www.enchor.us/?charter=rdyd'
PIX_URL = 'https://www.enchor.us/?charter=pix_'
INTRO_URL = 'https://www.enchor.us/?charter=intro'

DEFAULT_CLOSING_LYRIC = '-'
DEFAULT_HIDDEN_LYRIC = '_'

PHRASE_LEAD_TICKS = 96
MIN_PHRASE_LEAD = 2
SEPARATE_XREALTIME = 1.5
LISTEN_XREALTIME = 11.4
STAGE_OVERHEAD_S = 4.0
DOTS_MS = 420

NEW_BLOCK_S = 1.0
BLOCK_STEP_S = 0.1
FINE_STEP_S = 0.01
MIN_BLOCK_S = 0.20
WORDS_HINT = ('type what you hear!\n'
              'please only one\n'
              'lyrical phrase\n'
              'per line\n'
              '(baby, baby)')
GUESS_LEAD_S = 0.35
GUESS_TAIL_S = 0.75

SYNC_MONO = ('font-family: Consolas, "Courier New", monospace;'
             ' font-weight: bold; letter-spacing: 0.4px;')
SYNC_NOTE_COLOR = '#b0883c'

SYNC_WARNING = (
    '!!! this tool does NOT accept per-syllable input !!!\n'
    'it WILL make mistakes and is best used as a base\n'
    'to then refine. there is NO SUPPORT provided for\n'
    'this feature. if youre that worried about how the\n'
    'output looks, you shouldnt be using this tool at all')

SYNC_WARNING_STYLE = (
    'QLabel { border: 4px double #d9534f; background: #1d1210;'
    ' color: #ff8f80; padding: 12px 16px;'
    ' font-family: Consolas, "Courier New", monospace; }')

SHOUT_RE = re.compile(r'(!{3}|[A-Z]{2,})')


def shouted(text):
    return SHOUT_RE.sub(r'<b>\1</b>', text).replace('\n', '<br>')

JUTSU_NO_SLIDEUP = 'no_slideup'
JUTSU_HIDE_NEXT = 'hide_next'
JUTSU_LYRIC_COLOR = 'lyric_color'
JUTSU_FAKE_NEXT = 'fake_next'

EDITOR_BG = '#151515'
PHRASE_BG = '#2c3b34'
PHRASE_BG_ACTIVE = '#40694f'
LYRIC_BG = '#33344a'
LYRIC_BG_ACTIVE = '#3d5a80'

MARK_COLORS = {
    'phrase': (PHRASE_BG, PHRASE_BG_ACTIVE),
    'lyric': (LYRIC_BG, LYRIC_BG_ACTIVE),
}

TAG_ACCENT_COLOR = '#e08a00'

AUTOSCROLL_DEADZONE = 14
AUTOSCROLL_DIVISOR = 13.0
AUTOSCROLL_INTERVAL = 16
ATTACK_FRACTION = 0.16

TAG_SPECS = [
    dict(tip='bold', open='<b>', close='</b>', glyph='B', bold=True,
         cfg='b_tag', key='Ctrl+B'),
    dict(tip='italic', open='<i>', close='</i>', glyph='I', italic=True,
         cfg='i_tag', key='Ctrl+I'),
    dict(tip='color', open='<color=#>', close='</color>', glyph='A',
         bold=True, accent=True, pick_color=True,
         cfg='color_tag', key='Ctrl+L'),
    dict(tip='line break', open='<br>', close='', glyph='¶',
         cfg='br_tag', key='Ctrl+K'),
    dict(tip='vertical offset', open='<voffset=0>', close='</voffset>', glyph='↕',
         cfg='voffset_tag', key='Ctrl+J'),
    dict(tip='small caps', open='<smallcaps>', close='</smallcaps>',
         glyph='A', tail='A', cfg='smallcaps_tag', key='Ctrl+/'),
    dict(tip='monospace', open='<mspace=0>', close='</mspace>', draw='monospace',
         cfg='mspace_tag', key='Ctrl+M'),
    dict(tip='character spacing', open='<cspace=0>', close='</cspace>', draw='cspace',
         cfg='cspace_tag', key='Ctrl+N'),
    dict(tip='subscript', open='<sub>', close='</sub>', glyph='x', sub='2',
         cfg='sub_tag', key='Ctrl+;'),
    dict(tip='superscript', open='<sup>', close='</sup>', glyph='x', sup='2',
         cfg='sup_tag', key="Ctrl+'"),
]


def _draw_monospace(p, size, color):
    pen = QPen(color)
    pen.setWidthF(max(1.0, size * 0.055))
    p.setPen(pen)

    cell_w = size * 0.34
    cell_h = size * 0.60
    top = (size - cell_h) / 2.0
    left = (size - cell_w * 2) / 2.0

    for index in range(2):
        p.drawRect(QRectF(left + index * cell_w, top, cell_w, cell_h))

    font = QFont('Georgia')
    font.setPixelSize(max(7, int(size * 0.36)))
    p.setFont(font)
    for index, ch in enumerate(('i', 'm')):
        p.drawText(QRectF(left + index * cell_w, top, cell_w, cell_h),
                   Qt.AlignCenter, ch)


def _draw_cspace(p, size, color):
    pen = QPen(color)
    pen.setWidthF(max(1.0, size * 0.05))
    p.setPen(pen)

    font = QFont('Georgia')
    font.setPixelSize(max(8, int(size * 0.46)))
    p.setFont(font)
    letter_w = size * 0.30
    p.drawText(QRectF(0, 0, letter_w, size), Qt.AlignCenter, 'A')
    p.drawText(QRectF(size - letter_w, 0, letter_w, size), Qt.AlignCenter, 'A')

    mid_y = size / 2.0
    x0, x1 = letter_w + size * 0.04, size - letter_w - size * 0.04
    p.drawLine(QPointF(x0, mid_y), QPointF(x1, mid_y))
    head = size * 0.10
    for x, direction in ((x0, 1), (x1, -1)):
        tip = QPointF(x, mid_y)
        p.drawLine(tip, QPointF(x + head * direction, mid_y - head * 0.7))
        p.drawLine(tip, QPointF(x + head * direction, mid_y + head * 0.7))

CUSTOM_DRAW = {'monospace': _draw_monospace, 'cspace': _draw_cspace}


def make_tag_icon(spec, base_color, size=22):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)

    color = QColor(TAG_ACCENT_COLOR) if spec.get('accent') else base_color

    custom = CUSTOM_DRAW.get(spec.get('draw'))
    if custom is not None:
        custom(p, size, color)
        p.end()
        return QIcon(pm)

    glyph = spec['glyph']
    tail, sup, sub = spec.get('tail'), spec.get('sup'), spec.get('sub')

    scale = {1: 0.72, 2: 0.52, 3: 0.42}.get(len(glyph.replace(' ', '')), 0.44)
    font = QFont('Georgia')
    font.setPixelSize(max(9, int(size * scale)))
    font.setBold(bool(spec.get('bold')))
    font.setItalic(bool(spec.get('italic')))
    p.setFont(font)
    p.setPen(color)

    if tail:
        big = QFont(font)
        big.setPixelSize(max(9, int(size * 0.80)))
        small = QFont(font)
        small.setPixelSize(max(7, int(size * 0.46)))

        fm_big, fm_small = QFontMetrics(big), QFontMetrics(small)
        w_big, w_small = fm_big.width(glyph), fm_small.width(tail)
        x = (size - (w_big + w_small)) / 2.0
        baseline = (size + fm_big.capHeight()) / 2.0

        p.setFont(big)
        p.drawText(int(round(x)), int(round(baseline)), glyph)
        p.setFont(small)
        p.drawText(int(round(x + w_big)), int(round(baseline)), tail)
    elif sup or sub:
        p.drawText(QRect(0, 0, int(size * 0.66), size), Qt.AlignCenter, glyph)
        small = QFont(font)
        small.setPixelSize(max(7, int(size * 0.36)))
        small.setBold(True)
        p.setFont(small)
        box = QRect(int(size * 0.52), int(size * 0.06) if sup else int(size * 0.36),
                    int(size * 0.46), int(size * 0.58))
        p.drawText(box, Qt.AlignCenter, sup or sub)
    else:
        p.drawText(QRect(0, 0, size, size), Qt.AlignCenter, glyph)

    p.end()
    return QIcon(pm)


def titlebar_icon(kind, color, size=20):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(color))
    pen.setWidthF(1.25)
    p.setPen(pen)

    box = size * 0.5
    left = (size - box) / 2.0
    top = (size - box) / 2.0
    right = left + box
    bottom = top + box

    if kind == 'min':
        middle = (top + bottom) / 2.0
        p.drawLine(QPointF(left, middle), QPointF(right, middle))
    elif kind == 'max':
        p.drawRect(QRectF(left, top, box, box))
    else:
        p.drawLine(QPointF(left, top), QPointF(right, bottom))
        p.drawLine(QPointF(right, top), QPointF(left, bottom))
    p.end()
    return pm


def tool_icon(kind, color, size=18):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(color))
    pen.setWidthF(1.3)
    p.setPen(pen)

    if kind == 'split':
        p.drawLine(QPointF(4, 3), QPointF(13, 12))
        p.drawLine(QPointF(14, 3), QPointF(5, 12))
        p.drawEllipse(QPointF(4.5, 14.0), 2.2, 2.2)
        p.drawEllipse(QPointF(13.5, 14.0), 2.2, 2.2)
    else:
        p.drawRect(QRectF(2.5, 2.5, size - 5, size - 5))
        middle = size / 2.0
        p.drawLine(QPointF(middle, 5.5), QPointF(middle, size - 5.5))
        p.drawLine(QPointF(5.5, middle), QPointF(size - 5.5, middle))
    p.end()
    return pm


class TitleBar(QWidget):
    HEIGHT = 34

    def __init__(self, window, parent=None):
        super(TitleBar, self).__init__(parent)
        self.win = window
        self._drag = None
        self.setFixedHeight(self.HEIGHT)

        dark = system_prefers_dark()
        hover = 'rgba(255,255,255,0.10)' if dark else 'rgba(0,0,0,0.08)'
        close_hover = '#c42b1c'

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(0)

        title = QLabel(APP_NAME, self)
        title.setStyleSheet('color: #8d8d96; font-size: 12px;')
        layout.addWidget(title)
        layout.addStretch(1)

        for kind, slot, danger in (('min', self.win.showMinimized, False),
                                   ('max', self._toggle_max, False),
                                   ('close', self.win.close, True)):
            icon = QIcon(titlebar_icon(kind, '#9d9da8'))
            icon.addPixmap(titlebar_icon(kind, '#ffffff'), QIcon.Active)
            button = QPushButton(self)
            button.setIcon(icon)
            button.setIconSize(QSize(20, 20))
            button.setFixedSize(46, self.HEIGHT)
            button.setFlat(True)
            button.setFocusPolicy(Qt.NoFocus)
            button.setStyleSheet(
                'QPushButton { border: none; background: transparent; }'
                'QPushButton:hover { background: %s; }'
                % (close_hover if danger else hover))
            button.clicked.connect(slot)
            layout.addWidget(button)

    def _toggle_max(self):
        if self.win.isMaximized():
            self.win.showNormal()
        else:
            self.win.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag = event.globalPos() - self.win.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            if self.win.isMaximized():
                self.win.showNormal()
                self._drag = QPoint(self.win.width() // 2, self.HEIGHT // 2)
            self.win.move(event.globalPos() - self._drag)

    def mouseReleaseEvent(self, _event):
        self._drag = None

    def mouseDoubleClickEvent(self, _event):
        self._toggle_max()


class FakePhraseDialog(QDialog):
    def __init__(self, parent=None):
        super(FakePhraseDialog, self).__init__(parent)
        self.setWindowTitle('fake next phrase')
        self.setMinimumWidth(320)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(6)
        layout.addWidget(QLabel('do what?', self))

        self.field = QLineEdit(self)
        self.field.returnPressed.connect(self.accept)
        layout.addWidget(self.field)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.button(QDialogButtonBox.Ok).setText('ok')
        buttons.button(QDialogButtonBox.Cancel).setText('cancel')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addSpacing(6)
        layout.addWidget(buttons)

    def phrase(self):
        return self.field.text()

    @staticmethod
    def ask(parent=None):
        dialog = FakePhraseDialog(parent)
        if dialog.exec_() == QDialog.Accepted:
            return dialog.phrase()
        return None


class GlobalGroupingDialog(QDialog):
    def __init__(self, tick=None, layers=3, parent=None):
        super(GlobalGroupingDialog, self).__init__(parent)
        self.setWindowTitle('insert global event grouping')
        self.setMinimumWidth(320)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(6)
        layout.addWidget(QLabel('at which tick?', self))

        self.field = QLineEdit(self)
        self.field.setValidator(QIntValidator(0, 2147483647, self))
        if tick is not None:
            self.field.setText(str(tick))
        self.field.selectAll()
        self.field.returnPressed.connect(self.accept)
        layout.addWidget(self.field)

        layout.addSpacing(8)
        self.three = QRadioButton('3 layer grouping', self)
        self.five = QRadioButton('5 layer grouping', self)
        (self.five if layers == 5 else self.three).setChecked(True)
        layout.addWidget(self.three)
        layout.addWidget(self.five)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.button(QDialogButtonBox.Ok).setText('ok')
        buttons.button(QDialogButtonBox.Cancel).setText('cancel')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addSpacing(8)
        layout.addWidget(buttons)

    def values(self):
        text = self.field.text().strip()
        return (int(text) if text.isdigit() else None,
                5 if self.five.isChecked() else 3)

    @staticmethod
    def ask(tick=None, layers=3, parent=None):
        dialog = GlobalGroupingDialog(tick, layers, parent)
        if dialog.exec_() == QDialog.Accepted:
            return dialog.values()
        return None


class TimeSpin(QDoubleSpinBox):
    def __init__(self, parent=None):
        super(TimeSpin, self).__init__(parent)
        self.setDecimals(2)
        self.setSingleStep(BLOCK_STEP_S)
        self.setRange(0.0, 24 * 3600.0)
        self.setAccelerated(True)
        self.setKeyboardTracking(False)
        self.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
        self.setAlignment(Qt.AlignRight)
        self.setFixedWidth(116)
        self.setToolTip('wheel or arrows step 0.1s, hold shift for 0.01s')

    def textFromValue(self, value):
        value = max(0.0, value)
        return '%dm %05.2fs' % (int(value) // 60,
                                value - 60 * (int(value) // 60))

    def stepBy(self, steps):
        if QApplication.keyboardModifiers() & Qt.ShiftModifier:
            self.setValue(self.value() + steps * FINE_STEP_S)
            return
        super(TimeSpin, self).stepBy(steps)

    def wheelEvent(self, event):
        notches = int(round(event.angleDelta().y() / 120.0))
        if notches == 0:
            return
        fine = bool(event.modifiers() & Qt.ShiftModifier)
        self.setValue(self.value()
                      + notches * (FINE_STEP_S if fine else BLOCK_STEP_S))
        event.accept()

    def valueFromText(self, text):
        digits = text.replace('m', ' ').replace('s', ' ').split()
        try:
            if len(digits) >= 2:
                return float(digits[0]) * 60.0 + float(digits[1])
            return float(digits[0]) if digits else 0.0
        except ValueError:
            return 0.0

    def validate(self, text, pos):
        from PyQt5.QtGui import QValidator
        return (QValidator.Acceptable, text, pos)


class SyncSession(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.audio = ''
        self.emissions = None
        self.wavs = []
        self.prepared = None
        self.mode = 'paste'
        self.lyrics = ''
        self.lines = []
        self.guess = []
        self.touched = set()
        self.blocks = []
        self.block_text = []
        self.regions = []
        self.inserted = set()

    def alive(self):
        if self.prepared is None or not self.emissions or len(self.wavs) != 2:
            return False
        return all(path and os.path.exists(path)
                   for path in [self.emissions] + list(self.wavs))

    def drop(self):
        for path in [self.emissions] + list(self.wavs):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        self.reset()


class AutoSyncDialog(QDialog):
    def __init__(self, timing, audio_path=None, parent=None, session=None):
        super(AutoSyncDialog, self).__init__(parent)
        self.setWindowTitle('auto-sync lyrics')
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.resize(980, 660)
        self.setMinimumSize(760, 540)

        self.timing = timing
        self._session = session
        self._prepared = None
        self._inserted = set()
        self._recenter = False
        self._audio = audio_path or ''
        self._emissions = None
        self._placements = []
        self._lines = []
        self._guess = []
        self._touched = set()
        self._blocks = []
        self._audio_files = []
        self._playing_all = False
        self._following = False
        self._block_text = []
        self._block_lines = []
        self._align_order = []
        self._editing = -1
        self._mode = 'paste'
        self._note = ''
        self._phase = None
        self._done_stages = []
        self._stage = None
        self._dots = 0
        self._duration = 0.0
        self._eta_started = 0.0
        self._eta_budget = 0.0

        self._dot_clock = QTimer(self)
        self._dot_clock.setInterval(DOTS_MS)
        self._dot_clock.timeout.connect(self._on_dot)

        self.stack = QStackedWidget(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 12)
        outer.setSpacing(8)
        outer.addWidget(self.stack)

        self.stack.addWidget(self._build_setup())
        self.stack.addWidget(self._build_busy())
        self.stack.addWidget(self._build_drag())

        self.player = MixPlayer(self)
        self.player.positionChanged.connect(self._on_position)
        self.player.stopped.connect(self._on_playback_stopped)


        self.runner = SyncRunner(self)
        self.runner.progress.connect(self._on_progress)
        self.runner.info.connect(self._on_info)
        self.runner.finished.connect(self._on_finished)
        self.runner.failed.connect(self._on_failed)
        self.runner.cancelled.connect(self._on_cancelled)

        self._refresh_audio_label()
        if session is not None and session.alive():
            self._restore()

    def _restore(self):
        session = self._session
        self._audio = session.audio
        self._emissions = session.emissions
        self._audio_files = list(session.wavs)
        self._prepared = session.prepared
        self._mode = session.mode
        self._lines = [list(words) for words in session.lines]
        self._guess = [list(starts) for starts in session.guess]
        self._touched = set(session.touched)
        self._block_text = list(session.block_text)
        self._inserted = set(session.inserted)
        self.lyrics.setPlainText(session.lyrics)

        regions = [None if span is None else (span[0], span[1])
                   for span in session.regions]
        self._blocks = [span for span in regions if span is not None]
        view = self.pane.view
        prepared = self._prepared or {}
        view.set_audio(prepared.get('duration', 0.0),
                       prepared.get('peaks_hz', 100),
                       base64.b64decode(prepared.get('vocal_peaks', '')))
        view.set_lines(len(regions))
        view.set_regions(regions)
        if len(self._audio_files) == 2:
            self.player.set_sources(*self._audio_files)
            self._on_levels()
        self._recenter = True
        self._show_drag('')

    def showEvent(self, event):
        super(AutoSyncDialog, self).showEvent(event)
        if self._recenter:
            self._recenter = False
            QTimer.singleShot(0, self._center_current)

    def _center_current(self):
        span = self.pane.view.region(self.line_list.currentRow())
        if span is not None:
            self.pane.center_on(span[0])

    # -- pages -----------------------------------------------------------

    def _build_setup(self):
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        audio_head = QLabel('current audio file:', page)
        audio_head.setStyleSheet(SYNC_MONO)
        layout.addWidget(audio_head)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.audio_field = QLineEdit(page)
        self.audio_field.setReadOnly(True)
        self.audio_field.setPlaceholderText('no audio chosen')
        browse = QPushButton('browse...', page)
        browse.clicked.connect(self._choose_audio)
        row.addWidget(self.audio_field, 1)
        row.addWidget(browse)
        layout.addLayout(row)

        layout.addSpacing(10)
        pitch = QLabel(
            'this system will attempt to chop the song into blocks of '
            'singing for you to type the lyrics into as you listen along.',
            page)
        pitch.setWordWrap(True)
        pitch.setStyleSheet(SYNC_MONO)
        layout.addWidget(pitch)

        layout.addSpacing(14)
        warning = QLabel(shouted(SYNC_WARNING), page)
        warning.setTextFormat(Qt.RichText)
        warning.setAlignment(Qt.AlignCenter)
        warning.setStyleSheet(SYNC_WARNING_STYLE)
        layout.addWidget(warning)

        layout.addSpacing(20)
        self.optional_head = QLabel(
            'OPTIONAL: (increases chances of success)', page)
        self.optional_head.setStyleSheet(
            SYNC_MONO + ' color: %s;' % TAG_ACCENT_COLOR)
        layout.addWidget(self.optional_head)

        paste = QLabel(
            'paste the lyrics, one line per phrase, word-for-word.  '
            'splitting words into syllables stays manual either way.', page)
        paste.setWordWrap(True)
        layout.addWidget(paste)

        self.lyrics = QPlainTextEdit(page)
        self.lyrics.setPlaceholderText(
            'leave empty to type them in as you go')
        layout.addWidget(self.lyrics, 1)

        self.note = QLabel('', page)
        self.note.setWordWrap(True)
        self.note.setStyleSheet('color: %s;' % SYNC_NOTE_COLOR)
        layout.addWidget(self.note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, page)
        self.start_button = buttons.button(QDialogButtonBox.Ok)
        self.start_button.setText('start')
        buttons.button(QDialogButtonBox.Cancel).setText('cancel')
        buttons.accepted.connect(self._on_start)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        return page

    def _build_busy(self):
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addStretch(1)

        self.busy_head = QLabel('', page)
        layout.addWidget(self.busy_head)

        self.bar = QProgressBar(page)
        self.bar.setRange(0, 100)
        layout.addWidget(self.bar)

        self.status = QLabel('starting...', page)
        self.status.setStyleSheet(
            'font-family: Consolas, "Courier New", monospace;')
        layout.addWidget(self.status)

        self.eta = QLabel('', page)
        self.eta.setStyleSheet('color: #7d7d88;')
        layout.addWidget(self.eta)
        layout.addStretch(1)

        self.busy_buttons = QDialogButtonBox(QDialogButtonBox.Cancel, page)
        self.busy_buttons.button(QDialogButtonBox.Cancel).setText('cancel')
        self.busy_buttons.rejected.connect(self._on_cancel)
        layout.addWidget(self.busy_buttons)
        return page

    def _build_drag(self):
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.hint = QLabel('', page)
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        split = QHBoxLayout()
        split.setSpacing(8)

        left = QVBoxLayout()
        left.setSpacing(4)
        self.line_list = QListWidget(page)
        self.line_list.setFixedWidth(280)
        self.line_list.currentRowChanged.connect(self._on_row_changed)
        left.addWidget(self.line_list, 3)

        self.words_head = QLabel('', page)
        self.words_head.setStyleSheet('color: #7d7d88; font-size: 11px;')
        left.addWidget(self.words_head)
        self.words_edit = QPlainTextEdit(page)
        self.words_edit.setFixedWidth(280)
        self.words_edit.setPlaceholderText(WORDS_HINT)
        self.words_edit.textChanged.connect(self._on_words_typed)
        left.addWidget(self.words_edit, 2)
        split.addLayout(left)

        right = QVBoxLayout()
        right.setSpacing(6)
        self.pane = WaveformPane(page)
        self.pane.view.zoomChanged.connect(self._on_zoom_changed)
        self.pane.view.clicked.connect(self._on_waveform_clicked)
        right.addWidget(self.pane, 1)
        right.addLayout(self._build_transport(page))
        split.addLayout(right, 1)
        layout.addLayout(split, 1)

        self.drag_buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, page)
        self.insert_button = self.drag_buttons.button(QDialogButtonBox.Ok)
        self.insert_button.setText('insert lyrics')
        self.drag_buttons.button(QDialogButtonBox.Cancel).setText('cancel')
        self.drag_buttons.accepted.connect(self._on_insert)
        self.drag_buttons.rejected.connect(self.reject)
        layout.addWidget(self.drag_buttons)
        return page

    def _build_transport(self, page):
        outer = QVBoxLayout()
        outer.setSpacing(6)

        edit = QHBoxLayout()
        edit.setSpacing(6)
        edit.addWidget(QLabel('block start', page))
        self.block_start = TimeSpin(page)
        self.block_start.valueChanged.connect(self._on_block_edited)
        edit.addWidget(self.block_start)
        edit.addSpacing(10)
        edit.addWidget(QLabel('block end', page))
        self.block_end = TimeSpin(page)
        self.block_end.valueChanged.connect(self._on_block_edited)
        edit.addWidget(self.block_end)
        edit.addSpacing(12)
        self.split_button = self._tool_button(
            'split', 'click where to cut a block in two   (s)', page)
        self.split_button.toggled.connect(self._on_tool_toggled)
        edit.addWidget(self.split_button)
        self.new_button = self._tool_button(
            'new', 'click where to drop a new one second block   (n)', page)
        self.new_button.toggled.connect(self._on_tool_toggled)
        edit.addWidget(self.new_button)

        edit.addSpacing(12)
        self.next_button = QPushButton('next block', page)
        self.next_button.clicked.connect(self._on_next_block)
        edit.addWidget(self.next_button)
        edit.addStretch(1)
        self.remaining = QLabel('', page)
        edit.addWidget(self.remaining)
        outer.addLayout(edit)

        row = QHBoxLayout()
        row.setSpacing(8)
        buttons = QVBoxLayout()
        buttons.setSpacing(4)
        self.play_button = QPushButton('play block', page)
        self.play_button.setFixedWidth(104)
        self.play_button.clicked.connect(self.play_block)
        buttons.addWidget(self.play_button)
        self.play_all_button = QPushButton('play all', page)
        self.play_all_button.setFixedWidth(104)
        self.play_all_button.clicked.connect(self.play_all)
        buttons.addWidget(self.play_all_button)
        row.addLayout(buttons)

        levels = QGridLayout()
        levels.setHorizontalSpacing(8)
        levels.setVerticalSpacing(4)
        self.vocal_level, self.vocal_pct = self._level_row(
            levels, 0, 'vocals', VOCAL_LEVEL, page)
        self.original_level, self.original_pct = self._level_row(
            levels, 1, 'song', ORIGINAL_LEVEL, page)
        row.addLayout(levels)

        row.addSpacing(10)
        self.clock = QLabel('0:00', page)
        row.addWidget(self.clock)
        row.addStretch(1)
        row.addWidget(QLabel('zoom', page))
        self.zoom = QSlider(Qt.Horizontal, page)
        self.zoom.setFixedWidth(150)
        self.zoom.setRange(0, ZOOM_STEPS)
        self.zoom.setValue(zoom_to_slider(PX_PER_S_DEFAULT))
        self.zoom.valueChanged.connect(self._on_zoom)
        row.addWidget(self.zoom)
        outer.addLayout(row)
        return outer

    @staticmethod
    def _tool_button(kind, tip, page):
        button = QToolButton(page)
        icon = QIcon(tool_icon(kind, '#9d9da8'))
        icon.addPixmap(tool_icon(kind, '#fca101'), QIcon.Normal, QIcon.On)
        button.setIcon(icon)
        button.setIconSize(QSize(18, 18))
        button.setCheckable(True)
        button.setAutoRaise(True)
        button.setToolTip(tip)
        return button

    def _level_row(self, grid, line, name, value, page):
        grid.addWidget(QLabel(name, page), line, 0)
        slider = QSlider(Qt.Horizontal, page)
        slider.setFixedWidth(140)
        slider.setRange(0, 100)
        slider.setValue(value)
        slider.valueChanged.connect(self._on_levels)
        grid.addWidget(slider, line, 1)
        readout = QLabel('%d%%' % value, page)
        readout.setMinimumWidth(38)
        grid.addWidget(readout, line, 2)
        return slider, readout

    # -- setup page ------------------------------------------------------

    def _choose_audio(self):
        start = os.path.dirname(self._audio) if self._audio else ''
        path, _ = QFileDialog.getOpenFileName(
            self, 'choose the audio to sync against', start, AUDIO_FILTER)
        if path:
            self._audio = path
            self._refresh_audio_label()

    def _refresh_audio_label(self):
        self.audio_field.setText(self._audio)
        megabytes = sync_models.missing_bytes() / (1024.0 * 1024.0)
        if megabytes > 0.0:
            self.note.setText(
                'experimental. the first run downloads %d mb of models from '
                '%s - they are kept in %s and only fetched once.'
                % (int(round(megabytes)),
                   ' and '.join(sync_models.download_urls()),
                   sync_models.model_dir()))
        else:
            self.note.setText(
                'experimental. expect to nudge roughly a third of the lines '
                'by ear afterwards.')

    def _parse_lyrics(self):
        lines = []
        for raw in self.lyrics.toPlainText().splitlines():
            words = [w.replace('"', "'") for w in raw.split()]
            if words:
                lines.append(words)
        return lines

    def _on_start(self):
        if not self._audio or not os.path.exists(self._audio):
            self._choose_audio()
        if not self._audio or not os.path.exists(self._audio):
            return
        self._lines = self._parse_lyrics()
        self._mode = 'paste' if self._lines else 'blocks'

        self._emissions = self._temp('inj_emis_', '.npy')
        self._audio_files = [self._temp('inj_song_', '.wav'),
                             self._temp('inj_voc_', '.wav')]
        self.busy_head.setText(
            'first run: fetching the models, then reading the song. the '
            'models are a one-off, the rest happens once per song.'
            if sync_models.missing() else
            'reading the song and isolating the vocals. '
            'this happens once per song and takes a few minutes.')
        self._begin('prepare', {
            'kind': 'prepare',
            'audio': self._audio,
            'emissions': self._emissions,
            'wav_original': self._audio_files[0],
            'wav_vocal': self._audio_files[1],
        })

    @staticmethod
    def _temp(prefix, suffix):
        handle, path = tempfile.mkstemp(prefix=prefix, suffix=suffix)
        os.close(handle)
        return path

    # -- worker ----------------------------------------------------------

    def _begin(self, phase, spec):
        self._phase = phase
        self.bar.setValue(0)
        self._done_stages = []
        self._stage = None
        self._stage_text = ''
        self._eta_started = 0.0
        self._eta_budget = 0.0
        self._dot_clock.stop()
        self.status.setText('starting...')
        self.eta.setText('')
        button = self.busy_buttons.button(QDialogButtonBox.Cancel)
        button.setText('cancel')
        button.setEnabled(True)
        self.stack.setCurrentIndex(1)
        self.runner.start(spec)

    def _on_progress(self, fraction, label, stage):
        self.bar.setValue(int(round(fraction * 100)))
        if stage != self._stage:
            if self._stage is not None:
                self._done_stages.append(self._stage_line(self._stage_text,
                                                          self._stage, 3))
            self._stage, self._dots = stage, 1
            self._dot_clock.start()
        self._stage_text = label
        self._paint_stages()

    def _on_dot(self):
        self._dots = self._dots % 3 + 1
        self._paint_stages()

    def _paint_stages(self):
        lines = list(self._done_stages)
        if self._stage is not None:
            lines.append(self._stage_line(self._stage_text, self._stage,
                                          self._dots))
        self.status.setText('\n'.join(lines))
        self.eta.setText(self._eta_text())

    @staticmethod
    def _stage_line(label, stage, dots):
        body = '%s %s' % (label, ' '.join('.' * dots))
        if stage not in COUNTED_STAGES:
            return body
        counter = '(%d/%d)' % (COUNTED_STAGES.index(stage) + 1,
                               len(COUNTED_STAGES))
        return '%-44s%s' % (body, counter)

    # -- how much longer -------------------------------------------------

    def _on_info(self, payload):
        duration = float(payload.get('duration') or 0.0)
        if duration > 0.0:
            self._duration = duration
            self._eta_started = time.monotonic()
            self._eta_budget = (duration / SEPARATE_XREALTIME
                                + duration / LISTEN_XREALTIME
                                + STAGE_OVERHEAD_S)

    def _eta_text(self):
        if self._eta_budget <= 0.0 or not self._eta_started:
            return ''
        left = self._eta_budget - (time.monotonic() - self._eta_started)
        if left <= 0.0:
            return 'nearly there'
        return 'estimated %dm remaining' % int(math.ceil(left / 60.0))

    def _on_finished(self, result):
        phase, self._phase = self._phase, None
        self._dot_clock.stop()
        if phase == 'prepare':
            self._on_prepared(result)
        elif phase == 'prefill':
            self._on_prefilled(result)
        elif phase == 'blocks':
            self._on_blocks(result)
        elif phase == 'align':
            self._on_aligned(result)

    def _on_failed(self, message):
        phase, self._phase = self._phase, None
        if phase in ('prefill', 'blocks'):
            self._show_drag('couldnt work out the blocks - set them by hand')
            return
        if phase == 'align' and self.pane.view.duration() > 0.0:
            self._show_drag('the aligner failed: {}'.format(message))
            return
        self.status.setText('failed: {}'.format(message))
        self._settle()

    def _on_cancelled(self):
        self._phase = None
        self.status.setText('cancelled')
        self._settle()

    def _settle(self):
        self._dot_clock.stop()
        self.eta.setText('')
        button = self.busy_buttons.button(QDialogButtonBox.Cancel)
        button.setText('close')
        button.setEnabled(True)
        try:
            self.busy_buttons.rejected.disconnect(self._on_cancel)
        except TypeError:
            pass
        self.busy_buttons.rejected.connect(self.reject)

    def _on_cancel(self):
        self.runner.cancel()
        self.status.setText('cancelling...')
        self.busy_buttons.button(QDialogButtonBox.Cancel).setEnabled(False)

    # -- drag page -------------------------------------------------------

    def _on_prepared(self, result):
        self._prepared = result
        view = self.pane.view
        view.set_audio(result.get('duration', 0.0),
                       result.get('peaks_hz', 100),
                       base64.b64decode(result.get('vocal_peaks', '')))
        view.set_lines(len(self._lines))

        self.line_list.clear()
        if len(self._audio_files) == 2:
            self.player.set_sources(*self._audio_files)
            self._on_levels()
        if self._mode == 'blocks':
            self.busy_head.setText('finding the blocks of singing.')
            self._begin('blocks', {
                'kind': 'blocks',
                'emissions': self._emissions,
            })
            return
        self.busy_head.setText('taking a first guess at where the lines are.')
        self._begin('prefill', {
            'kind': 'prefill',
            'emissions': self._emissions,
            'lines': [{'words': words} for words in self._lines],
        })

    def _on_blocks(self, result):
        self._blocks = [(float(a), float(b))
                        for a, b in (result.get('blocks') or [])]
        self._block_text = [''] * len(self._blocks)
        view = self.pane.view
        view.set_lines(len(self._blocks))
        view.set_regions(self._blocks)
        self._show_drag('' if self._blocks
                        else 'found no singing in that track')

    def _on_prefilled(self, result):
        self._guess = [list(starts) for starts in result.get('starts') or []]
        while len(self._guess) < len(self._lines):
            self._guess.append([])
        self.pane.view.set_regions(self._windows_from(self._guess))
        self._show_drag('')

    def _windows_from(self, guess):
        spans = []
        for starts in guess:
            if not starts:
                spans.append(None)
                continue
            spans.append([max(0.0, starts[0] - GUESS_LEAD_S),
                          starts[-1] + GUESS_TAIL_S])
        for first, second in zip(spans, spans[1:]):
            if first is not None and second is not None \
                    and first[1] > second[0]:
                middle = (first[1] + second[0]) / 2.0
                first[1] = second[0] = middle
        return [None if s is None else (s[0], s[1]) for s in spans]

    def _show_drag(self, note):
        blocks = self._mode == 'blocks'
        self.hint.setText(
            ('each block is a stretch of singing. pick one, hit play block, '
             'and type what you hear. trim it with the start and end boxes, '
             'then next block. drag the waveform to pan, ctrl+wheel to zoom.'
             if blocks else
             'these windows are a first guess: you must review them for any '
             'cut-off or missing words to have any chance at success. trim '
             'them with the start and end boxes. drag the waveform to pan, '
             'ctrl+wheel to zoom.')
            + '\nyou can open and close this window freely during this '
            'session, but if you dont complete the lyrics before exiting the '
            'program you will not be able to resume where you left off')
        self.words_head.setVisible(blocks)
        self.words_edit.setVisible(blocks)

        self._editing = -1
        self.line_list.clear()
        for index in range(len(self._blocks) if blocks else len(self._lines)):
            self.line_list.addItem('')
        self.stack.setCurrentIndex(2)
        self.line_list.setCurrentRow(0)
        self._on_row_changed(self.line_list.currentRow())
        self._note = note
        self._refresh_rows()
        first = self.pane.view.region(0)
        if first is not None:
            self.pane.center_on(first[0])

    def _on_row_changed(self, row):
        if row < 0:
            return
        self.pane.view.set_current(row)
        span = self.pane.view.region(row)
        if span is not None and not self._following:
            self.pane.center_on(span[0])
        self._load_block_bounds(row)
        if self._mode != 'blocks':
            return
        self._editing = row
        self.words_head.setText(
            'words for block %d%s' % (row + 1, self._span_label(span)))
        self.words_edit.blockSignals(True)
        self.words_edit.setPlainText(
            self._block_text[row] if row < len(self._block_text) else '')
        self.words_edit.blockSignals(False)

    @staticmethod
    def _span_label(span):
        if span is None:
            return ''
        return '   %d:%02d - %d:%02d' % (
            int(span[0]) // 60, int(span[0]) % 60,
            int(span[1]) // 60, int(span[1]) % 60)

    def _on_words_typed(self):
        if self._mode != 'blocks' or not (0 <= self._editing
                                          < len(self._block_text)):
            return
        self._block_text[self._editing] = self.words_edit.toPlainText()
        self._note = ''
        self._refresh_rows()

    # -- block bounds ----------------------------------------------------

    def _load_block_bounds(self, row):
        span = self.pane.view.region(row)
        for box in (self.block_start, self.block_end):
            box.blockSignals(True)
            box.setEnabled(span is not None)
        if span is not None:
            lo, hi = self._bounds_for(row)
            self.block_start.setRange(lo, max(lo, span[1] - MIN_BLOCK_S))
            self.block_end.setRange(min(hi, span[0] + MIN_BLOCK_S), hi)
            self.block_start.setValue(span[0])
            self.block_end.setValue(span[1])
        for box in (self.block_start, self.block_end):
            box.blockSignals(False)

    def _bounds_for(self, row):
        regions = self.pane.view.regions()
        low, high = 0.0, self.pane.view.duration() or 0.0
        for index, span in enumerate(regions):
            if span is None or index == row:
                continue
            if index < row:
                low = max(low, span[1])
            else:
                high = min(high, span[0])
        return low, max(low + MIN_BLOCK_S, high)

    def _on_block_edited(self):
        row = self.line_list.currentRow()
        if row < 0 or self.pane.view.region(row) is None:
            return
        lo, hi = self._bounds_for(row)
        start = max(lo, min(self.block_start.value(), hi - MIN_BLOCK_S))
        end = min(hi, max(self.block_end.value(), start + MIN_BLOCK_S))
        self.pane.view.set_region(row, (start, end))
        self._touched.add(row)
        self._load_block_bounds(row)
        self.words_head.setText(
            'words for block %d%s' % (row + 1, self._span_label((start, end))))
        self._note = ''
        self._refresh_rows()

    def _on_tool_toggled(self, on):
        sender = self.sender()
        if on:
            for other in (self.split_button, self.new_button):
                if other is not sender and other.isChecked():
                    other.blockSignals(True)
                    other.setChecked(False)
                    other.blockSignals(False)
        self.pane.view.tool_cursor(self._armed() is not None)

    def _disarm(self):
        for button in (self.split_button, self.new_button):
            if button.isChecked():
                button.setChecked(False)

    def _armed(self):
        if self.split_button.isChecked():
            return 'split'
        if self.new_button.isChecked():
            return 'new'
        return None

    def _on_waveform_clicked(self, seconds):
        tool = self._armed()
        if tool == 'split':
            self._split_at(seconds)
        elif tool == 'new':
            self._new_at(seconds)

    def _split_at(self, seconds):
        view = self.pane.view
        index = view.block_at(seconds)
        if index < 0:
            self._say('click inside a block to split it')
            return
        start, end = view.region(index)
        if seconds - start < MIN_BLOCK_S or end - seconds < MIN_BLOCK_S:
            self._say('too close to the edge to split')
            return
        self._insert_block(index + 1, (seconds, end))
        view.set_region(index, (start, seconds))
        self.line_list.setCurrentRow(index)
        self._say('')
        self._disarm()

    def _new_at(self, seconds):
        view = self.pane.view
        span = (seconds, seconds + NEW_BLOCK_S)
        if span[1] > (view.duration() or 0.0):
            self._say('not enough song left for a new block')
            return
        for other in view.regions():
            if other is not None and other[0] < span[1] and span[0] < other[1]:
                self._say('that would overlap block %d'
                          % (view.regions().index(other) + 1))
                return
        at = len([r for r in view.regions()
                  if r is not None and r[0] < span[0]])
        self._insert_block(at, span)
        self.line_list.setCurrentRow(at)
        self._say('')
        self._disarm()

    def _insert_block(self, at, span):
        view = self.pane.view
        spans = view.regions()
        spans.insert(at, span)
        self._block_text.insert(at, '')
        self._blocks = [s for s in spans if s is not None]
        view.set_lines(len(spans))
        view.set_regions(spans)
        self.line_list.insertItem(at, '')
        self._editing = -1
        self._refresh_rows()

    def _say(self, note):
        self._note = note
        self._refresh_rows()

    def _on_next_block(self):
        row = self.line_list.currentRow()
        if row + 1 < self.line_list.count():
            self.line_list.setCurrentRow(row + 1)
            self.words_edit.setFocus()
            self.play_block()

    # -- playback --------------------------------------------------------

    def play_block(self):
        span = self.pane.view.region(self.line_list.currentRow())
        if span is None:
            return
        self._set_playing_all(False)
        self.pane.view.set_live(self.line_list.currentRow())
        self.player.play(span[0], span[1])

    def play_all(self):
        if self._playing_all:
            self.player.stop()
            self._on_playback_stopped()
            return
        self._set_playing_all(True)
        self.pane.view.set_live(-1)
        self.player.play(0.0)

    def _set_playing_all(self, on):
        self._playing_all = on
        self.play_all_button.setText('stop' if on else 'play all')

    def _on_playback_stopped(self):
        self._set_playing_all(False)
        self.pane.view.set_live(-1)

    def _on_position(self, seconds):
        view = self.pane.view
        view.set_position(seconds)
        self.clock.setText('%d:%02d' % (int(seconds) // 60, int(seconds) % 60))

        live = view.block_at(seconds)
        view.set_live(live)
        if self._playing_all and live >= 0 \
                and live != self.line_list.currentRow():
            self._following = True
            try:
                self.line_list.setCurrentRow(live)
            finally:
                self._following = False
        self.pane.keep_visible(seconds)

    def _on_levels(self):
        self.vocal_pct.setText('%d%%' % self.vocal_level.value())
        self.original_pct.setText('%d%%' % self.original_level.value())
        self.player.set_levels(self.original_level.value() / 100.0,
                               self.vocal_level.value() / 100.0)

    # -- rows ------------------------------------------------------------

    def _refresh_rows(self):
        if self._mode == 'blocks':
            self._refresh_block_rows()
            return
        regions = self.pane.view.regions()
        pending = 0
        for index, words in enumerate(self._lines):
            item = self.line_list.item(index)
            if item is None:
                continue
            span = regions[index] if index < len(regions) else None
            if index in self._inserted:
                mark = '\u2713'
            elif span is not None:
                mark = '\u25cf'
                pending += 1
            else:
                mark = '\u25cb'
            item.setText('%s %2d  %s' % (mark, index + 1, ' '.join(words)))
        left = sum(1 for span in regions if span is None)
        if self._note:
            text = self._note
        elif left:
            text = ('1 line still needs a window' if left == 1
                    else '%d lines still need a window' % left)
        elif not pending:
            text = 'every line is in the chart already'
        else:
            text = 'ready'
        self.remaining.setText(text)
        self.insert_button.setEnabled(left == 0 and pending > 0)

    def _refresh_block_rows(self):
        regions = self.pane.view.regions()
        filled = orphaned = pending = 0
        for index, text in enumerate(self._block_text):
            item = self.line_list.item(index)
            if item is None:
                continue
            words = [w for w in text.split() if w]
            span = regions[index] if index < len(regions) else None
            written = index in self._inserted
            if words:
                filled += 1
                if span is None:
                    orphaned += 1
                elif not written:
                    pending += 1
            mark = '\u2713' if written else ('\u25cf' if words else '\u25cb')
            item.setText('%s %2d %s  %s' % (
                mark, index + 1, self._span_label(span).strip(),
                ' '.join(words[:4]) + ('...' if len(words) > 4 else '')))
        lines = sum(len(self._typed_lines(t)) for t in self._block_text)
        if self._note:
            text = self._note
        elif orphaned:
            text = ('%d block%s has words but no window'
                    % (orphaned, '' if orphaned == 1 else 's have'))
        elif filled and not pending:
            text = 'every block you typed is in the chart already'
        elif filled:
            text = '%d of %d blocks filled, %d line%s' % (
                filled, len(self._block_text), lines,
                '' if lines == 1 else 's')
        else:
            text = 'nothing typed yet'
        self.remaining.setText(text)
        self.insert_button.setEnabled(pending > 0 and orphaned == 0)

    @staticmethod
    def _typed_lines(text):
        out = []
        for raw in text.splitlines():
            words = [w.replace('"', "'") for w in raw.split()]
            if words:
                out.append(words)
        return out

    def _on_zoom(self, value):
        self.pane.view.set_px_per_second(slider_to_zoom(value))

    def _on_zoom_changed(self, px_per_s):
        self.zoom.blockSignals(True)
        self.zoom.setValue(zoom_to_slider(px_per_s))
        self.zoom.blockSignals(False)

    # -- alignment -------------------------------------------------------

    def _on_insert(self):
        self.player.stop()
        spec = (self._block_spec() if self._mode == 'blocks'
                else self._line_spec())
        if spec is None:
            return
        self.busy_head.setText('placing the words.')
        self._begin('align', spec)

    def _line_spec(self):
        regions = self.pane.view.regions()
        if any(span is None for span in regions):
            return None
        return {
            'kind': 'align',
            'emissions': self._emissions,
            'lines': [{'words': words, 'start': span[0], 'end': span[1],
                       'align': index not in self._inserted
                                and (index in self._touched
                                     or not self._guessed(index))}
                      for index, (words, span)
                      in enumerate(zip(self._lines, regions))],
        }

    def _block_spec(self):
        regions = self.pane.view.regions()
        self._block_lines = []
        lines = []
        for index, span in enumerate(regions):
            typed = self._typed_lines(self._block_text[index]) \
                if index < len(self._block_text) else []
            self._block_lines.append(typed)
            if span is None:
                if typed:
                    return None
                continue
            lines.append({'words': [w for line in typed for w in line],
                          'start': span[0], 'end': span[1],
                          'align': index not in self._inserted,
                          'block': index})
        if not any(entry['words'] and entry['align'] for entry in lines):
            return None
        self._align_order = [entry.pop('block') for entry in lines]
        return {'kind': 'align', 'emissions': self._emissions, 'lines': lines}

    def _guessed(self, index):
        return index < len(self._guess) and bool(self._guess[index])

    def _on_aligned(self, result):
        if self._mode == 'blocks':
            self._on_blocks_aligned(result)
            return
        starts = list(result.get('starts') or [])
        while len(starts) < len(self._lines):
            starts.append(None)
        regions = self.pane.view.regions()
        placements = []
        written = set()
        for index, words in enumerate(self._lines):
            if index in self._inserted:
                continue
            got = starts[index]
            if got is None:
                got = self._guess[index] if self._guessed(index) else []
            placed = [(word, int(round(
                self.timing.tick_at_audio_seconds(seconds))))
                for word, seconds in zip(words, got)]
            if placed:
                placements.append((placed, self._end_tick(regions, index)))
                written.add(index)
        if not placements:
            self._show_drag('nothing came back from the aligner')
            return
        self._placements = placements
        self._inserted |= written
        self.accept()

    def _on_blocks_aligned(self, result):
        starts = list(result.get('starts') or [])
        regions = self.pane.view.regions()
        placements = []
        written = set()
        for position, block in enumerate(self._align_order):
            got = starts[position] if position < len(starts) else None
            if not got:
                continue
            at = 0
            typed = self._block_lines[block]
            for order, words in enumerate(typed):
                placed = [(word, int(round(
                    self.timing.tick_at_audio_seconds(seconds))))
                    for word, seconds in zip(words, got[at:at + len(words)])]
                at += len(words)
                if not placed:
                    continue
                last = order == len(typed) - 1
                placements.append(
                    (placed, self._end_tick(regions, block) if last else None))
                written.add(block)
        if not placements:
            self._show_drag('nothing came back from the aligner')
            return
        self._placements = placements
        self._inserted |= written
        self.accept()

    def _end_tick(self, regions, index):
        span = regions[index] if 0 <= index < len(regions) else None
        if span is None:
            return None
        return int(round(self.timing.tick_at_audio_seconds(span[1])))

    def keyPressEvent(self, event):
        if self.stack.currentIndex() == 2 and not self._typing():
            key = event.key()
            if key == Qt.Key_Space:
                self.play_block()
                return
            if key == Qt.Key_S:
                self.split_button.toggle()
                return
            if key == Qt.Key_N:
                self.new_button.toggle()
                return
        super(AutoSyncDialog, self).keyPressEvent(event)

    @staticmethod
    def _typing():
        return isinstance(QApplication.focusWidget(),
                          (QPlainTextEdit, QLineEdit, QAbstractSpinBox))

    def placements(self):
        return self._placements

    def audio_path(self):
        return self._audio

    # -- teardown --------------------------------------------------------

    def done(self, code):
        if self.runner.running():
            self.runner.cancel()
        self.player.release()
        self._store_session()
        super(AutoSyncDialog, self).done(code)

    def _store_session(self):
        session = self._session
        if session is None or self._prepared is None:
            self._drop_temp()
            return
        session.audio = self._audio
        session.emissions = self._emissions
        session.wavs = list(self._audio_files)
        session.prepared = self._prepared
        session.mode = self._mode
        session.lyrics = self.lyrics.toPlainText()
        session.lines = [list(words) for words in self._lines]
        session.guess = [list(starts) for starts in self._guess]
        session.touched = set(self._touched)
        session.blocks = list(self._blocks)
        session.block_text = list(self._block_text)
        session.regions = self.pane.view.regions()
        session.inserted = set(self._inserted)

    def _drop_temp(self):
        for path in [self._emissions] + list(self._audio_files):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        self._emissions = None
        self._audio_files = []


class HotkeysDialog(QDialog):
    def __init__(self, rows, parent=None):
        super(HotkeysDialog, self).__init__(parent)
        self.setWindowTitle('hotkeys')
        self.setMinimumWidth(360)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(4)

        for group, items in rows:
            head = QLabel(group, self)
            font = head.font()
            font.setBold(True)
            head.setFont(font)
            layout.addSpacing(8)
            layout.addWidget(head)
            grid = QGridLayout()
            grid.setContentsMargins(6, 2, 0, 2)
            grid.setHorizontalSpacing(18)
            grid.setVerticalSpacing(2)
            for r, (name, key) in enumerate(items):
                grid.addWidget(QLabel(name, self), r, 0)
                keylabel = QLabel(key, self)
                keylabel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                grid.addWidget(keylabel, r, 1)
            grid.setColumnStretch(0, 1)
            layout.addLayout(grid)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.button(QDialogButtonBox.Close).setText('close')
        buttons.rejected.connect(self.reject)
        layout.addSpacing(10)
        layout.addWidget(buttons)


class CreditsDialog(QDialog):
    def __init__(self, parent=None):
        super(CreditsDialog, self).__init__(parent)
        self.setWindowTitle('credits')
        self.setMinimumWidth(400)
        self.setWindowFlags(self.windowFlags() | Qt.WindowContextHelpButtonHint)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 14)

        image = os.path.join(resource_dir(), 'rdyd.png').replace(os.sep, '/')
        body = QLabel(self)
        body.setTextFormat(Qt.RichText)
        body.setOpenExternalLinks(True)
        body.setAlignment(Qt.AlignHCenter)
        body.setWordWrap(True)
        body.setText(
            '<div align="center">'
            '<p style="font-size:19px;"><b>intro no jutsu</b><br>'
            '<span style="color:#9a9a9a;">clone hero lyric editor</span></p>'
            '<p>a &quot;fork&quot; of <a href="{fork}">'
            "MasterThe8's eLJe | LyricJutsu Editor</a><br>"
            '<span style="font-size:8pt; color:#77777f;">'
            '(a closed source project this was heavily influenced by)'
            '</span></p>'
            '<p><a href="{spec}">'
            "FireFox's Chart File Format Specifications</a></p>"
            '<p><a href="{pix}">pix_</a> - the g.o.a.t.<br>'
            '<a href="{intro}">intro</a> - my muse</p>'
            '<p>created by: <a href="{charter}">RDYD</a></p>'
            '<p><a href="{charter}">'
            '<img src="{img}" width="72" height="72"></a></p>'
            '</div>'.format(fork=FORK_URL, charter=CHARTER_URL,
                            spec=SPEC_URL, img=image,
                            pix=PIX_URL, intro=INTRO_URL))
        layout.addWidget(body)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        buttons.button(QDialogButtonBox.Close).setText('close')
        buttons.rejected.connect(self.reject)
        layout.addSpacing(8)
        layout.addWidget(buttons)

    def event(self, e):
        if e.type() == QEvent.EnterWhatsThisMode:
            QWhatsThis.leaveWhatsThisMode()
            sfx.play_file(os.path.join(resource_dir(), 'questionmark.opus'))
            return True
        return super(CreditsDialog, self).event(e)


# -- chart sections --------------------------------------------------------

def section_bounds(lines):
    bounds = {}
    index = 0
    while index < len(lines):
        head = SECTION_HEAD_RE.match(lines[index])
        if head is None:
            index += 1
            continue
        brace = index + 1
        while brace < len(lines) and not lines[brace].strip():
            brace += 1
        if brace >= len(lines) or lines[brace].strip() != '{':
            index += 1
            continue
        close = brace + 1
        while close < len(lines) and lines[close].strip() != '}':
            close += 1
        if close >= len(lines):
            break
        bounds.setdefault(head.group(1), (brace, close))
        index = close + 1
    return bounds


class GlobalText(object):
    song = ''
    sync_track = ''
    prefix = ''
    suffix = ''
    newline = '\n'
    encoding = 'utf-8'


def load_settings():
    cfg = configparser.ConfigParser()
    values = {
        'closing_lyric': DEFAULT_CLOSING_LYRIC,
        'hidden_lyric': DEFAULT_HIDDEN_LYRIC,
        'font_family': 'Consolas',
        'font_size': '18',
        'font_color': '#FFF',
        'background_color': EDITOR_BG,
        'path': '',
        'temp_path': '',
    }
    for spec in TAG_SPECS:
        values[spec['cfg']] = spec['key']
    try:
        with open(settings_path(), encoding='utf-8') as f:
            cfg.read_file(f)
        for section in cfg.sections():
            for key, value in cfg.items(section):
                if key in values and value != '':
                    values[key] = value
    except (OSError, configparser.Error):
        pass
    return cfg, values


def app_icon():
    for name in ('rdyd.ico', 'rdyd.png'):
        path = os.path.join(resource_dir(), name)
        if os.path.exists(path):
            return QIcon(path)
    return QIcon(':/img/icon.png')


class ChartTextEdit(QPlainTextEdit):
    def __init__(self, parent=None):
        super(ChartTextEdit, self).__init__(parent)
        self.window_ref = parent
        self.setContextMenuPolicy(Qt.DefaultContextMenu)

        self._marks = []
        self._mark_rows = {}
        self._active_row = -1
        self.cursorPositionChanged.connect(self._sync_active_mark)
        self.textChanged.connect(self.refresh_line_marks)

        self._auto_on = False
        self._auto_anchor = None
        self._auto_speed = 0.0
        self._auto_carry = 0.0
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(AUTOSCROLL_INTERVAL)
        self._auto_timer.timeout.connect(self._auto_step)

    # -- line classification -----------------------------------------------

    @staticmethod
    def phrase_tick(text):
        m = PHRASE_START_RE.match(text)
        return int(m.group(1)) if m else None

    @staticmethod
    def lyric_tick(text):
        m = LYRIC_RE.match(text)
        return int(m.group(1)) if m else None

    @staticmethod
    def line_kind(text):
        if PHRASE_START_RE.match(text):
            return 'phrase'
        if LYRIC_RE.match(text):
            return 'lyric'
        return None

    @staticmethod
    def _mark_selection(block, kind, active):
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(QColor(MARK_COLORS[kind][1 if active else 0]))
        sel.format.setProperty(QTextFormat.FullWidthSelection, True)
        cur = QTextCursor(block)
        cur.clearSelection()
        sel.cursor = cur
        return sel

    def refresh_line_marks(self):
        self._marks = []
        self._mark_rows = {}
        self._active_row = self.textCursor().blockNumber()
        block = self.document().firstBlock()
        while block.isValid():
            kind = self.line_kind(block.text())
            if kind is not None:
                row = block.blockNumber()
                self._mark_rows[row] = len(self._marks)
                self._marks.append(
                    self._mark_selection(block, kind, row == self._active_row))
            block = block.next()
        self.setExtraSelections(self._marks)

    def _sync_active_mark(self):
        row = self.textCursor().blockNumber()
        if row == self._active_row:
            return
        previous, self._active_row = self._active_row, row
        document = self.document()
        touched = False
        for target in (previous, row):
            slot = self._mark_rows.get(target)
            if slot is None:
                continue
            block = document.findBlockByNumber(target)
            kind = self.line_kind(block.text()) if block.isValid() else None
            if kind is None:
                continue
            self._marks[slot] = self._mark_selection(block, kind, target == row)
            touched = True
        if touched:
            self.setExtraSelections(self._marks)

    # -- middle-button autoscroll (held) -----------------------------------

    def _auto_stop(self):
        if not self._auto_on:
            return
        self._auto_on = False
        self._auto_speed = 0.0
        self._auto_carry = 0.0
        self._auto_timer.stop()
        self.viewport().setCursor(Qt.IBeamCursor)

    def _auto_step(self):
        if not self._auto_on or not self._auto_speed:
            return
        self._auto_carry += self._auto_speed
        step = int(self._auto_carry)
        if step:
            self._auto_carry -= step
            bar = self.verticalScrollBar()
            bar.setValue(bar.value() + step)

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._auto_on = True
            self._auto_anchor = event.pos()
            self._auto_speed = 0.0
            self._auto_carry = 0.0
            self.viewport().setCursor(Qt.SizeVerCursor)
            self._auto_timer.start()
            return
        super(ChartTextEdit, self).mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._auto_on:
            delta = event.pos().y() - self._auto_anchor.y()
            if abs(delta) <= AUTOSCROLL_DEADZONE:
                self._auto_speed = 0.0
            else:
                reach = delta - (AUTOSCROLL_DEADZONE if delta > 0
                                 else -AUTOSCROLL_DEADZONE)
                self._auto_speed = reach / AUTOSCROLL_DIVISOR
            return
        super(ChartTextEdit, self).mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._auto_on and event.button() == Qt.MiddleButton:
            self._auto_stop()
            return
        super(ChartTextEdit, self).mouseReleaseEvent(event)

    def focusOutEvent(self, event):
        self._auto_stop()
        super(ChartTextEdit, self).focusOutEvent(event)

    # -- opening the menu --------------------------------------------------

    def contextMenuEvent(self, event):
        self.setTextCursor(self.cursorForPosition(event.pos()))
        self.show_line_menu(event.globalPos())

    def show_line_menu(self, global_pos):
        text = self.textCursor().block().text()
        phrase = self.phrase_tick(text)
        lyric = self.lyric_tick(text)

        menu = QMenu(self)

        if phrase is not None:
            head = menu.addAction('phrase start @ tick {}'.format(phrase))
            head.setEnabled(False)
            menu.addSeparator()
            menu.addAction('no slideup transition',
                           lambda: self.window_ref.apply_jutsu(JUTSU_NO_SLIDEUP, phrase))
            menu.addAction('hide next phrase',
                           lambda: self.window_ref.apply_jutsu(JUTSU_HIDE_NEXT, phrase))
            menu.addAction('fake next phrase...',
                           lambda: self.window_ref.apply_jutsu(JUTSU_FAKE_NEXT, phrase))
            menu.addAction('lyric color no jutsu (method 1)...',
                           lambda: self.window_ref.apply_jutsu(JUTSU_LYRIC_COLOR, phrase))
            menu.addSeparator()
            menu.addAction('preview output from here',
                           lambda: self.window_ref.preview_from_tick(phrase))
        elif lyric is not None:
            head = menu.addAction('lyric @ tick {}'.format(lyric))
            head.setEnabled(False)
            menu.addSeparator()
            menu.addAction('preview output from here',
                           lambda: self.window_ref.preview_from_tick(lyric))
            menu.addSeparator()
            tags = menu.addAction('text tags')
            tags.setEnabled(False)
            menu.addAction(self.window_ref.tag_toolbar_action(menu))
        else:
            head = menu.addAction('click a phrase start or lyric line')
            head.setEnabled(False)

        menu.exec_(global_pos)


class MainWindow(QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()
        self.config, self.settings = load_settings()
        self.current_file = None

        self.setWindowIcon(app_icon())
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.resize(900, 700)

        self.plainTextEdit = ChartTextEdit(self)
        self.plainTextEdit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.plainTextEdit.setFont(QFont(self.settings['font_family'],
                                         int(self.settings['font_size'])))
        self.plainTextEdit.setStyleSheet(
            'QPlainTextEdit { background-color: %s; color: %s; }'
            % (self.settings['background_color'], self.settings['font_color']))
        self.highlighter = Highlighter(self.plainTextEdit.document())
        base_color = self.palette().color(QPalette.WindowText)
        self._tag_icons = [make_tag_icon(spec, base_color) for spec in TAG_SPECS]
        self._preview = None
        self._preview_audio = None
        self._phrase_end_warned = False
        self._grouping_layers = 3
        self._sync_session = SyncSession()

        self._build_actions()
        nav = self._build_nav()
        split = QSplitter(Qt.Horizontal, self)
        split.addWidget(nav)
        split.addWidget(self.plainTextEdit)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([230, 730])

        shell = QWidget(self)
        column = QVBoxLayout(shell)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(TitleBar(self, shell))
        column.addWidget(split, 1)

        footer = QWidget(shell)
        footer.setFixedHeight(16)
        foot_layout = QHBoxLayout(footer)
        foot_layout.setContentsMargins(0, 0, 2, 2)
        foot_layout.addStretch(1)
        foot_layout.addWidget(QSizeGrip(footer), 0, Qt.AlignBottom | Qt.AlignRight)
        column.addWidget(footer)
        self.setCentralWidget(shell)

        self._build_tag_shortcuts()
        self._update_glow_state()
        self._section_timer = QTimer(self)
        self._section_timer.setSingleShot(True)
        self._section_timer.setInterval(400)
        self._section_timer.timeout.connect(self.refresh_sections)
        self.plainTextEdit.textChanged.connect(self._section_timer.start)
        self._update_title()

    # -- menu --------------------------------------------------------------

    def _build_actions(self):
        self.action_open = QAction('open chart...', self)
        self.action_open.setShortcut('Ctrl+O')
        self.action_open.triggered.connect(self.open_file)

        self.action_save = QAction('save as...', self)
        self.action_save.setShortcut('Ctrl+S')
        self.action_save.triggered.connect(self.save_file)

        self.action_preview = QAction('output preview...', self)
        self.action_preview.setShortcut('F5')
        self.action_preview.triggered.connect(self.open_preview)

        self.action_undo = QAction('undo', self)
        self.action_undo.setShortcut('Ctrl+Z')
        self.action_undo.triggered.connect(self.plainTextEdit.undo)

        self.action_redo = QAction('redo', self)
        self.action_redo.setShortcut('Ctrl+Y')
        self.action_redo.triggered.connect(self.plainTextEdit.redo)

        self.action_scrub = QAction('scrub phrase_end lines', self)
        self.action_scrub.triggered.connect(self.scrub_phrase_ends)

        self.action_grouping = QAction('insert global event grouping...', self)
        self.action_grouping.setShortcut('Ctrl+G')
        self.action_grouping.triggered.connect(self._apply_global_grouping)

        self.action_autosync = QAction('auto-sync lyrics...', self)
        self.action_autosync.triggered.connect(self.open_autosync)

        self.action_hotkeys = QAction('hotkeys', self)
        self.action_hotkeys.triggered.connect(self.show_hotkeys)

        self.action_credits = QAction('credits', self)
        self.action_credits.triggered.connect(self.show_credits)

        self.action_exit = QAction('exit', self)
        self.action_exit.triggered.connect(self.close)

        for act in (self.action_open, self.action_save, self.action_preview,
                    self.action_undo, self.action_redo, self.action_scrub,
                    self.action_grouping,
                    self.action_autosync, self.action_hotkeys,
                    self.action_credits, self.action_exit):
            self.addAction(act)

    def _build_nav(self):
        self._glow_buttons = {}
        dark = system_prefers_dark()
        hover = 'rgba(255,255,255,0.10)' if dark else 'rgba(0,0,0,0.08)'
        press = 'rgba(255,255,255,0.18)' if dark else 'rgba(0,0,0,0.15)'
        pane = QWidget(self)
        outer = QVBoxLayout(pane)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        top = QWidget(pane)
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(10, 10, 10, 10)
        top_layout.setSpacing(3)

        groups = [
            ('file', [self.action_open, self.action_preview, self.action_save]),
            ('edit', [self.action_undo, self.action_redo,
                      self.action_scrub]),
            ('sync', [self.action_autosync]),
            ('help', [self.action_hotkeys, self.action_credits]),
            (None, [self.action_exit]),
        ]
        for title, actions in groups:
            if title:
                top_layout.addSpacing(8)
                head = QLabel(title, top)
                head.setStyleSheet('color: #7d7d88; font-size: 11px;')
                top_layout.addWidget(head)
            for act in actions:
                button = QPushButton(act.text(), top)
                button.setFlat(True)
                button.setCursor(Qt.PointingHandCursor)
                button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                button.setStyleSheet(
                    'QPushButton { text-align: left; padding: 6px 10px;'
                    ' border: none; background: transparent; }'
                    'QPushButton:hover { background: %s; }'
                    'QPushButton:pressed { background: %s; }' % (hover, press))
                key = act.shortcut().toString()
                if key:
                    button.setToolTip(key)
                for key, target in (('open', self.action_open),
                                    ('preview', self.action_preview),
                                    ('save', self.action_save)):
                    if act is target:
                        self._glow_buttons[key] = button
                if act in (self.action_undo, self.action_redo):
                    button.clicked.connect(
                        lambda _checked=False, a=act: (sfx.blip(), a.trigger()))
                else:
                    button.clicked.connect(act.trigger)
                top_layout.addWidget(button)
        top_layout.addStretch(1)

        bottom = QWidget(pane)
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(10, 8, 10, 10)
        bottom_layout.setSpacing(4)
        head = QLabel('sections', bottom)
        head.setStyleSheet('color: #7d7d88; font-size: 11px;')
        bottom_layout.addWidget(head)
        self.section_list = QListWidget(bottom)
        self.section_list.setAlternatingRowColors(False)
        self.section_list.setStyleSheet(
            'QListWidget { border: none; background: transparent;'
            ' outline: none; }'
            'QListWidget::item { padding: 6px 6px; border: none; }'
            'QListWidget::item:hover { padding: 6px 6px; background: %s; }'
            'QListWidget::item:selected { padding: 6px 6px; background: %s;'
            ' color: palette(window-text); }' % (hover, press))
        self.section_list.itemActivated.connect(self._jump_to_section)
        self.section_list.itemClicked.connect(self._jump_to_section)
        bottom_layout.addWidget(self.section_list, 1)

        self._setup_glows()
        inner = QSplitter(Qt.Vertical, pane)
        inner.addWidget(top)
        inner.addWidget(bottom)
        inner.setSizes([300, 300])
        outer.addWidget(inner)
        pane.setMinimumWidth(170)
        return pane

    def _setup_glows(self):
        self._glow_effects = {}
        for key, button in self._glow_buttons.items():
            effect = QGraphicsDropShadowEffect(button)
            effect.setOffset(0, 0)
            effect.setBlurRadius(0.0)
            effect.setColor(QColor(0, 0, 0, 0))
            effect.setEnabled(False)
            button.setGraphicsEffect(effect)
            self._glow_effects[key] = effect

        self._glow_active = None
        self._glow_phase = 0.0
        self._glow_timer = QTimer(self)
        self._glow_timer.setInterval(33)
        self._glow_timer.timeout.connect(self._pulse_glow)

    def _set_glow(self, key):
        if not getattr(self, '_glow_effects', None):
            return
        self._glow_active = key
        for name, effect in self._glow_effects.items():
            lit = (name == key)
            effect.setEnabled(lit)
            if not lit:
                effect.setBlurRadius(0.0)
                effect.setColor(QColor(0, 0, 0, 0))
        if key:
            self._glow_phase = 0.0
            self._glow_timer.start()
            self._pulse_glow()
        else:
            self._glow_timer.stop()

    def _update_glow_state(self):
        if not self.current_file:
            self._set_glow('open')
        elif not self._preview_audio:
            self._set_glow('preview')
        else:
            self._set_glow(None)

    def _pulse_glow(self):
        self._glow_phase += 0.033
        cycle = (self._glow_phase * 0.85) % 1.0
        if cycle < ATTACK_FRACTION:
            wave = cycle / ATTACK_FRACTION
        else:
            wave = math.exp(-3.4 * (cycle - ATTACK_FRACTION)
                            / (1.0 - ATTACK_FRACTION))
        effect = self._glow_effects.get(self._glow_active)
        if effect is None:
            return
        color = QColor(TAG_ACCENT_COLOR)
        color.setAlpha(int(40 + 215 * wave))
        effect.setColor(color)
        effect.setBlurRadius(4.0 + 34.0 * wave)

    # -- sections ----------------------------------------------------------

    def refresh_sections(self):
        current = self.section_list.currentRow() if self.section_list.count() else -1
        self.section_list.clear()
        for number, line in enumerate(self.getScript().splitlines()):
            m = SECTION_RE.match(line)
            if m:
                item = QListWidgetItem(m.group(2))
                item.setData(Qt.UserRole, number)
                item.setToolTip('tick {}'.format(m.group(1)))
                self.section_list.addItem(item)
        if 0 <= current < self.section_list.count():
            self.section_list.setCurrentRow(current)

    def _jump_to_section(self, item):
        block = item.data(Qt.UserRole)
        if block is None:
            return
        doc = self.plainTextEdit.document()
        if block >= doc.blockCount():
            return
        sfx.blip()
        cursor = QTextCursor(doc.findBlockByNumber(block))
        self.plainTextEdit.setTextCursor(cursor)
        bar = self.plainTextEdit.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.plainTextEdit.setTextCursor(cursor)
        self.plainTextEdit.ensureCursorVisible()
        self.plainTextEdit.setFocus()

    # -- help --------------------------------------------------------------

    def show_hotkeys(self):
        rows = [
            ('file', [('open chart', 'Ctrl+O'),
                      ('save as', 'Ctrl+S'),
                      ('output preview', 'F5')]),
            ('edit', [('undo', 'Ctrl+Z'), ('redo', 'Ctrl+Y'),
                      ('insert global event grouping...', 'Ctrl+G')]),
            ('text tags', [(spec['tip'],
                            self.settings.get(spec['cfg']) or spec['key'])
                           for spec in TAG_SPECS]),
            ('output preview', [('play / pause', 'Space'),
                                ('rewind 2s', 'Left'),
                                ('advance 2s', 'Right')]),
        ]
        HotkeysDialog(rows, self).exec_()

    def show_credits(self):
        CreditsDialog(self).exec_()

    def _build_tag_shortcuts(self):
        self._tag_shortcuts = []
        for spec in TAG_SPECS:
            binding = self.settings.get(spec['cfg']) or spec['key']
            sc = QShortcut(QKeySequence(binding), self)
            sc.setContext(Qt.WindowShortcut)
            sc.activated.connect(lambda s=spec: self._apply_tag(s))
            self._tag_shortcuts.append(sc)

    def _update_title(self):
        name = os.path.basename(self.current_file) if self.current_file else 'no file'
        self.setWindowTitle('{} {} - {}'.format(APP_NAME, APP_VERSION, name.lower()))

    # -- text tags ---------------------------------------------------------

    def tag_toolbar_action(self, menu):
        holder = QWidget(menu)
        grid = QGridLayout(holder)
        grid.setContentsMargins(10, 2, 10, 8)
        grid.setSpacing(3)

        for index, spec in enumerate(TAG_SPECS):
            button = QToolButton(holder)
            button.setIcon(self._tag_icons[index])
            button.setIconSize(QSize(22, 22))
            button.setFixedSize(30, 30)
            button.setAutoRaise(True)
            button.setToolTip(spec['tip'])
            button.clicked.connect(
                lambda _checked=False, s=spec, m=menu: self._apply_tag(s, m))
            grid.addWidget(button, index // 5, index % 5)

        action = QWidgetAction(menu)
        action.setDefaultWidget(holder)
        return action

    def _apply_tag(self, spec, menu=None):
        if menu is not None:
            menu.close()

        cursor = self.plainTextEdit.textCursor()
        block = cursor.block()
        m = LYRIC_RE.match(block.text())
        if not m:
            QMessageBox.critical(self, 'error', 'text tags only apply to lyric lines.')
            return

        open_tag, close_tag = spec['open'], spec['close']
        if spec.get('pick_color'):
            chosen = ColorPicker.get_color(QColor('#fca101'), self, 'text color')
            if not chosen.isValid():
                return
            open_tag = '<color={}>'.format(chosen.name(QColor.HexRgb))

        tick, lyric_text = m.group(1), m.group(2)
        new_line = '{} = E "lyric {}{}{}"'.format(tick, open_tag, lyric_text, close_tag)

        edit_cursor = QTextCursor(block)
        edit_cursor.beginEditBlock()
        edit_cursor.movePosition(QTextCursor.StartOfBlock)
        edit_cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        edit_cursor.insertText(new_line)
        edit_cursor.endEditBlock()
        self.plainTextEdit.setFocus()

    # -- output preview ----------------------------------------------------

    def _ensure_audio(self):
        if self._preview_audio and os.path.exists(self._preview_audio):
            return self._preview_audio
        start = os.path.dirname(self.current_file) if self.current_file else self._dialog_dir()
        path, _ = QFileDialog.getOpenFileName(
            self, 'choose the audio to sync the preview to', start, AUDIO_FILTER)
        if not path:
            return None
        self._preview_audio = path
        self._update_glow_state()
        return path

    def _ensure_preview(self):
        audio = self._ensure_audio()
        if not audio:
            return None
        if self._preview is None:
            self._preview = PreviewWindow(self)
            self._preview.closed.connect(self._on_preview_closed)
            self._preview.set_audio(audio)
        elif self._preview.audio_path() != audio:
            self._preview.set_audio(audio)

        timing = ChartTiming(GlobalText.song, GlobalText.sync_track)
        phrases = parse_phrases(self.getScript())
        if not phrases:
            QMessageBox.critical(self, 'error',
                                 'no lyric phrases found - open a chart first.')
            return None
        self._preview.set_chart(phrases, timing)
        self._preview.show()
        self._preview.raise_()
        return self._preview

    def _on_preview_closed(self):
        self._preview = None

    def _reset_preview(self):
        self._preview_audio = None
        self._update_glow_state()
        preview, self._preview = self._preview, None
        if preview is not None:
            preview.stop()
            preview.close()

    def open_preview(self):
        preview = self._ensure_preview()
        if preview is not None:
            preview.start_at_tick(0)

    def preview_from_tick(self, tick):
        preview = self._ensure_preview()
        if preview is not None:
            preview.start_at_tick(tick)

    # -- file i/o ----------------------------------------------------------

    def _dialog_dir(self):
        return self.settings['temp_path'] or self.settings['path'] or app_dir()

    def open_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, 'open file', self._dialog_dir(), 'chart files (*.chart)')
        if not file_name:
            return
        try:
            self.read_chart(file_name)
            self.current_file = file_name
            self._reset_preview()
            self._update_title()
            self._update_glow_state()
        except Exception as e:
            QMessageBox.critical(self, 'error',
                                 'error occurred while opening or reading file:\n{}'.format(e))

    def read_chart(self, file_chart):
        with open(file_chart, 'rb') as f:
            file_contents = f.read()

        encoding = chardet.detect(file_contents)['encoding'] or 'utf-8'
        if encoding.lower().replace('_', '-') in ('ascii', 'us-ascii'):
            encoding = 'utf-8'
        try:
            fcd = file_contents.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            encoding = 'utf-8'
            fcd = file_contents.decode('utf-8', errors='replace')

        lines = fcd.split('\n')
        bounds = section_bounds(lines)
        events = bounds.get('Events')
        if events is None:
            raise ValueError('no [Events] section found in this .chart file.')

        def body(name):
            found = bounds.get(name)
            if found is None:
                return ''
            return '\n'.join(lines[found[0] + 1:found[1]])

        open_index, close_index = events
        GlobalText.newline = '\r\n' if '\r\n' in fcd else '\n'
        GlobalText.encoding = encoding
        GlobalText.prefix = '\n'.join(lines[:open_index + 1]) + '\n'
        GlobalText.suffix = '\n'.join(lines[close_index:])
        GlobalText.song = body('Song')
        GlobalText.sync_track = body('SyncTrack')

        display = ('\n' + body('Events')).replace('\n  ', '\n')
        self._phrase_end_warned = False
        self._sync_session.drop()
        self.plainTextEdit.setPlainText(display.strip())
        self.plainTextEdit.document().setModified(False)
        self.refresh_sections()

    def save_file(self):
        path = self.current_file or self._dialog_dir()
        file_name, _ = QFileDialog.getSaveFileName(
            self, 'save file', path, 'chart files (*.chart)')
        if not file_name:
            return
        try:
            pte = self.plainTextEdit.toPlainText()
            newline = GlobalText.newline or '\n'
            indented = '  ' + pte.replace('\n', newline + '  ')
            data = GlobalText.prefix + indented + newline + GlobalText.suffix
            encoding = GlobalText.encoding or 'utf-8'
            try:
                blob = data.encode(encoding)
            except (UnicodeEncodeError, LookupError):
                blob = data.encode('utf-8')
                QMessageBox.information(
                    self, 'save',
                    'saved as utf-8 - {} cannot hold every character that is '
                    'in the chart now.'.format(encoding))
            with open(file_name, 'wb') as f:
                f.write(blob)
            self.plainTextEdit.document().setModified(False)
            self.current_file = file_name
            self._update_title()
        except Exception as e:
            QMessageBox.critical(self, 'error',
                                 'error occurred while saving file:\n{}'.format(e))

    def getScript(self):
        return self.plainTextEdit.toPlainText()

    # -- jutsu application -------------------------------------------------

    def _replace_all_text(self, new_text):
        scroll_bar = self.plainTextEdit.verticalScrollBar()
        scroll_pos = scroll_bar.value()
        cursor = self.plainTextEdit.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.Document)
        cursor.insertText(new_text)
        cursor.endEditBlock()
        scroll_bar.setValue(scroll_pos)

    @staticmethod
    def _used_ticks(lines):
        ticks = set()
        for line in lines:
            m = TICK_RE.match(line)
            if m:
                ticks.add(int(m.group(1)))
        return ticks

    @staticmethod
    def _lyric_ticks(lines):
        ticks = set()
        for line in lines:
            m = LYRIC_RE.match(line)
            if m:
                ticks.add(int(m.group(1)))
        return ticks

    @staticmethod
    def _tick_counts(text):
        counts = {}
        for line in text.splitlines():
            m = TICK_RE.match(line)
            if m:
                tick = int(m.group(1))
                counts[tick] = counts.get(tick, 0) + 1
        return counts

    @staticmethod
    def _sorted_by_tick(lines):
        keyed = []
        carried = 0
        for index, line in enumerate(lines):
            m = TICK_RE.match(line)
            if m:
                carried = int(m.group(1))
            keyed.append((carried, index, line))
        keyed.sort()
        return [line for _tick, _index, line in keyed]

    def _warn_phrase_ends(self):
        if self._phrase_end_warned:
            return False
        self._phrase_end_warned = True
        return self._phrase_end_prompt(True)

    def scrub_phrase_ends(self):
        self._phrase_end_prompt(False)

    def _phrase_end_prompt(self, quiet):
        lines = self.getScript().split('\n')
        hits = [line for line in lines if PHRASE_END_RE.match(line)]
        if not hits:
            if not quiet:
                QMessageBox.information(
                    self, 'phrase_end', 'this chart has no phrase_end events.')
            return False

        confirm = QMessageBox(self)
        confirm.setIcon(QMessageBox.Warning)
        confirm.setWindowTitle('phrase_end')
        confirm.setText(
            'this chart has {} phrase_end event{}.\n'
            "they fuck up the jutsus and aren't technically needed.\n\n"
            'scrub them all out?'.format(
                len(hits), '' if len(hits) == 1 else 's'))
        confirm.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        confirm.button(QMessageBox.Yes).setText('scrub them')
        confirm.button(QMessageBox.No).setText('leave them')
        if confirm.exec_() != QMessageBox.Yes:
            return False
        self._replace_all_text('\n'.join(
            line for line in lines if not PHRASE_END_RE.match(line)))
        return True

    def apply_jutsu(self, kind, tick):
        if kind == JUTSU_LYRIC_COLOR:
            self._apply_lyric_color(tick)
        elif kind == JUTSU_FAKE_NEXT:
            self._apply_fake_next(tick)
        else:
            self._apply_insert_jutsu(kind, tick)

    def _apply(self, build, *args):
        text, error = build(*args)
        if error is None and self._warn_phrase_ends():
            text, error = build(*args)
        if error:
            QMessageBox.critical(self, 'error', error)
            return
        self._replace_all_text(text)

    def _apply_fake_next(self, tick):
        fake = FakePhraseDialog.ask(self)
        if fake is None:
            return
        fake = fake.strip()
        if not fake:
            QMessageBox.critical(self, 'error', 'the fake phrase cannot be empty.')
            return
        self._apply(self._fake_next_text, tick, fake)

    def _fake_next_text(self, tick, fake):
        closing = self.settings['closing_lyric'] or DEFAULT_CLOSING_LYRIC
        lines = self.getScript().splitlines()

        ps_index = next(
            (i for i, ln in enumerate(lines)
             if self.plainTextEdit.phrase_tick(ln) == tick), None)
        if ps_index is None:
            return None, 'could not find a phrase start at tick {}.'.format(tick)

        replacement = [
            '{} = E "lyric {}"'.format(tick, closing),
            '{} = E "phrase_start"'.format(tick + 1),
            '{} = E "lyric {}"'.format(tick + 2, fake),
            '{} = E "phrase_start"'.format(tick + 3),
            '{} = E "lyric {}"'.format(tick + 4, closing),
        ]

        survivors = [ln for i, ln in enumerate(lines) if i != ps_index]
        needed = {tick + i for i in range(5)}
        collisions = (needed - {tick}) & self._used_ticks(survivors)
        if tick in self._lyric_ticks(survivors):
            collisions.add(tick)
        collisions = sorted(collisions)
        if collisions:
            return None, (
                'this jutsu needs ticks {} to be free, but {} already exist in '
                'the chart.\n\napplying it would overwrite existing events.'
                .format(sorted(needed), collisions))

        out = []
        for i, line in enumerate(lines):
            if i == ps_index:
                out.extend(replacement)
            else:
                out.append(line)
        return '\n'.join(self._sorted_by_tick(out)), None

    def _apply_insert_jutsu(self, kind, tick):
        self._apply(self._insert_jutsu_text, kind, tick)

    def _insert_jutsu_text(self, kind, tick):
        closing = self.settings['closing_lyric'] or DEFAULT_CLOSING_LYRIC
        hidden = self.settings['hidden_lyric'] or DEFAULT_HIDDEN_LYRIC

        lines = self.getScript().splitlines()

        ps_index = next(
            (i for i, ln in enumerate(lines)
             if self.plainTextEdit.phrase_tick(ln) == tick), None)
        if ps_index is None:
            return None, 'could not find a phrase start at tick {}.'.format(tick)

        lyric_tick = None
        for i in range(ps_index + 1, len(lines)):
            if PHRASE_START_RE.match(lines[i]):
                break
            m = LYRIC_RE.match(lines[i])
            if m:
                lyric_tick = int(m.group(1))
                break
        if lyric_tick is None:
            return None, (
                'the phrase at tick {} has no lyric line after it, so there is '
                'nothing to anchor the jutsu to.'.format(tick))

        if kind == JUTSU_NO_SLIDEUP:
            inserts = [
                (lyric_tick - 2, '{} = E "lyric {}"'.format(lyric_tick - 2, closing)),
                (lyric_tick - 1, '{} = E "phrase_start"'.format(lyric_tick - 1)),
            ]
        else:
            inserts = [
                (lyric_tick - 4, '{} = E "lyric {}"'.format(lyric_tick - 4, closing)),
                (lyric_tick - 3, '{} = E "phrase_start"'.format(lyric_tick - 3)),
                (lyric_tick - 2, '{} = E "lyric {}"'.format(lyric_tick - 2, hidden)),
                (lyric_tick - 1, '{} = E "phrase_start"'.format(lyric_tick - 1)),
            ]

        needed = {t for t, _ in inserts}
        if min(needed) < 0:
            return None, (
                'the lyric at tick {} is too close to the start of the chart '
                'for this jutsu.'.format(lyric_tick))

        survivors = [ln for i, ln in enumerate(lines) if i != ps_index]
        collisions = sorted((needed & self._used_ticks(survivors)) - {tick})
        if collisions:
            return None, (
                'this jutsu needs ticks {} to be free, but {} already exist in '
                'the chart.\n\napplying it would overwrite existing events.'
                .format(sorted(needed), collisions))

        out = survivors + [line for _, line in inserts]
        return '\n'.join(self._sorted_by_tick(out)), None

    def _apply_global_grouping(self):
        m = TICK_RE.match(self.plainTextEdit.textCursor().block().text())
        chosen = GlobalGroupingDialog.ask(
            int(m.group(1)) if m else None, self._grouping_layers, self)
        if chosen is None:
            return
        tick, layers = chosen
        self._grouping_layers = layers
        if tick is None:
            QMessageBox.critical(self, 'error', 'enter a tick to insert at.')
            return
        self._apply(self._grouping_text, tick, layers)

    def _grouping_text(self, tick, layers):
        closing = self.settings['closing_lyric'] or DEFAULT_CLOSING_LYRIC
        hidden = self.settings['hidden_lyric'] or DEFAULT_HIDDEN_LYRIC

        bodies = ['lyric ' + hidden, 'phrase_start', 'lyric ' + closing]
        if layers == 5:
            bodies[2:2] = ['lyric ' + hidden, 'phrase_start']

        lines = self.getScript().splitlines()
        inserts = ['{} = E "{}"'.format(tick + offset, body)
                   for offset, body in enumerate(bodies)]
        needed = {tick + offset for offset in range(len(bodies))}
        collisions = sorted(needed & self._used_ticks(lines))
        if collisions:
            return None, (
                'this jutsu needs ticks {} to be free, but {} already exist in '
                'the chart.\n\napplying it would overwrite existing events.'
                .format(sorted(needed), collisions))

        return '\n'.join(self._sorted_by_tick(lines + inserts)), None

    def _apply_lyric_color(self, tick):
        color = ColorPicker.get_color(QColor('#fca101'), self, 'lyric color')
        if not color.isValid():
            return
        self._apply(self._lyric_color_text, tick, color)

    def _lyric_color_text(self, tick, color):
        script = self.getScript()
        try:
            result = LyricColorJutsu().build(
                script, tick, color.name(QColor.HexRgb))
        except ValueError as e:
            return None, str(e).lower()

        before = self._tick_counts(script)
        after = self._tick_counts(result)
        collisions = sorted(t for t, n in after.items()
                            if n > 1 and n > before.get(t, 0))
        if collisions:
            return None, (
                'this jutsu needs the four ticks before the first lyric to be '
                'free, but {} already exist in the chart.\n\napplying it would '
                'overwrite existing events.'.format(collisions))
        return result, None

    # -- auto-sync -----------------------------------------------------------

    def open_autosync(self):
        if not GlobalText.prefix:
            QMessageBox.critical(self, 'auto-sync', 'open a chart first.')
            return
        session = self._sync_session
        lines = self.getScript().split('\n')
        if not self._lyric_ticks(lines):
            session.inserted = set()
        elif not session.alive():
            QMessageBox.critical(
                self, 'auto-sync',
                'this chart already has lyric events.\n'
                'auto-sync only writes into an empty one.')
            return

        timing = ChartTiming(GlobalText.song, GlobalText.sync_track)
        dialog = AutoSyncDialog(timing, session.audio or self._preview_audio,
                                self, session)
        accepted = dialog.exec_() == QDialog.Accepted
        chosen = dialog.audio_path()
        if chosen and chosen != self._preview_audio:
            self._preview_audio = chosen
            self._update_glow_state()
        if not accepted:
            return
        self._insert_placements(dialog.placements(), timing.resolution)

    def _insert_placements(self, placements, resolution):
        lines = self.getScript().splitlines()
        used = self._used_ticks(lines)
        lead = max(MIN_PHRASE_LEAD,
                   int(round(PHRASE_LEAD_TICKS * resolution / 192.0)))

        inserts = []
        moved = 0
        cursor = -1
        opened = []
        for words, end_hint in placements:
            if not words:
                continue
            first = max(0, words[0][1] - lead)
            start = self._next_free(first, used, cursor)
            cursor = start
            used.add(start)
            inserts.append('{} = E "phrase_start"'.format(start))
            ticks = []
            for index, (word, tick) in enumerate(words):
                floor = start + MIN_PHRASE_LEAD - 1 if index == 0 else cursor
                placed = self._next_free(tick, used, floor)
                if placed != tick:
                    moved += 1
                cursor = placed
                used.add(placed)
                inserts.append('{} = E "lyric {}"'.format(placed, word))
                ticks.append(placed)
            opened.append((start, ticks, end_hint))

        closed = self._close_phrases(opened, used, lead, inserts)
        if not inserts:
            return
        self._replace_all_text('\n'.join(self._sorted_by_tick(lines + inserts)))
        note = '{} lines, {} events.'.format(len(opened), len(inserts))
        if moved:
            note += '\n{} nudged off an occupied tick.'.format(moved)
        if closed < len(opened):
            note += '\n{} had no room for a phrase_end.'.format(
                len(opened) - closed)
        QMessageBox.information(self, 'auto-sync', note)

    @staticmethod
    def _close_phrases(opened, used, lead, inserts):
        closed = 0
        for index, (_start, ticks, end_hint) in enumerate(opened):
            last = ticks[-1]
            following = opened[index + 1][0] if index + 1 < len(opened) else None
            if end_hint is not None:
                target = int(end_hint)
            elif following is not None:
                target = last + max(lead, (following - last) // 2)
            else:
                target = last + 2 * lead
            ceiling = None if following is None else following - 1
            if ceiling is not None:
                target = min(target, ceiling)
            target = max(target, last + 1)
            while target in used:
                target += 1
            if ceiling is not None and target > ceiling:
                continue
            used.add(target)
            inserts.append('{} = E "phrase_end"'.format(target))
            closed += 1
        return closed

    @staticmethod
    def _next_free(tick, used, floor):
        tick = max(int(tick), floor + 1, 0)
        while tick in used:
            tick += 1
        return tick

    # -- close -------------------------------------------------------------

    def closeEvent(self, event):
        if not self.plainTextEdit.document().isModified():
            self._sync_session.drop()
            event.accept()
            return

        confirm = QMessageBox(self)
        confirm.setIcon(QMessageBox.Question)
        confirm.setText('there are unsaved changes\n'
                        'are you sure you want to exit?')
        confirm.setWindowTitle('exit')
        confirm.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        confirm.button(QMessageBox.Yes).setText('yes')
        confirm.button(QMessageBox.No).setText('no')
        self._set_glow('save')
        try:
            answer = confirm.exec_()
        finally:
            self._update_glow_state()
        if answer == QMessageBox.Yes:
            self._sync_session.drop()
            event.accept()
        else:
            event.ignore()


def _install_excepthook():
    def hook(kind, value, trace):
        sys.__excepthook__(kind, value, trace)
        try:
            QMessageBox.critical(
                None, 'error',
                'something went wrong:\n{}: {}'.format(kind.__name__, value))
        except Exception:
            pass
    sys.excepthook = hook


def main():
    app = QApplication(sys.argv)
    _install_excepthook()
    app.setApplicationName(APP_NAME)
    apply_theme(app)
    app.setWindowIcon(app_icon())
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
