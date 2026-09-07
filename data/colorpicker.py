"""a tall color picker."""

import configparser

from PyQt5.QtCore import QPoint, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import (
    QColor, QIcon, QImage, QLinearGradient, QPainter, QPalette, QPen, QPixmap)
from PyQt5.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from .paths import settings_path
from .theme import border_color, system_prefers_dark

CUSTOM_COLS = 8
CUSTOM_ROWS = 2
CUSTOM_SLOTS = CUSTOM_COLS * CUSTOM_ROWS
SWATCH_GAP = 3


# ---------------------------------------------------------------- persistence

def load_custom_colors():
    cfg = configparser.ConfigParser()
    try:
        with open(settings_path(), encoding='utf-8') as f:
            cfg.read_file(f)
        raw = cfg.get('CustomColors', 'colors')
    except (OSError, configparser.Error):
        return []
    out = []
    for chunk in raw.split(','):
        chunk = chunk.strip()
        if chunk and QColor(chunk).isValid():
            out.append(QColor(chunk).name(QColor.HexRgb))
    return out[:CUSTOM_SLOTS]


def save_custom_colors(colors):
    cfg = configparser.ConfigParser()
    try:
        with open(settings_path(), encoding='utf-8') as f:
            cfg.read_file(f)
    except (OSError, configparser.Error):
        pass
    if not cfg.has_section('CustomColors'):
        cfg.add_section('CustomColors')
    cfg.set('CustomColors', 'colors', ','.join(colors))
    try:
        with open(settings_path(), 'w', encoding='utf-8') as f:
            cfg.write(f)
    except OSError:
        pass


# ---------------------------------------------------------------------- icons

def dropper_icon(color, size=18):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(color)
    pen.setWidthF(max(1.2, size * 0.10))
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)

    p.drawLine(QPoint(int(size * 0.22), int(size * 0.78)),
               QPoint(int(size * 0.62), int(size * 0.38)))
    p.drawEllipse(QRectF(size * 0.58, size * 0.10, size * 0.32, size * 0.32))
    p.drawLine(QPoint(int(size * 0.20), int(size * 0.80)),
               QPoint(int(size * 0.14), int(size * 0.88)))
    p.end()
    return QIcon(pm)


# --------------------------------------------------------------- square field

class HueSatSquare(QWidget):
    colorChanged = pyqtSignal(QColor)

    def __init__(self, parent=None):
        super(HueSatSquare, self).__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(200)
        self.setCursor(Qt.CrossCursor)
        self._hue = 0
        self._sat = 255
        self._value = 255
        self._base = None
        self._base_size = None

    def color(self):
        return QColor.fromHsv(self._hue, self._sat, self._value)

    def set_hsv(self, hue, sat, value):
        self._hue, self._sat, self._value = hue, sat, value
        self.update()

    def set_color(self, color):
        h, s, v, _ = color.getHsv()
        if h < 0:
            h = self._hue
        self.set_hsv(h, s, v)

    def set_value(self, value):
        self._value = value
        self.update()

    def _base_image(self):
        w, h = max(1, self.width()), max(1, self.height())
        if self._base_size == (w, h):
            return self._base
        img = QImage(w, h, QImage.Format_RGB32)
        for x in range(w):
            hue = int(x * 359 / max(1, w - 1))
            for y in range(h):
                sat = 255 - int(y * 255 / max(1, h - 1))
                img.setPixelColor(x, y, QColor.fromHsv(hue, sat, 255))
        self._base, self._base_size = img, (w, h)
        return img

    def paintEvent(self, _event):
        p = QPainter(self)
        p.drawImage(0, 0, self._base_image())
        if self._value < 255:
            p.fillRect(self.rect(),
                       QColor(0, 0, 0, 255 - self._value))

        w, h = self.width(), self.height()
        x = int(self._hue * (w - 1) / 359.0)
        y = int((255 - self._sat) * (h - 1) / 255.0)
        margin = 8
        x = min(max(x, margin), max(margin, w - margin - 1))
        y = min(max(y, margin), max(margin, h - margin - 1))
        ring = Qt.black if self.color().lightness() > 128 else Qt.white
        p.setPen(QPen(ring, 2))
        p.drawEllipse(QPoint(x, y), 6, 6)
        p.setPen(QPen(Qt.gray, 1))
        p.drawEllipse(QPoint(x, y), 7, 7)
        p.end()

    def _pick(self, pos):
        w, h = max(1, self.width() - 1), max(1, self.height() - 1)
        x = min(max(pos.x(), 0), w)
        y = min(max(pos.y(), 0), h)
        self._hue = int(x * 359 / w)
        self._sat = 255 - int(y * 255 / h)
        self.update()
        self.colorChanged.emit(self.color())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pick(event.pos())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._pick(event.pos())


# -------------------------------------------------------------- value slider

