"""Creates 3 sample FAQ entries and one owner admin (from env ADMIN_USER_ID).

Run once against a fresh Firestore project to sanity-check the data layer
end to end. A richer example dataset lives in tests/fixtures/faq_example.md
and can be loaded via /import or scripts/bulk_import.py.
"""
from __future__ import annotations

import asyncio
import os

from app.config import get_settings
from app.models import Entry
from app.repo.admins import AdminRepo
from app.repo.entries import EntryRepo
from app.repo.firestore import FirestoreStore, build_firestore_client

SAMPLE_ENTRIES = [
    {
        "title": "Тестовий запис 1",
        "category": "Загальне",
        "answer": "Це тестова відповідь номер 1.",
        "patterns": ["тест\\w*\\s*1"],
        "keywords": ["тест"],
    },
    {
        "title": "Тестовий запис 2",
        "category": "Загальне",
        "answer": "Це тестова відповідь номер 2.",
        "patterns": ["тест\\w*\\s*2"],
        "keywords": ["тест"],
    },
    {
        "title": "Тестовий запис 3",
        "category": "Загальне",
        "answer": "Це тестова відповідь номер 3.",
        "patterns": ["тест\\w*\\s*3"],
        "keywords": ["тест"],
    },
]


async def main() -> None:
    settings = get_settings()
    client = build_firestore_client(settings)
    store = FirestoreStore(client)
    entry_repo = EntryRepo(store)
    admin_repo = AdminRepo(store)

    admin_user_id = os.environ.get("ADMIN_USER_ID")
    if not admin_user_id:
        raise SystemExit("ADMIN_USER_ID env var is required")
    admin_user_id = int(admin_user_id)

    await admin_repo.add(admin_user_id, name="Owner", role="owner", added_by=admin_user_id)
    print(f"Created owner admin {admin_user_id}")

    for data in SAMPLE_ENTRIES:
        entry = Entry.create(updated_by=admin_user_id, **data)
        saved = await entry_repo.save(entry, actor_id=admin_user_id)
        print(f"Created entry {saved.id!r}")


if __name__ == "__main__":
    asyncio.run(main())
