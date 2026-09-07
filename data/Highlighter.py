import configparser

from PyQt5.QtCore import QRegExp
from PyQt5.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat

from .paths import settings_path

EVENT_NAMES = [
    'Default', 'default', 'Section', 'section', 'phrase_start', 'phrase_end',
    'lyric', 'idle', 'half_tempo', 'normal_tempo', 'verse', 'chorus',
    'music_start', 'lighting ()', 'lighting (flare)', 'lighting (blackout)',
    'lighting (chase)', 'lighting (strobe)', 'lighting (color1)',
    'lighting (color2)', 'lighting (sweep)', 'crowd_lighters_fast',
    'crowd_lighters_off', 'crowd_lighters_slow', 'crowd_half_tempo',
    'crowd_normal_tempo', 'crowd_double_tempo', 'band_jump', 'sync_head_bang',
    'sync_wag']

DEFAULTS = {
    'positionformat': '#FF00FF',
    'valueformat': '#F5FF5E',
    'richtagformat': '#00FF7F',
    'eventnameformat': '#03FCF4',
}


class Highlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super(Highlighter, self).__init__(parent)

        colors = dict(DEFAULTS)
        self.config = configparser.ConfigParser()
        try:
            with open(settings_path(), encoding='utf-8') as f:
                self.config.read_file(f)
            for section in self.config.sections():
                for key, value in self.config.items(section):
                    if key in colors:
                        colors[key] = value
        except (OSError, configparser.Error):
            pass

        self.highlightingRules = []

        position_format = QTextCharFormat()
        position_format.setForeground(QColor(colors['positionformat']))
        self.highlightingRules.append((QRegExp(r'(\b[0-9_]+)\s*(?==)'), position_format))

        value_format = QTextCharFormat()
        value_format.setForeground(QColor(colors['valueformat']))
        self.highlightingRules.append((QRegExp('".*"'), value_format))

        html_format = QTextCharFormat()
        html_format.setForeground(QColor(colors['richtagformat']))
        self.highlightingRules.append((QRegExp('<[^>]+>'), html_format))

        event_name_format = QTextCharFormat()
        event_name_format.setForeground(QColor(colors['eventnameformat']))
        for name in EVENT_NAMES:
            self.highlightingRules.append(
                (QRegExp(QRegExp.escape(name)), event_name_format))

    def highlightBlock(self, text):
        for pattern, char_format in self.highlightingRules:
            expression = QRegExp(pattern)
            index = expression.indexIn(text)
            while index >= 0:
                length = expression.matchedLength()
                self.setFormat(index, length, char_format)
                index = expression.indexIn(text, index + length)
