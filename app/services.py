from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.matching.base import Matcher
from app.repo.admins import AdminRepo
from app.repo.entries import EntryCache, EntryRepo
from app.repo.firestore import Store
from app.repo.logs import LogRepo


@dataclass
class Services:
    settings: Settings
    store: Store
    entry_repo: EntryRepo
    entry_cache: EntryCache
    admin_repo: AdminRepo
    log_repo: LogRepo
    matcher: Matcher | None = None


def get_services(bot_data: dict) -> Services:
    return bot_data["services"]
