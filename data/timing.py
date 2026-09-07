"""chart timing and lyric-phrase parsing."""

import re

DEFAULT_BPM = 120.0
DEFAULT_RESOLUTION = 192

NO_SLIDE_TICKS = 1

MARKER_CHARS = '-_'

TICK_LINE_RE = re.compile(r'^\s*(\d+)\s*=\s*(.+?)\s*$')
EVENT_RE = re.compile(r'^E\s+"(.*)"$')
LYRIC_RE = re.compile(r'^lyric ?(.*)$')
BPM_RE = re.compile(r'^B\s+(\d+)$')
TAG_RE = re.compile(r'<(/?)([a-zA-Z_]+)(?:=([^>]*))?>')


def parse_song_meta(song_text):
    resolution, offset = DEFAULT_RESOLUTION, 0.0
    for line in song_text.splitlines():
        if '=' not in line:
            continue
        key, _, value = line.partition('=')
        key, value = key.strip().lower(), value.strip().strip('"')
        try:
            if key == 'resolution':
                resolution = int(float(value))
            elif key == 'offset':
                offset = float(value)
        except ValueError:
            pass
    return max(1, resolution), offset


def parse_tempos(sync_text):
    tempos = []
    for line in sync_text.splitlines():
        m = TICK_LINE_RE.match(line)
        if not m:
            continue
        b = BPM_RE.match(m.group(2))
        if b:
            bpm = int(b.group(1)) / 1000.0
            if bpm > 0.0:
                tempos.append((int(m.group(1)), bpm))
    tempos.sort()
    return tempos


class ChartTiming(object):
    def __init__(self, song_text='', sync_text=''):
        self.resolution, self.offset = parse_song_meta(song_text)
        self.tempos = parse_tempos(sync_text)

    def tick_to_seconds(self, tick):
        seconds = 0.0
        prev_tick = 0
        bpm = self.tempos[0][1] if self.tempos and self.tempos[0][0] == 0 else DEFAULT_BPM
        for t, next_bpm in self.tempos:
            if t >= tick:
                break
            if t > prev_tick:
                seconds += (t - prev_tick) / self.resolution * (60.0 / bpm)
                prev_tick = t
            bpm = next_bpm
        seconds += (tick - prev_tick) / self.resolution * (60.0 / bpm)
        return seconds

    def audio_seconds(self, tick):
        return self.tick_to_seconds(tick) + self.offset

    def seconds_to_tick(self, seconds):
        if seconds <= 0.0:
            return 0.0
        prev_tick = 0
        elapsed = 0.0
        bpm = self.tempos[0][1] if self.tempos and self.tempos[0][0] == 0 else DEFAULT_BPM
        for t, next_bpm in self.tempos:
            if t > prev_tick:
                span = (t - prev_tick) / self.resolution * (60.0 / bpm)
                if elapsed + span > seconds:
                    break
                elapsed += span
                prev_tick = t
            bpm = next_bpm
        return prev_tick + (seconds - elapsed) * self.resolution * bpm / 60.0

    def tick_at_audio_seconds(self, seconds):
        return self.seconds_to_tick(seconds - self.offset)

    def beats_at(self, seconds):
        beats = 0.0
        prev_tick = 0
        elapsed = 0.0
        bpm = self.tempos[0][1] if self.tempos and self.tempos[0][0] == 0 else DEFAULT_BPM
        for t, next_bpm in self.tempos:
            if t <= prev_tick:
                bpm = next_bpm
                continue
            span = (t - prev_tick) / self.resolution * (60.0 / bpm)
            if elapsed + span >= seconds:
                break
            beats += (t - prev_tick) / float(self.resolution)
            elapsed += span
            prev_tick = t
            bpm = next_bpm
        beats += max(0.0, seconds - elapsed) * bpm / 60.0
        return beats

    def bpm_at(self, seconds):
        bpm = self.tempos[0][1] if self.tempos and self.tempos[0][0] == 0 else DEFAULT_BPM
        prev_tick = 0
        elapsed = 0.0
        for t, next_bpm in self.tempos:
            if t <= prev_tick:
                bpm = next_bpm
                continue
            span = (t - prev_tick) / self.resolution * (60.0 / bpm)
            if elapsed + span >= seconds:
                break
            elapsed += span
            prev_tick = t
            bpm = next_bpm
        return bpm


# ---------------------------------------------------------------- tag styling

class Style(object):
    __slots__ = ('bold', 'italic', 'smallcaps', 'uppercase', 'lowercase',
                 'sub', 'sup', 'base_color', 'sung_color', 'voffset',
                 'cspace', 'mspace')

    def __init__(self):
        self.bold = False
        self.italic = False
        self.smallcaps = False
        self.uppercase = False
        self.lowercase = False
        self.sub = False
        self.sup = False
        self.base_color = None
        self.sung_color = None
        self.voffset = 0.0
        self.cspace = 0.0
        self.mspace = 0.0

    def apply_text(self, text):
        if self.uppercase:
            return text.upper()
        if self.lowercase:
            return text.lower()
        return text


