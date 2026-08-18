from __future__ import annotations

import unicodedata

# Visual homoglyphs typed on the wrong keyboard layout (section 5.1 of the
# plan). Deliberately NOT a full Latin->Cyrillic transliteration table —
# e.g. "d" has no Cyrillic lookalike here, so "dtek" only partially maps.
_HOMOGLYPHS = {
    "a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "x": "х",
    "i": "і", "y": "у", "k": "к", "m": "м", "t": "т", "h": "н", "b": "в",
}
_APOSTROPHES = {"'": "'", "ʼ": "'", "`": "'", "´": "'", "’": "'"}
_KEEP_PUNCT = set("'-?")


def _map_char(ch: str) -> str:
    return _HOMOGLYPHS.get(ch) or _APOSTROPHES.get(ch) or ch


def normalize_text(text: str) -> tuple[str, list[str]]:
    text = unicodedata.normalize("NFC", text).lower()
    mapped = "".join(_map_char(ch) for ch in text)
    kept = "".join(ch if (ch.isalnum() or ch in _KEEP_PUNCT) else " " for ch in mapped)
    cleaned = " ".join(kept.split())
    tokens = cleaned.split(" ") if cleaned else []
    return cleaned, tokens


def normalize_pattern(pattern: str) -> str:
    """Homoglyph/apostrophe-map a stored regex source so it matches text
    that went through normalize_text(). Deliberately skips lowercasing
    (EntryCache compiles with re.IGNORECASE) since blindly lowercasing
    would corrupt case-sensitive escapes like \\W, \\S, \\B."""
    text = unicodedata.normalize("NFC", pattern)
    return "".join(_map_char(ch) for ch in text)
