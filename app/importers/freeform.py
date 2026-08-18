from __future__ import annotations

import re
from dataclasses import dataclass

_URL_RE = re.compile(r"https?://\S+")
_SENTENCE_END = (".", "!", "?", "…")
_TITLE_MAX_LEN = 60
# A line that's nothing but repeats of one divider character ("---",
# "___", "===", "***", ...) — people use these as visual section breaks
# in a casual paste. Without treating them as block boundaries, everything
# between the nearest actual blank lines becomes one block, which can
# glue several unrelated topics into a single answer.
_DIVIDER_RE = re.compile(r"^([-_=*~])\1{2,}$")


def _is_divider(line: str) -> bool:
    return bool(_DIVIDER_RE.match(line.strip()))


@dataclass
class ParsedBlock:
    title: str | None
    body: str
    confidence: str  # "high" | "orphan"
    source_lines: tuple[int, int]


def _split_into_blocks(text: str) -> list[tuple[int, int, list[str]]]:
    # Markdown hard-break (trailing double space) just means "this is a
    # deliberate line break" — stripping the trailing spaces doesn't lose
    # any information since we already split on newlines.
    lines = [l.rstrip() for l in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    blocks: list[tuple[int, int, list[str]]] = []
    current: list[str] = []
    start = 1
    for i, line in enumerate(lines, start=1):
        if line.strip() == "" or _is_divider(line):
            if current:
                blocks.append((start, i - 1, current))
                current = []
            start = i + 1
        else:
            current.append(line)
    if current:
        blocks.append((start, len(lines), current))
    return blocks


def _is_only_urls(lines: list[str]) -> bool:
    return all(_URL_RE.fullmatch(l.strip()) for l in lines if l.strip())


def _classify(start: int, end: int, lines: list[str]) -> ParsedBlock:
    joined_raw = "\n".join(lines)

    if _is_only_urls(lines):
        return ParsedBlock(title=None, body=joined_raw.strip(), confidence="orphan", source_lines=(start, end))

    first = lines[0]
    rest = lines[1:]

    url_match = _URL_RE.search(first)
    if url_match and first[: url_match.start()].strip():
        title = first[: url_match.start()].strip().rstrip(":,;-— ")
        body_first_line = first[url_match.start() :].strip()
        body = "\n".join([body_first_line, *rest]).strip()
        if title:
            return ParsedBlock(title=title, body=body, confidence="high", source_lines=(start, end))

    if first.rstrip().endswith(":") and len(first) <= _TITLE_MAX_LEN:
        title = first.rstrip()[:-1].strip()
        body = "\n".join(rest).strip()
        if title and body:
            return ParsedBlock(title=title, body=body, confidence="high", source_lines=(start, end))

    if len(first) <= _TITLE_MAX_LEN and not first.rstrip().endswith(_SENTENCE_END) and rest:
        return ParsedBlock(title=first.strip(), body="\n".join(rest).strip(), confidence="high", source_lines=(start, end))

    # first line > 60 chars, or the whole block is a single paragraph
    return ParsedBlock(title=None, body=joined_raw.strip(), confidence="orphan", source_lines=(start, end))


def segment_freeform(text: str) -> list[ParsedBlock]:
    return [_classify(start, end, lines) for start, end, lines in _split_into_blocks(text)]