class ValueSlider(QWidget):
    valueChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super(ValueSlider, self).__init__(parent)
        self.setFixedWidth(26)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setCursor(Qt.SizeVerCursor)
        self._hue = 0
        self._sat = 255
        self._value = 255
        self._dark = system_prefers_dark()

    def set_hue_sat(self, hue, sat):
        self._hue, self._sat = hue, sat
        self.update()

    def set_value(self, value):
        self._value = value
        self.update()

    def value(self):
        return self._value

    def _bar_rect(self):
        return QRect(0, 6, self.width() - 8, max(1, self.height() - 12))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        bar = self._bar_rect()

        grad = QLinearGradient(bar.topLeft(), bar.bottomLeft())
        grad.setColorAt(0.0, QColor.fromHsv(self._hue, self._sat, 255))
        grad.setColorAt(1.0, QColor(0, 0, 0))
        p.fillRect(bar, grad)
        p.setPen(QPen(QColor(border_color(self._dark)), 1))
        p.drawRect(bar.adjusted(0, 0, -1, -1))

        y = bar.top() + int((255 - self._value) * (bar.height() - 1) / 255.0)
        p.setPen(QPen(self.palette().color(QPalette.WindowText), 1))
        p.setBrush(self.palette().color(QPalette.WindowText))
        p.drawPolygon(QPoint(self.width() - 7, y),
                      QPoint(self.width() - 1, y - 4),
                      QPoint(self.width() - 1, y + 4))
        p.end()

    def _pick(self, pos):
        bar = self._bar_rect()
        y = min(max(pos.y() - bar.top(), 0), bar.height() - 1)
        self._value = 255 - int(y * 255 / max(1, bar.height() - 1))
        self.update()
        self.valueChanged.emit(self._value)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pick(event.pos())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._pick(event.pos())


# --------------------------------------------------------------- swatch strip

class SwatchGrid(QWidget):
    picked = pyqtSignal(QColor)

    def __init__(self, dark, parent=None):
        super(SwatchGrid, self).__init__(parent)
        self._colors = []
        self._dark = dark
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

    def set_colors(self, colors):
        self._colors = list(colors)[:CUSTOM_SLOTS]
        self.update()

    def colors(self):
        return list(self._colors)

    def add(self, color):
        name = QColor(color).name(QColor.HexRgb)
        if name in self._colors:
            self._colors.remove(name)
        self._colors.insert(0, name)
        self._colors = self._colors[:CUSTOM_SLOTS]
        self.update()

    def _cell_size(self, width=None):
        width = self.width() if width is None else width
        return max(10, int((width - (CUSTOM_COLS - 1) * SWATCH_GAP) / CUSTOM_COLS))

    def _height_for(self, width):
        cell = self._cell_size(width)
        return CUSTOM_ROWS * cell + (CUSTOM_ROWS - 1) * SWATCH_GAP

    def sizeHint(self):
        return QSize(CUSTOM_COLS * 30, self._height_for(self.width() or CUSTOM_COLS * 30))

    def resizeEvent(self, event):
        self.setFixedHeight(self._height_for(event.size().width()))
        super(SwatchGrid, self).resizeEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        cell = self._cell_size()
        empty = QColor('#2a2a2a') if self._dark else QColor('#ffffff')
        for index in range(CUSTOM_SLOTS):
            row, col = divmod(index, CUSTOM_COLS)
            rect = QRect(col * (cell + SWATCH_GAP), row * (cell + SWATCH_GAP),
                         cell, cell)
            if index < len(self._colors):
                p.fillRect(rect, QColor(self._colors[index]))
            else:
                p.fillRect(rect, empty)
            p.setPen(QPen(QColor(border_color(self._dark)), 1))
            p.drawRect(rect.adjusted(0, 0, -1, -1))
        p.end()

    def mousePressEvent(self, event):
        cell = self._cell_size()
        col = event.pos().x() // (cell + SWATCH_GAP)
        row = event.pos().y() // (cell + SWATCH_GAP)
        index = row * CUSTOM_COLS + col
        if 0 <= col < CUSTOM_COLS and 0 <= index < len(self._colors):
            self.picked.emit(QColor(self._colors[index]))


# --------------------------------------------------------------------- dialog

