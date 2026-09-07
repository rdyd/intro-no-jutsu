"""lyric color no jutsu (method 1)."""

import configparser
import re

from .paths import settings_path

EVENT_LINE_RE = re.compile(r'^\s*\d+ = \S')

DEFAULT_COLOR = '#fca101'
DEFAULT_HIDDEN_LYRIC = '_'


class LyricColorJutsu(object):
    def __init__(self):
        self.hidden_lyric = DEFAULT_HIDDEN_LYRIC
        config = configparser.ConfigParser()
        try:
            with open(settings_path(), encoding='utf-8') as f:
                config.read_file(f)
            self.hidden_lyric = config.get('setLyric', 'hidden_lyric')
        except (OSError, configparser.Error):
            pass
        self.selected_color = None

    # ---- helpers (verbatim semantics from the original) -------------------

    def get_lines(self, events, position):
        lines = []
        current_line = ''
        current_position = None
        for event in events:
            pos, event_data = event.split(' = ')
            event_name, *value = event_data.strip('E "').split(' ')
            value = ' '.join(value)
            pos = int(pos)
            if current_position == position:
                lines.append(current_line)
            if pos == position:
                current_position = pos
                current_line = event
            elif event_name == 'phrase_start' or event_name == 'phrase_end':
                current_position = None
            if current_position is not None and pos != position:
                current_line = event
        if current_position == position:
            lines.append(current_line)
        return lines

    def get_lyric_item(self, events):
        lines_temp = []
        for line in events[1:]:
            pos, event_data = line.split(' = ')
            event_name, *value = event_data.strip('E "').split(' ')
            value = ' '.join(value)
            if event_name != 'section':
                lines_temp.append(value)
        return lines_temp

    def convert_list_to_string(self, lyric_items):
        result = ''
        for i, item in enumerate(lyric_items):
            if i > 0 and not lyric_items[i - 1].endswith('-'):
                result += ' '
            result += item.rstrip('-')
        return result

    def get_section_lines(self, script):
        section_lines = []
        for line in script:
            parts = line.split(' = ')
            if len(parts) == 2:
                pos, event_data = parts
                event_name = event_data.strip('E "').split(' ')[0]
                if event_name == 'section':
                    section_lines.append(line)
        return section_lines

    def remove_section_lines(self, script):
        filtered_script = []
        for line in script:
            parts = line.split(' = ')
            if len(parts) == 2:
                event_name = parts[1].strip('E "').split(' ')[0]
                if event_name != 'section':
                    filtered_script.append(line)
                continue
            filtered_script.append(line)
        return filtered_script

    def find_first_lyric_element(self, lyric_items):
        first_lyric_element = None
        for item in lyric_items:
            if 'lyric' in item:
                first_lyric_element = item
                lyric_items.remove(item)
                break
        return first_lyric_element

    def find_last_lyric_element(self, lyric_items):
        last_lyric_element = None
        for item in reversed(lyric_items):
            if 'lyric' in item:
                last_lyric_element = item
                lyric_items.remove(item)
                break
        return last_lyric_element

    def split_lyric(self, lyric):
        parts = lyric.split(' = E "lyric ')
        position = int(parts[0])
        lyric_value = parts[1].strip('"')
        return position, lyric_value

    def insert_and_sort(self, script, element):
        if isinstance(element, list):
            script.extend(element)
        elif isinstance(element, str):
            script.append(element)
        return sorted(script, key=lambda x: int(x.split(' = ')[0]))

    def apply_lyric_color(self, lyric, pos, syllable):
        hex_value = str(self.selected_color) if self.selected_color is not None else DEFAULT_COLOR
        line1 = str(int(pos) - 4) + ' = E "lyric ' + lyric + '"'
        line2 = str(int(pos) - 3) + ' = E "phrase_start"'
        line3 = str(int(pos) - 2) + ' = E "lyric ' + self.hidden_lyric + '"'
        line4 = str(int(pos) - 1) + ' = E "phrase_start"'
        line5 = str(int(pos)) + ' = E "lyric <color=#FFFFFF><color=' + hex_value + '>' + syllable + '"'
        return [line1, line2, line3, line4, line5]

    def apply_lyric_close(self, pos, syllable):
        return str(int(pos)) + ' = E "lyric ' + syllable + '</color></color>"'

    def remove_elements(self, list1, list2):
        return [x for x in list1 if x not in list2]

    def check_position_in_script(self, script, position):
        for line in script:
            if line.startswith(str(position) + ' = '):
                return True
        return False

    def extract_phrase_start(self, lines):
        phrase_start = None
        remaining_lines = []
        if lines:
            if lines[0].endswith('phrase_start"'):
                phrase_start = lines[0]
                remaining_lines = lines[1:]
            else:
                return None, lines
        return phrase_start, remaining_lines

    # ---- entry point -----------------------------------------------------

    def build(self, script_text, position, color):
        self.selected_color = color
        value = [line for line in script_text.splitlines() if line.strip()]
        stray = next((l for l in value if not EVENT_LINE_RE.match(l)
                      or l.count(' = ') != 1), None)
        if stray is not None:
            raise ValueError(
                'this line cannot be read as a chart event:\n' + stray.strip())

        if not self.check_position_in_script(value, position):
            raise ValueError('Position not found!')

        temp_section = self.get_section_lines(value)
        temp_value = self.remove_section_lines(value)

        lines = self.get_lines(value, position)
        temp_value = self.remove_elements(temp_value, lines)
        lines = self.remove_section_lines(lines)
        lyric_items = self.get_lyric_item(lines)

        temp_ps, _liness = self.extract_phrase_start(lines)
        if temp_ps is None:
            raise ValueError("Position must be start with 'phrase_start'!")

        lyric_items = self.convert_list_to_string(lyric_items)
        first_lyric = self.find_first_lyric_element(lines)
        last_lyric = self.find_last_lyric_element(lines)

        try:
            f_pos, f_value = self.split_lyric(first_lyric)
            l_pos, l_value = self.split_lyric(last_lyric)

            first_phrase = self.apply_lyric_color(lyric_items, f_pos, f_value)
            last_phrase = self.apply_lyric_close(l_pos, l_value)

            lines = self.insert_and_sort(lines, first_phrase)
            lines = self.insert_and_sort(lines, last_phrase)

            final_result = self.insert_and_sort(temp_value, lines)
            final_result = self.insert_and_sort(final_result, temp_section)
            return '\n'.join(final_result)
        except (TypeError, ValueError, AttributeError, IndexError):
            raise ValueError('Make sure you choose the correct part of the phrase!')
