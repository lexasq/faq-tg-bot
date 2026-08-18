from __future__ import annotations

import re

from app.matching.normalize import normalize_text
from app.models import Entry, MatchResult
from app.repo.entries import EntryCache

QUESTION_MARKERS = [
    "?", "як", "який", "яка", "яке", "куди", "де", "коли", "скільки",
    "чи", "хто", "підкаж", "підскаж", "не знаю", "потрібн", "треба",
]

_LONG_MESSAGE_CHARS = 300
_LONG_MESSAGE_CAP = 0.50
_AMBIGUITY_MARGIN = 0.10


def has_question_marker(cleaned_text: str) -> bool:
    return any(marker in cleaned_text for marker in QUESTION_MARKERS)


def _score_entry(
    entry: Entry, cleaned_text: str, raw_text_len: int, pattern_pairs: list[tuple[str, re.Pattern[str]]]
) -> tuple[float, list[str], str]:
    matched = [raw for raw, compiled in pattern_pairs if compiled.search(cleaned_text)]
    if not matched:
        return 0.0, [], ""

    score = 0.60
    reasons = [f"matched patterns: {matched}"]

    if len(matched) >= 2:
        score += 0.10
        reasons.append("2+ distinct patterns (+0.10)")

    if has_question_marker(cleaned_text):
        score += 0.20
        reasons.append("question marker (+0.20)")

    if entry.priority > 0:
        bonus = min(entry.priority * 0.02, 0.10)
        score += bonus
        reasons.append(f"priority {entry.priority} (+{bonus:.2f})")

    if raw_text_len > _LONG_MESSAGE_CHARS:
        score = min(score, _LONG_MESSAGE_CAP)
        reasons.append(f"message > {_LONG_MESSAGE_CHARS} chars, capped at {_LONG_MESSAGE_CAP}")

    score = max(0.0, min(1.0, score))
    return score, matched, "; ".join(reasons)


def is_ambiguous(results: list[MatchResult]) -> bool:
    return len(results) >= 2 and (results[0].score - results[1].score) < _AMBIGUITY_MARGIN


def top_decision(results: list[MatchResult], threshold: float) -> MatchResult | None:
    """Below threshold, or the top two candidates too close to call, means
    don't answer."""
    if not results or results[0].score < threshold:
        return None
    if is_ambiguous(results):
        return None
    return results[0]


_ROUTER_LEAF_MARGIN = 0.15


def decide_with_router_precedence(
    results: list[MatchResult], entries_by_id: dict[str, Entry], threshold: float
) -> MatchResult | None:
    """Plan addendum A5: when a router and a leaf both match, the leaf only
    wins if it clears the router by >= 0.15; otherwise show the router,
    even if the leaf's raw score happens to be higher. This supersedes the
    generic top-two ambiguity check for this specific pairing — that's the
    router's whole purpose (the question is genuinely underspecified)."""
    if not results:
        return None

    routers = [r for r in results if entries_by_id.get(r.entry_id) and entries_by_id[r.entry_id].type == "router"]
    leaves = [r for r in results if r not in routers]

    if routers and leaves:
        top_router, top_leaf = routers[0], leaves[0]
        winner = top_leaf if (top_leaf.score - top_router.score) >= _ROUTER_LEAF_MARGIN else top_router
        return winner if winner.score >= threshold else None

    return top_decision(results, threshold)


class RegexMatcher:
    def __init__(self, cache: EntryCache) -> None:
        self._cache = cache

    async def match(self, text: str, entries: list[Entry]) -> list[MatchResult]:
        cleaned, _tokens = normalize_text(text)
        results: list[MatchResult] = []
        for entry in entries:
            score, matched, reason = _score_entry(entry, cleaned, len(text), self._cache.pattern_pairs(entry.id))
            if score > 0:
                results.append(MatchResult(entry_id=entry.id, score=score, matched_patterns=matched, reason=reason))
        results.sort(key=lambda r: r.score, reverse=True)
        return results