class ColorPicker(QDialog):
    def __init__(self, initial=None, parent=None, title='select color'):
        super(ColorPicker, self).__init__(parent)
        self._dark = system_prefers_dark()
        self._color = QColor(initial) if initial and QColor(initial).isValid() \
            else QColor('#fca101')
        self._picking = False

        self.setWindowTitle(title)
        self.setFixedWidth(300)
        self.setMinimumHeight(560)

        text_color = self.palette().color(QPalette.WindowText)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)

        # -- dropper, top --------------------------------------------------
        top = QHBoxLayout()
        top.setSpacing(6)
        self.dropper = QToolButton(self)
        self.dropper.setIcon(dropper_icon(text_color))
        self.dropper.setIconSize(QSize(18, 18))
        self.dropper.setFixedSize(30, 28)
        self.dropper.setToolTip('pick a color from the screen')
        self.dropper.clicked.connect(self._start_screen_pick)
        top.addWidget(self.dropper)
        self.hint = QLabel('pick from screen', self)
        self.hint.setStyleSheet('font-size: 11px;')
        top.addWidget(self.hint)
        top.addStretch(1)
        root.addLayout(top)

        # -- square + value slider -----------------------------------------
        field = QHBoxLayout()
        field.setSpacing(8)
        self.square = HueSatSquare(self)
        self.square.setMinimumHeight(230)
        self.square.colorChanged.connect(self._on_square)
        field.addWidget(self.square, 1)

        self.value_slider = ValueSlider(self)
        self.value_slider.valueChanged.connect(self._on_value)
        field.addWidget(self.value_slider)
        root.addLayout(field, 1)

        # -- current color -------------------------------------------------
        current = QHBoxLayout()
        current.setSpacing(8)
        self.preview = QLabel(self)
        self.preview.setFixedSize(52, 26)
        current.addWidget(self.preview)
        self.readout = QLabel(self)
        current.addWidget(self.readout)
        current.addStretch(1)
        root.addLayout(current)

        # -- custom colors -------------------------------------------------
        root.addWidget(QLabel('custom colors', self))
        self.grid = SwatchGrid(self._dark, self)
        self.grid.set_colors(load_custom_colors())
        self.grid.picked.connect(self.set_color)
        root.addWidget(self.grid)

        self.add_button = QPushButton('add to custom colors', self)
        self.add_button.clicked.connect(self._add_custom)
        root.addWidget(self.add_button)

        # -- html ----------------------------------------------------------
        html = QHBoxLayout()
        html.setSpacing(6)
        html.addWidget(QLabel('html:', self))
        self.hex_edit = QLineEdit(self)
        self.hex_edit.setMaxLength(7)
        self.hex_edit.editingFinished.connect(self._on_hex)
        html.addWidget(self.hex_edit, 1)
        root.addLayout(html)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.button(QDialogButtonBox.Ok).setText('ok')
        buttons.button(QDialogButtonBox.Cancel).setText('cancel')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.set_color(self._color)

    # -- state -------------------------------------------------------------

    def color(self):
        return self._color

    def set_color(self, color):
        color = QColor(color)
        if not color.isValid():
            return
        self._color = color
        self.square.set_color(color)
        h, s, v, _ = color.getHsv()
        self.value_slider.set_hue_sat(self.square._hue, s)
        self.value_slider.set_value(v)
        self._refresh()

    def _on_square(self, color):
        self._color = color
        h, s, _v, _ = color.getHsv()
        self.value_slider.set_hue_sat(self.square._hue, s)
        self._refresh()

    def _on_value(self, value):
        self.square.set_value(value)
        self._color = self.square.color()
        self._refresh()

    def _refresh(self):
        name = self._color.name(QColor.HexRgb)
        self.preview.setStyleSheet(
            'background-color: %s; border: 1px solid %s;'
            % (name, border_color(self._dark)))
        self.readout.setText(name)
        if self.hex_edit.text().lower() != name:
            self.hex_edit.setText(name)

    def _on_hex(self):
        text = self.hex_edit.text().strip()
        if text and not text.startswith('#'):
            text = '#' + text
        color = QColor(text)
        if color.isValid():
            self.set_color(color)
        else:
            self._refresh()

    def _add_custom(self):
        self.grid.add(self._color)
        save_custom_colors(self.grid.colors())

    # -- screen picking ----------------------------------------------------

    def _start_screen_pick(self):
        self._picking = True
        self.hint.setText('click anywhere - esc cancels')
        self.grabMouse(Qt.CrossCursor)
        self.grabKeyboard()

    def _end_screen_pick(self):
        self._picking = False
        self.hint.setText('pick from screen')
        self.releaseMouse()
        self.releaseKeyboard()

    @staticmethod
    def _screen_color(global_pos):
        screen = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
        if screen is None:
            return QColor()
        pm = screen.grabWindow(0, global_pos.x(), global_pos.y(), 1, 1)
        if pm.isNull():
            return QColor()
        return pm.toImage().pixelColor(0, 0)

    def mouseMoveEvent(self, event):
        if self._picking:
            color = self._screen_color(event.globalPos())
            if color.isValid():
                self.set_color(color)
            return
        super(ColorPicker, self).mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._picking:
            color = self._screen_color(event.globalPos())
            self._end_screen_pick()
            if color.isValid():
                self.set_color(color)
            return
        super(ColorPicker, self).mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if self._picking and event.key() == Qt.Key_Escape:
            self._end_screen_pick()
            return
        super(ColorPicker, self).keyPressEvent(event)

    # -- convenience -------------------------------------------------------

    @staticmethod
    def get_color(initial=None, parent=None, title='select color'):
        dialog = ColorPicker(initial, parent, title)
        if dialog.exec_() == QDialog.Accepted:
            return dialog.color()
        return QColor()
