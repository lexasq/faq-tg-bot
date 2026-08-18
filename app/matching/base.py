from __future__ import annotations

from typing import Protocol

from app.models import Entry, MatchResult


class Matcher(Protocol):
    async def match(self, text: str, entries: list[Entry]) -> list[MatchResult]: ...
