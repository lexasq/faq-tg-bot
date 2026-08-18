from __future__ import annotations

import itertools
from copy import deepcopy


class FakeStore:
    """In-memory stand-in for app.repo.firestore.Store. No network, no
    Firestore emulator required — this is what every test in this suite
    runs the domain repos against."""

    def __init__(self) -> None:
        self._entries: dict[str, dict] = {}
        self._revisions: dict[str, dict[str, dict]] = {}
        self._config: dict = {"entries_version": 0}
        self._admins: dict[int, dict] = {}
        self._logs: dict[str, list[dict]] = {}
        self._log_ids = itertools.count(1)

    async def get_entry(self, entry_id: str) -> dict | None:
        data = self._entries.get(entry_id)
        return deepcopy(data) if data is not None else None

    async def list_entries(self) -> list[dict]:
        return [deepcopy(d) for d in self._entries.values()]

    async def write_entry_with_revision(self, entry_id: str, new_data: dict, previous: dict | None) -> None:
        if previous is not None:
            self._revisions.setdefault(entry_id, {})[str(previous["version"])] = deepcopy(previous)
        self._entries[entry_id] = deepcopy(new_data)
        self._config["entries_version"] = self._config.get("entries_version", 0) + 1

    async def delete_entry(self, entry_id: str) -> None:
        self._entries.pop(entry_id, None)
        self._config["entries_version"] = self._config.get("entries_version", 0) + 1

    async def list_revisions(self, entry_id: str) -> list[dict]:
        return [deepcopy(d) for d in self._revisions.get(entry_id, {}).values()]

    async def get_config(self) -> dict:
        return deepcopy(self._config)

    async def update_config(self, patch: dict) -> None:
        self._config.update(deepcopy(patch))

    async def get_admin(self, user_id: int) -> dict | None:
        data = self._admins.get(user_id)
        return deepcopy(data) if data is not None else None

    async def list_admins(self) -> list[dict]:
        return [deepcopy(d) for d in self._admins.values()]

    async def set_admin(self, user_id: int, data: dict) -> None:
        self._admins[user_id] = deepcopy(data)

    async def delete_admin(self, user_id: int) -> None:
        self._admins.pop(user_id, None)

    async def add_log(self, collection: str, data: dict) -> str:
        log_id = str(next(self._log_ids))
        entry = {"id": log_id, **deepcopy(data)}
        self._logs.setdefault(collection, []).append(entry)
        return log_id

    async def list_logs(self, collection: str, limit: int = 500, since=None) -> list[dict]:
        items = self._logs.get(collection, [])
        if since is not None:
            items = [d for d in items if d["ts"] >= since]
        items = sorted(items, key=lambda d: d["ts"], reverse=True)
        return [deepcopy(d) for d in items[:limit]]

    async def get_log(self, collection: str, doc_id: str) -> dict | None:
        for d in self._logs.get(collection, []):
            if d["id"] == doc_id:
                return deepcopy(d)
        return None

    async def update_log(self, collection: str, doc_id: str, patch: dict) -> None:
        for d in self._logs.get(collection, []):
            if d["id"] == doc_id:
                d.update(deepcopy(patch))
                return
