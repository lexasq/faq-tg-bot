from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

# National (passport-style) transliteration: г->h, х->kh, и->y, і/ї/й->i,
# є->ie, ю->iu, я->ia, ь and apostrophes dropped. Deterministic so imports
# are idempotent and router `children` slugs stay stable across runs.
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e",
    "є": "ie", "ж": "zh", "з": "z", "и": "y", "і": "i", "ї": "i", "й": "i",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "shch", "ю": "iu", "я": "ia",
    "ь": "", "'": "", "ʼ": "", "’": "", "́": "",
}


def slugify(title: str) -> str:
    text = unicodedata.normalize("NFC", title).lower()
    out: list[str] = []
    for ch in text:
        if ch in _TRANSLIT:
            out.append(_TRANSLIT[ch])
        elif ch.isalnum():
            out.append(ch)
        else:
            out.append("_")
    return re.sub(r"_+", "_", "".join(out)).strip("_")


Visibility = Literal["public", "dm_only"]
EntryType = Literal["answer", "router"]
AdminRole = Literal["owner", "editor"]

DEFAULT_ROUTER_PRIORITY = -5


class Entry(BaseModel):
    id: str
    title: str
    slug: str
    category: str = "Загальне"
    answer: str
    patterns: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    priority: int = 0
    enabled: bool = True
    version: int = 1
    updated_at: datetime
    updated_by: int
    visibility: Visibility = "public"
    type: EntryType = "answer"
    children: list[str] = Field(default_factory=list)
    review_after: date | None = None

    @classmethod
    def create(
        cls,
        *,
        title: str,
        answer: str,
        updated_by: int,
        category: str = "Загальне",
        patterns: list[str] | None = None,
        keywords: list[str] | None = None,
        priority: int | None = None,
        visibility: Visibility = "public",
        type: EntryType = "answer",
        children: list[str] | None = None,
        review_after: date | None = None,
    ) -> Entry:
        slug = slugify(title)
        if priority is None:
            priority = DEFAULT_ROUTER_PRIORITY if type == "router" else 0
        return cls(
            id=slug,
            title=title,
            slug=slug,
            category=category,
            answer=answer,
            patterns=patterns or [],
            keywords=keywords or [],
            priority=priority,
            enabled=True,
            version=1,
            updated_at=datetime.utcnow(),
            updated_by=updated_by,
            visibility=visibility,
            type=type,
            children=children or [],
            review_after=review_after,
        )


class Admin(BaseModel):
    user_id: int
    name: str
    role: AdminRole = "editor"
    added_by: int
    added_at: datetime


class BotConfig(BaseModel):
    model_config = {"extra": "ignore"}

    chat_ids: list[int] = Field(default_factory=list)
    autoreply_enabled: bool = True
    auto_threshold: float = 0.75
    suggest_threshold: float = 0.45
    cooldown_seconds: int = 900
    matcher: str = "regex"
    entries_version: int = 0


class MatchResult(BaseModel):
    entry_id: str
    score: float
    matched_patterns: list[str] = Field(default_factory=list)
    reason: str = ""
