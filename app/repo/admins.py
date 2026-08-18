from __future__ import annotations

import asyncio
import time
from datetime import datetime

from app.models import Admin, AdminRole
from app.repo.firestore import Store


class AdminRepo:
    def __init__(self, store: Store, ttl_seconds: float = 60.0) -> None:
        self._store = store
        self._ttl = ttl_seconds
        self._cache: dict[int, Admin] | None = None
        self._cached_at: float = 0.0
        self._lock = asyncio.Lock()

    async def _ensure_cache(self) -> dict[int, Admin]:
        if self._cache is not None and (time.monotonic() - self._cached_at) < self._ttl:
            return self._cache
        async with self._lock:
            if self._cache is not None and (time.monotonic() - self._cached_at) < self._ttl:
                return self._cache
            admins = await self._store.list_admins()
            self._cache = {a["user_id"]: Admin(**a) for a in admins}
            self._cached_at = time.monotonic()
        return self._cache

    def _invalidate(self) -> None:
        self._cache = None

    async def is_admin(self, user_id: int) -> bool:
        return user_id in await self._ensure_cache()

    async def is_owner(self, user_id: int) -> bool:
        admin = (await self._ensure_cache()).get(user_id)
        return admin is not None and admin.role == "owner"

    async def get(self, user_id: int) -> Admin | None:
        return (await self._ensure_cache()).get(user_id)

    async def list(self) -> list[Admin]:
        return list((await self._ensure_cache()).values())

    async def add(self, user_id: int, name: str, role: AdminRole, added_by: int) -> Admin:
        admin = Admin(user_id=user_id, name=name, role=role, added_by=added_by, added_at=datetime.utcnow())
        await self._store.set_admin(user_id, admin.model_dump())
        self._invalidate()
        return admin

    async def remove(self, user_id: int) -> None:
        await self._store.delete_admin(user_id)
        self._invalidate()
