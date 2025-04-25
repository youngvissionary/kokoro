import re
import asyncio
from collections import deque

def is_sentence_terminator(c, include_newlines=True):
    return c in '.!?…。？！' or (include_newlines and c == '\n')

def is_trailing_char(c):
    return c in "\"')]}」』"

def get_token_from_buffer(buffer, start):
    end = start
    while end < len(buffer) and not buffer[end].isspace():
        end += 1
    return buffer[start:end]

ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "sgt", "col", "gen",
    "rep", "sen", "gov", "lt", "maj", "capt", "st", "mt", "etc", "co",
    "inc", "ltd", "dept", "vs", "p", "pg", "jan", "feb", "mar", "apr",
    "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "sun",
    "mon", "tu", "tue", "tues", "wed", "th", "thu", "thur", "thurs", "fri", "sat"
}

def is_abbreviation(token):
    token = re.sub(r"['’]s$", "", token, flags=re.IGNORECASE)
    token = re.sub(r"\.+$", "", token)
    return token.lower() in ABBREVIATIONS

MATCHING = {
    ')': '(', ']': '[', '}': '{',
    '》': '《', '〉': '〈', '›': '‹', '»': '«',
    '〉': '〈', '」': '「', '』': '『', '〕': '〔', '】': '【'
}
OPENING = set(MATCHING.values())

def update_stack(c, stack, i, buffer):
    if c in ('"', "'"):
        if c == "'" and i > 0 and i < len(buffer) - 1:
            prev_char = buffer[i-1]
            next_char = buffer[i+1]
            if prev_char.isalpha() and next_char.isalpha():
                return
        if stack and stack[-1] == c:
            stack.pop()
        else:
            stack.append(c)
        return
    if c in OPENING:
        stack.append(c)
        return
    expected_opening = MATCHING.get(c)
    if expected_opening and stack and stack[-1] == expected_opening:
        stack.pop()

class TextSplitterStream:
    def __init__(self):
        self._buffer = ""
        self._sentences = deque()
        self._closed = False
        self._event = asyncio.Event()

    def push(self, *texts):
        for text in texts:
            self._buffer += text
            self._process()
            if self._sentences:
                self._event.set()

    def close(self):
        if self._closed:
            raise RuntimeError("Stream is already closed.")
        self._closed = True
        self.flush()

    def flush(self):
        remainder = self._buffer.strip()
        if remainder:
            self._sentences.append(remainder)
        self._buffer = ""
        self._event.set()

    def _process(self):
        buffer = self._buffer
        len_buffer = len(buffer)
        sentence_start = 0
        i = 0
        stack = []

        def scan_boundary(idx):
            end = idx
            while end + 1 < len_buffer and is_sentence_terminator(buffer[end+1], False):
                end += 1
            while end + 1 < len_buffer and is_trailing_char(buffer[end+1]):
                end += 1
            next_non_space = end + 1
            while next_non_space < len_buffer and buffer[next_non_space].isspace():
                next_non_space += 1
            return {'end': end, 'next_non_space': next_non_space}

        while i < len_buffer:
            c = buffer[i]
            update_stack(c, stack, i, buffer)

            if not stack and is_sentence_terminator(c):
                current_segment = buffer[sentence_start:i]
                if re.search(r'(^|\n)\d+$', current_segment):
                    i += 1
                    continue

                boundary = scan_boundary(i)
                boundary_end = boundary['end']
                next_non_space = boundary['next_non_space']

                if i == next_non_space - 1 and c != '\n':
                    i += 1
                    continue

                if next_non_space == len_buffer:
                    break

                token_start = i - 1
                while token_start >= 0 and not buffer[token_start].isspace():
                    token_start -= 1
                token_start = max(sentence_start, token_start + 1)
                token = get_token_from_buffer(buffer, token_start)
                if not token:
                    i += 1
                    continue

                if (('://' in token or '@' in token) and
                        not is_sentence_terminator(token[-1] if token else '')):
                    i = token_start + len(token)
                    continue

                if is_abbreviation(token):
                    i += 1
                    continue

                if (re.fullmatch(r'^([A-Za-z]\.)+$', token) and
                        next_non_space < len_buffer and buffer[next_non_space].isupper()):
                    i += 1
                    continue

                if (c == '.' and next_non_space < len_buffer and
                        buffer[next_non_space].islower()):
                    i += 1
                    continue

                sentence = buffer[sentence_start:boundary_end+1].strip()
                if sentence in ('...', '…'):
                    i += 1
                    continue

                if sentence:
                    self._sentences.append(sentence)
                i = sentence_start = boundary_end + 1
                continue
            i += 1

        self._buffer = buffer[sentence_start:]
        if self._sentences:
            self._event.set()

    async def __aiter__(self):
        return self

    async def __anext__(self):
        while True:
            if self._closed and not self._sentences:
                raise StopAsyncIteration
            if self._sentences:
                return self._sentences.popleft()
            else:
                await self._event.wait()
                self._event.clear()

    def __iter__(self):
        self.flush()
        sentences = list(self._sentences)
        self._sentences.clear()
        return iter(sentences)

def split(text):
    splitter = TextSplitterStream()
    splitter.push(text)
    splitter.close()
    return list(splitter)

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python splitter.py <text>")
        sys.exit(1)
    text = sys.argv[1]
    print(split(text))