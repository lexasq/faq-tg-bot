from __future__ import annotations

from datetime import date, datetime, time
from typing import Protocol

from google.cloud import firestore

from app.config import Settings

ENTRIES_COLLECTION = "faq_entries"
REVISIONS_SUBCOLLECTION = "revisions"
ADMINS_COLLECTION = "admins"
CONFIG_COLLECTION = "config"
CONFIG_DOC = "bot"


class Store(Protocol):
    """Everything app/repo/{entries,admins,logs}.py needs from a backing
    store. FirestoreStore implements this against real Firestore;
    tests/fakes.py implements it in-memory so the domain repos never touch
    a live Firestore connection during tests."""

    async def get_entry(self, entry_id: str) -> dict | None: ...
    async def list_entries(self) -> list[dict]: ...
    async def write_entry_with_revision(self, entry_id: str, new_data: dict, previous: dict | None) -> None: ...
    async def delete_entry(self, entry_id: str) -> None: ...
    async def list_revisions(self, entry_id: str) -> list[dict]: ...

    async def get_config(self) -> dict: ...
    async def update_config(self, patch: dict) -> None: ...

    async def get_admin(self, user_id: int) -> dict | None: ...
    async def list_admins(self) -> list[dict]: ...
    async def set_admin(self, user_id: int, data: dict) -> None: ...
    async def delete_admin(self, user_id: int) -> None: ...

    async def add_log(self, collection: str, data: dict) -> str: ...
    async def list_logs(self, collection: str, limit: int = 500, since: datetime | None = None) -> list[dict]: ...
    async def get_log(self, collection: str, doc_id: str) -> dict | None: ...
    async def update_log(self, collection: str, doc_id: str, patch: dict) -> None: ...


def build_firestore_client(settings: Settings) -> firestore.AsyncClient:
    return firestore.AsyncClient(project=settings.FIRESTORE_PROJECT_ID or None)


def _encode_entry_dates(data: dict) -> dict:
    # google-cloud-firestore only knows how to encode datetime.datetime as
    # a Timestamp; Entry.review_after is a plain date and raises
    # TypeError('Cannot convert to a Firestore Value', ...) unencoded.
    review_after = data.get("review_after")
    if isinstance(review_after, date) and not isinstance(review_after, datetime):
        data = {**data, "review_after": datetime.combine(review_after, time.min)}
    return data


def _decode_entry_dates(data: dict) -> dict:
    review_after = data.get("review_after")
    if isinstance(review_after, datetime):
        data = {**data, "review_after": review_after.date()}
    return data


class FirestoreStore:
    def __init__(self, client: firestore.AsyncClient) -> None:
        self._client = client

    def _entry_ref(self, entry_id: str):
        return self._client.collection(ENTRIES_COLLECTION).document(entry_id)

    async def get_entry(self, entry_id: str) -> dict | None:
        snap = await self._entry_ref(entry_id).get()
        return _decode_entry_dates(snap.to_dict()) if snap.exists else None

    async def list_entries(self) -> list[dict]:
        docs = self._client.collection(ENTRIES_COLLECTION).stream()
        return [_decode_entry_dates(doc.to_dict()) async for doc in docs]

    async def write_entry_with_revision(self, entry_id: str, new_data: dict, previous: dict | None) -> None:
        entry_ref = self._entry_ref(entry_id)
        config_ref = self._client.collection(CONFIG_COLLECTION).document(CONFIG_DOC)
        new_data = _encode_entry_dates(new_data)
        previous = _encode_entry_dates(previous) if previous is not None else None

        @firestore.async_transactional
        async def _txn(transaction: firestore.AsyncTransaction) -> None:
            if previous is not None:
                revision_ref = entry_ref.collection(REVISIONS_SUBCOLLECTION).document(str(previous["version"]))
                transaction.set(revision_ref, previous)
            transaction.set(entry_ref, new_data)
            # .update() requires the doc to already exist; config/bot won't
            # on a brand-new database, so the very first write would 404.
            # .set(merge=True) creates-or-merges and still applies the
            # Increment transform correctly either way.
            transaction.set(config_ref, {"entries_version": firestore.Increment(1)}, merge=True)

        transaction = self._client.transaction()
        await _txn(transaction)

    async def delete_entry(self, entry_id: str) -> None:
        await self._entry_ref(entry_id).delete()
        config_ref = self._client.collection(CONFIG_COLLECTION).document(CONFIG_DOC)
        await config_ref.set({"entries_version": firestore.Increment(1)}, merge=True)

    async def list_revisions(self, entry_id: str) -> list[dict]:
        docs = self._entry_ref(entry_id).collection(REVISIONS_SUBCOLLECTION).stream()
        return [_decode_entry_dates(doc.to_dict()) async for doc in docs]

    async def get_config(self) -> dict:
        snap = await self._client.collection(CONFIG_COLLECTION).document(CONFIG_DOC).get()
        return snap.to_dict() if snap.exists else {}

    async def update_config(self, patch: dict) -> None:
        await self._client.collection(CONFIG_COLLECTION).document(CONFIG_DOC).set(patch, merge=True)

    def _admin_ref(self, user_id: int):
        return self._client.collection(ADMINS_COLLECTION).document(str(user_id))

    async def get_admin(self, user_id: int) -> dict | None:
        snap = await self._admin_ref(user_id).get()
        return snap.to_dict() if snap.exists else None

    async def list_admins(self) -> list[dict]:
        docs = self._client.collection(ADMINS_COLLECTION).stream()
        return [doc.to_dict() async for doc in docs]

    async def set_admin(self, user_id: int, data: dict) -> None:
        await self._admin_ref(user_id).set(data)

    async def delete_admin(self, user_id: int) -> None:
        await self._admin_ref(user_id).delete()

    async def add_log(self, collection: str, data: dict) -> str:
        _, doc_ref = await self._client.collection(collection).add(data)
        return doc_ref.id

    async def list_logs(self, collection: str, limit: int = 500, since: datetime | None = None) -> list[dict]:
        query = self._client.collection(collection)
        if since is not None:
            # Filtering here instead of fetching everything and checking
            # `ts >= since` in Python matters: /stats used to pull up to
            # 2000 raw docs per collection (3 collections = up to 6000
            # reads) on every call just to throw most of them away.
            query = query.where(filter=firestore.FieldFilter("ts", ">=", since))
        query = query.order_by("ts", direction=firestore.Query.DESCENDING).limit(limit)
        return [{**doc.to_dict(), "id": doc.id} async for doc in query.stream()]

    async def get_log(self, collection: str, doc_id: str) -> dict | None:
        snap = await self._client.collection(collection).document(doc_id).get()
        return {**snap.to_dict(), "id": snap.id} if snap.exists else None

    async def update_log(self, collection: str, doc_id: str, patch: dict) -> None:
        await self._client.collection(collection).document(doc_id).update(patch)
