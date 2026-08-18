from __future__ import annotations

from app.models import Entry, MatchResult


class AiMatcher:
    """A hybrid matcher that only calls an LLM for the regex matcher's gray
    zone. Deliberately not implemented yet: it needs real miss_log data to
    calibrate against, which only exists once the regex matcher has been
    running for a while."""

    async def match(self, text: str, entries: list[Entry]) -> list[MatchResult]:
        raise NotImplementedError("AI matcher is not implemented yet")
