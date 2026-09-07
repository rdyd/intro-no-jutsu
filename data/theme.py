"""system light/dark theme detection and application."""

import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QProxyStyle, QStyle, QStyleFactory

D_WINDOW = '#1e1e1e'
D_BASE = '#151515'
D_ALT_BASE = '#232323'
D_TEXT = '#e6e6e6'
D_DISABLED = '#6a6a6a'
D_BUTTON = '#2b2b2b'
D_HIGHLIGHT = '#3d6fa5'
D_BORDER = '#3a3a3a'

L_WINDOW = '#f0f0f0'
L_BASE = '#ffffff'
L_ALT_BASE = '#f7f7f7'
L_TEXT = '#1b1b1b'
L_DISABLED = '#9a9a9a'
L_BUTTON = '#e9e9e9'
L_HIGHLIGHT = '#3d6fa5'
L_BORDER = '#c4c4c4'


def system_prefers_dark():
    if sys.platform == 'win32':
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize')
            try:
                value, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
                return value == 0
            finally:
                winreg.CloseKey(key)
        except (ImportError, OSError, FileNotFoundError):
            pass

    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            window = app.palette().color(QPalette.Window)
            return window.lightness() < 128
    except Exception:
        pass
    return False


def palette_for(dark):
    p = QPalette()
    if dark:
        window, base, alt, text = D_WINDOW, D_BASE, D_ALT_BASE, D_TEXT
        disabled, button, highlight = D_DISABLED, D_BUTTON, D_HIGHLIGHT
        highlight_text = '#ffffff'
    else:
        window, base, alt, text = L_WINDOW, L_BASE, L_ALT_BASE, L_TEXT
        disabled, button, highlight = L_DISABLED, L_BUTTON, L_HIGHLIGHT
        highlight_text = '#ffffff'

    p.setColor(QPalette.Window, QColor(window))
    p.setColor(QPalette.WindowText, QColor(text))
    p.setColor(QPalette.Base, QColor(base))
    p.setColor(QPalette.AlternateBase, QColor(alt))
    p.setColor(QPalette.ToolTipBase, QColor(window))
    p.setColor(QPalette.ToolTipText, QColor(text))
    p.setColor(QPalette.Text, QColor(text))
    p.setColor(QPalette.Button, QColor(button))
    p.setColor(QPalette.ButtonText, QColor(text))
    p.setColor(QPalette.BrightText, QColor('#ff5555'))
    p.setColor(QPalette.Link, QColor(highlight))
    p.setColor(QPalette.Highlight, QColor(highlight))
    p.setColor(QPalette.HighlightedText, QColor(highlight_text))

    for group in (QPalette.Disabled,):
        p.setColor(group, QPalette.WindowText, QColor(disabled))
        p.setColor(group, QPalette.Text, QColor(disabled))
        p.setColor(group, QPalette.ButtonText, QColor(disabled))

    return p


def border_color(dark):
    return D_BORDER if dark else L_BORDER


class FlatDisabledStyle(QProxyStyle):
    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.SH_EtchDisabledText:
            return 0
        return super(FlatDisabledStyle, self).styleHint(
            hint, option, widget, returnData)


def apply_theme(app):
    dark = system_prefers_dark()
    app.setStyle(FlatDisabledStyle(QStyleFactory.create('Fusion')))
    app.setPalette(palette_for(dark))
    return dark