def _float(value, default=0.0):
    if not value:
        return default
    try:
        return float(str(value).strip().rstrip('emp%'))
    except ValueError:
        return default


def _style_from_stack(stack):
    st = Style()
    colors = []
    for name, value in stack:
        if name == 'b':
            st.bold = True
        elif name == 'i':
            st.italic = True
        elif name == 'smallcaps':
            st.smallcaps = True
        elif name == 'uppercase':
            st.uppercase = True
        elif name == 'lowercase':
            st.lowercase = True
        elif name == 'sub':
            st.sub = True
        elif name == 'sup':
            st.sup = True
        elif name == 'color':
            if value:
                colors.append(value.strip())
        elif name == 'voffset':
            st.voffset = _float(value)
        elif name == 'cspace':
            st.cspace = _float(value)
        elif name == 'mspace':
            st.mspace = _float(value)
    if colors:
        st.base_color = colors[0]
        st.sung_color = colors[1] if len(colors) > 1 else colors[0]
    return st


class Run(object):
    __slots__ = ('text', 'style')

    def __init__(self, text, style):
        self.text = text
        self.style = style


class Syllable(object):
    __slots__ = ('tick', 'runs', 'join')

    def __init__(self, tick, runs, join):
        self.tick = tick
        self.runs = runs
        self.join = join

    @property
    def text(self):
        return ''.join(r.text for r in self.runs)


class Phrase(object):
    def __init__(self, start_tick):
        self.start_tick = start_tick
        self.end_tick = None
        self.explicit_end = False
        self.syllables = []
        self.no_slide = False

    def plain_text(self):
        out = ''
        for i, s in enumerate(self.syllables):
            out += s.text
            if i < len(self.syllables) - 1:
                if s.join == '-':
                    pass
                elif s.join == '=':
                    out += '-'
                else:
                    out += ' '
        return out

    def last_tick(self):
        return self.syllables[-1].tick if self.syllables else self.start_tick


def _split_runs(raw, stack):
    runs = []
    pos = 0
    for m in TAG_RE.finditer(raw):
        if m.start() > pos:
            runs.append(Run(raw[pos:m.start()], _style_from_stack(stack)))
        closing, name, value = m.group(1), m.group(2).lower(), m.group(3)
        if closing:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == name:
                    stack.pop(i)
                    break
        elif name == 'br':
            runs.append(Run(' ', _style_from_stack(stack)))
        else:
            stack.append((name, value))
        pos = m.end()
    if pos < len(raw):
        runs.append(Run(raw[pos:], _style_from_stack(stack)))
    return runs


def parse_phrases(events_text):
    entries = []
    for line in events_text.splitlines():
        m = TICK_LINE_RE.match(line)
        if not m:
            continue
        e = EVENT_RE.match(m.group(2))
        if e:
            entries.append((int(m.group(1)), e.group(1)))
    entries.sort(key=lambda x: x[0])

    phrases = []
    current = None
    stack = []

    def close(tick, explicit):
        nonlocal current
        if current is not None and current.syllables:
            current.end_tick = tick
            current.explicit_end = explicit
            phrases.append(current)
        current = None

    for tick, body in entries:
        if body == 'phrase_start':
            close(tick, False)
            current = Phrase(tick)
            stack = []
        elif body == 'phrase_end':
            close(tick, True)
            stack = []
        else:
            lm = LYRIC_RE.match(body)
            if lm and current is not None:
                raw = lm.group(1)
                if raw.strip() == '+':
                    continue
                runs = _split_runs(raw, stack)
                joined = ''.join(r.text for r in runs)
                stripped = joined.strip()
                join = ''

                if stripped and all(c in MARKER_CHARS for c in stripped):
                    style = runs[0].style if runs else _style_from_stack(stack)
                    runs = [Run(' ', style)]
                else:
                    if joined.endswith('-'):
                        join = '-'
                    elif joined.endswith('='):
                        join = '='
                    if join and runs:
                        runs[-1].text = runs[-1].text[:-1]
                        runs = [r for r in runs if r.text]
                    for r in runs:
                        r.text = r.text.replace('=', '-')

                if any(r.text for r in runs):
                    current.syllables.append(Syllable(tick, runs, join))

    if current is not None and current.syllables:
        current.end_tick = current.last_tick() + 480
        phrases.append(current)

    for i, p in enumerate(phrases):
        nxt = phrases[i + 1].start_tick if i + 1 < len(phrases) else None
        if p.end_tick is None:
            p.end_tick = nxt if nxt is not None else p.last_tick() + 480
        if p.syllables and (p.syllables[0].tick - p.start_tick) <= NO_SLIDE_TICKS:
            p.no_slide = True
    return phrases
