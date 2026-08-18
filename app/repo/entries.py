from __future__ import annotations

import asyncio
import contextlib
import re
import zlib
from datetime import datetime

from app.logging_conf import get_logger
from app.matching.normalize import normalize_pattern
from app.models import BotConfig, Entry, Visibility
from app.repo.firestore import Store

logger = get_logger(__name__)


def short_id(entry_id: str) -> str:
    """Deterministic short token for an entry id, for use in callback_data
    (Telegram caps that at 64 bytes and our slugs can run past 40 chars)."""
    return format(zlib.crc32(entry_id.encode()) & 0xFFFFFFF, "x")


class EntryRepo:
    def __init__(self, store: Store) -> None:
        self._store = store

    async def get(self, entry_id: str) -> Entry | None:
        data = await self._store.get_entry(entry_id)
        return Entry(**data) if data is not None else None

    async def list_all(self) -> list[Entry]:
        return [Entry(**d) for d in await self._store.list_entries()]

    async def save(self, entry: Entry, *, actor_id: int) -> Entry:
        previous = await self._store.get_entry(entry.id)
        version = previous["version"] + 1 if previous is not None else entry.version
        entry = entry.model_copy(update={"version": version, "updated_at": datetime.utcnow(), "updated_by": actor_id})
        await self._store.write_entry_with_revision(entry.id, entry.model_dump(), previous)
        return entry

    async def delete(self, entry_id: str) -> None:
        await self._store.delete_entry(entry_id)

    async def set_enabled(self, entry_id: str, enabled: bool, *, actor_id: int) -> Entry | None:
        entry = await self.get(entry_id)
        if entry is None:
            return None
        return await self.save(entry.model_copy(update={"enabled": enabled}), actor_id=actor_id)

    async def set_visibility(self, entry_id: str, visibility: Visibility, *, actor_id: int) -> Entry | None:
        entry = await self.get(entry_id)
        if entry is None:
            return None
        return await self.save(entry.model_copy(update={"visibility": visibility}), actor_id=actor_id)

    async def revisions(self, entry_id: str) -> list[dict]:
        return await self._store.list_revisions(entry_id)


class EntryCache:
    """Loads all entries into memory and only re-hits the store when
    config/bot.entries_version changes — a 200-entry FAQ should cost a few
    reads/hour, not one per group message."""

    def __init__(self, entry_repo: EntryRepo, store: Store, poll_interval: float = 30.0) -> None:
        self._entry_repo = entry_repo
        self._store = store
        self._poll_interval = poll_interval
        self._entries: dict[str, Entry] = {}
        self._pattern_pairs: dict[str, list[tuple[str, re.Pattern[str]]]] = {}
        self._short_to_id: dict[str, str] = {}
        self._config: BotConfig = BotConfig()
        self._known_version: int | None = None
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    @property
    def config(self) -> BotConfig:
        return self._config

    async def refresh(self, force: bool = False) -> bool:
        config = await self._store.get_config()
        self._config = BotConfig(**config)
        version = config.get("entries_version", 0)
        if not force and version == self._known_version:
            return False
        async with self._lock:
            entries = await self._entry_repo.list_all()
            pattern_pairs: dict[str, list[tuple[str, re.Pattern[str]]]] = {}
            for entry in entries:
                pairs: list[tuple[str, re.Pattern[str]]] = []
                for raw in entry.patterns:
                    try:
                        compiled = re.compile(normalize_pattern(raw), re.IGNORECASE | re.UNICODE)
                    except re.error as exc:
                        logger.warning("invalid_pattern", entry_id=entry.id, pattern=raw, error=str(exc))
                        continue
                    pairs.append((raw, compiled))
                pattern_pairs[entry.id] = pairs
            self._entries = {e.id: e for e in entries}
            self._pattern_pairs = pattern_pairs
            self._short_to_id = {short_id(e.id): e.id for e in entries}
            self._known_version = version
        return True

    def get_all_enabled(self) -> list[Entry]:
        return [e for e in self._entries.values() if e.enabled]

    def get_all(self) -> list[Entry]:
        return list(self._entries.values())

    def get(self, entry_id: str) -> Entry | None:
        return self._entries.get(entry_id)

    def resolve_short(self, token: str) -> str | None:
        return self._short_to_id.get(token)

    def pattern_pairs(self, entry_id: str) -> list[tuple[str, re.Pattern[str]]]:
        return self._pattern_pairs.get(entry_id, [])

    def compiled_patterns(self, entry_id: str) -> list[re.Pattern[str]]:
        return [compiled for _, compiled in self.pattern_pairs(entry_id)]

    async def start(self) -> None:
        await self.refresh(force=True)
        self._task = asyncio.create_task(self._poll_loop())

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(self._poll_interval)
            try:
                await self.refresh()
            except Exception:
                logger.exception("cache_refresh_failed")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
