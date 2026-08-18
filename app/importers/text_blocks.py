from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import date


@dataclass
class ParsedEntry:
    title: str
    category: str
    answer: str
    patterns: list[str] = field(default_factory=list)
    visibility: str = "public"
    type: str = "answer"
    children: list[str] = field(default_factory=list)
    review_after: date | None = None
    source_line: int = 0


@dataclass
class ParseError:
    line: int
    message: str


def split_pattern_list(raw: str) -> list[str]:
    """Split a comma-separated KEYS/pattern list without breaking on a
    comma that's part of a regex quantifier like {0,20} or otherwise
    nested inside (){}/[] — e.g. "рахунок(?!.{0,20}(осбб|тепл))" is one
    pattern, not four fragments. Only a comma at bracket-depth 0 is a
    real separator."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for ch in raw:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def _split_blocks(text: str) -> list[tuple[int, list[str]]]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[tuple[int, list[str]]] = []
    current: list[str] = []
    start_line = 1
    for i, line in enumerate(lines, start=1):
        if line.strip() == "---":
            if any(l.strip() for l in current):
                blocks.append((start_line, current))
            current = []
            start_line = i + 1
        else:
            current.append(line)
    if any(l.strip() for l in current):
        blocks.append((start_line, current))
    return blocks


def _parse_block(start_line: int, lines: list[str]) -> ParsedEntry | ParseError:
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    if idx >= len(lines) or not lines[idx].lstrip().startswith("Q:"):
        return ParseError(start_line, "block must start with 'Q:'")

    title = lines[idx].split("Q:", 1)[1].strip()
    idx += 1

    category = "Загальне"
    patterns: list[str] = []
    visibility = "public"
    type_ = "answer"
    children: list[str] = []
    review_after: date | None = None
    answer_lines: list[str] = []
    in_answer = False

    for line in lines[idx:]:
        if in_answer:
            answer_lines.append(line)
            continue
        stripped = line.lstrip()
        if stripped.startswith("CAT:"):
            category = stripped[4:].strip() or "Загальне"
        elif stripped.startswith("KEYS:"):
            patterns = split_pattern_list(stripped[5:])
        elif stripped.startswith("VIS:"):
            v = stripped[4:].strip().lower()
            if v in ("public", "dm_only"):
                visibility = v
        elif stripped.startswith("TYPE:"):
            t = stripped[5:].strip().lower()
            if t in ("answer", "router"):
                type_ = t
        elif stripped.startswith("CHILDREN:"):
            children = [c.strip() for c in stripped[9:].split(",") if c.strip()]
        elif stripped.startswith("REVIEW:"):
            raw = stripped[7:].strip()
            if raw:
                with contextlib.suppress(ValueError):
                    review_after = date.fromisoformat(raw)
        elif stripped.startswith("A:"):
            in_answer = True
            rest = stripped[2:]
            if rest.strip():
                answer_lines.append(rest.lstrip())
        # any other stray line before "A:" is ignored (lenient parser)

    if not title:
        return ParseError(start_line, "missing title after 'Q:'")

    answer = "\n".join(answer_lines).strip("\n")
    if not answer.strip():
        return ParseError(start_line, f"block '{title}' has no 'A:' answer")

    return ParsedEntry(
        title=title,
        category=category,
        answer=answer,
        patterns=patterns,
        visibility=visibility,
        type=type_,
        children=children,
        review_after=review_after,
        source_line=start_line,
    )


def is_strict_format(text: str) -> bool:
    return text.lstrip().startswith("Q:")


def parse_strict(text: str) -> tuple[list[ParsedEntry], list[ParseError]]:
    entries: list[ParsedEntry] = []
    errors: list[ParseError] = []
    for start_line, lines in _split_blocks(text):
        result = _parse_block(start_line, lines)
        if isinstance(result, ParseError):
            errors.append(result)
        else:
            entries.append(result)
    return entries, errors


def render_strict_block(entry) -> str:
    """The inverse of parse_strict — used by /export so export -> edit ->
    import round-trips."""
    lines = [f"Q: {entry.title}", f"CAT: {entry.category}"]
    if getattr(entry, "visibility", "public") != "public":
        lines.append(f"VIS: {entry.visibility}")
    if getattr(entry, "type", "answer") != "answer":
        lines.append(f"TYPE: {entry.type}")
    children = getattr(entry, "children", None)
    if children:
        lines.append(f"CHILDREN: {', '.join(children)}")
    review_after = getattr(entry, "review_after", None)
    if review_after:
        lines.append(f"REVIEW: {review_after.isoformat()}")
    if entry.patterns:
        lines.append(f"KEYS: {', '.join(entry.patterns)}")
    lines.append("A:")
    lines.append(entry.answer)
    return "\n".join(lines)


def render_strict_export(entries) -> str:
    return "\n---\n".join(render_strict_block(e) for e in entries)
