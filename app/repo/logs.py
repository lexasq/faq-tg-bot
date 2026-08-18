from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Literal

from app.logging_conf import get_logger
from app.repo.firestore import Store

logger = get_logger(__name__)

MATCH_LOG = "match_log"
MISS_LOG = "miss_log"
FEEDBACK_LOG = "feedback"

MatchAction = Literal["replied", "suggested", "silent", "mention"]
Vote = Literal["up", "down"]

_TEXT_LIMIT = 500


def _truncate(text: str) -> str:
    return text[:_TEXT_LIMIT]


class LogRepo:
    """Fire-and-forget writes: Firestore latency must never delay a reply.
    Failures are logged, not raised, since a missed log entry is not worth
    losing the group message it was describing."""

    def __init__(self, store: Store) -> None:
        self._store = store

    def log_match(
        self,
        *,
        chat_id: int,
        user_id: int,
        text: str,
        entry_id: str | None,
        score: float,
        action: MatchAction,
    ) -> None:
        self._fire(
            MATCH_LOG,
            {
                "chat_id": chat_id,
                "user_id": user_id,
                "text": _truncate(text),
                "entry_id": entry_id,
                "score": score,
                "action": action,
                "ts": datetime.utcnow(),
            },
        )

    def log_miss(
        self,
        *,
        chat_id: int,
        user_id: int,
        text: str,
        top_entry_id: str | None,
        top_score: float,
        direct_ask: bool = False,
    ) -> None:
        self._fire(
            MISS_LOG,
            {
                "chat_id": chat_id,
                "user_id": user_id,
                "text": _truncate(text),
                "top_entry_id": top_entry_id,
                "top_score": top_score,
                "direct_ask": direct_ask,
                "handled": False,
                "ts": datetime.utcnow(),
            },
        )

    def log_feedback(self, *, match_log_id: str | None, entry_id: str, user_id: int, vote: Vote) -> None:
        self._fire(
            FEEDBACK_LOG,
            {
                "match_log_id": match_log_id,
                "entry_id": entry_id,
                "user_id": user_id,
                "vote": vote,
                "ts": datetime.utcnow(),
            },
        )

    async def list_recent(self, collection: str, limit: int = 500, since: datetime | None = None) -> list[dict]:
        return await self._store.list_logs(collection, limit=limit, since=since)

    async def get(self, collection: str, doc_id: str) -> dict | None:
        return await self._store.get_log(collection, doc_id)

    async def mark_handled(self, collection: str, doc_id: str) -> None:
        await self._store.update_log(collection, doc_id, {"handled": True})

    def _fire(self, collection: str, data: dict) -> None:
        asyncio.create_task(self._write(collection, data))

    async def _write(self, collection: str, data: dict) -> None:
        try:
            await self._store.add_log(collection, data)
        except Exception:
            logger.exception("log_write_failed", collection=collection)
