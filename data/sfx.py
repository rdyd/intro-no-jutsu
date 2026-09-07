"""small ui sounds."""

import math
import os
import struct

from PyQt5.QtCore import QDir, QUrl
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer, QSoundEffect

RATE = 44100
CLICK_MS = 34
CLICK_HZ = 1180.0
CLICK_GAIN = 0.16
CLICK_VOLUME = 0.35

_click = None
_players = []


def _wav_bytes(count):
    return 44 + 2 * count


def _write_wav(path, samples, rate=RATE):
    data = b''.join(struct.pack('<h', int(max(-1.0, min(1.0, s)) * 32767))
                    for s in samples)
    with open(path, 'wb') as f:
        f.write(b'RIFF')
        f.write(struct.pack('<I', 36 + len(data)))
        f.write(b'WAVEfmt ')
        f.write(struct.pack('<IHHIIHH', 16, 1, 1, rate, rate * 2, 2, 16))
        f.write(b'data')
        f.write(struct.pack('<I', len(data)))
        f.write(data)


def _render_click():
    total = int(RATE * CLICK_MS / 1000.0)
    attack = max(1, int(total * 0.12))
    samples = []
    for i in range(total):
        t = i / float(RATE)
        if i < attack:
            env = i / float(attack)
        else:
            env = math.exp(-5.0 * (i - attack) / float(total - attack))
        value = (math.sin(2.0 * math.pi * CLICK_HZ * t)
                 + 0.30 * math.sin(4.0 * math.pi * CLICK_HZ * t))
        samples.append(value * env * CLICK_GAIN)
    return samples


def _click_effect():
    global _click
    if _click is not None:
        return _click
    try:
        path = os.path.join(QDir.tempPath(), 'inj_click.wav')
        samples = _render_click()
        try:
            stale = os.path.getsize(path) != _wav_bytes(len(samples))
        except OSError:
            stale = True
        if stale:
            _write_wav(path, samples)
        effect = QSoundEffect()
        effect.setSource(QUrl.fromLocalFile(path))
        effect.setVolume(CLICK_VOLUME)
        _click = effect
    except Exception:
        _click = False
    return _click


def blip():
    effect = _click_effect()
    if effect:
        try:
            effect.play()
        except Exception:
            pass


def play_file(path):
    try:
        if not path or not os.path.exists(path):
            return
        player = QMediaPlayer()
        player.setMedia(QMediaContent(QUrl.fromLocalFile(os.path.abspath(path))))
        player.setVolume(85)
        player.play()
        _players.append(player)
        if len(_players) > 4:
            _players.pop(0)
    except Exception:
        pass
