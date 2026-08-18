from app.repo.admins import AdminRepo
from tests.fakes import FakeStore


async def test_add_then_is_admin_and_is_owner():
    store = FakeStore()
    repo = AdminRepo(store)

    await repo.add(1, name="Owner", role="owner", added_by=1)
    await repo.add(2, name="Editor", role="editor", added_by=1)

    assert await repo.is_admin(1) is True
    assert await repo.is_owner(1) is True
    assert await repo.is_admin(2) is True
    assert await repo.is_owner(2) is False
    assert await repo.is_admin(3) is False


async def test_remove_invalidates_cache_immediately():
    store = FakeStore()
    repo = AdminRepo(store)
    await repo.add(1, name="Owner", role="owner", added_by=1)
    assert await repo.is_admin(1) is True

    await repo.remove(1)

    assert await repo.is_admin(1) is False


async def test_cache_respects_ttl(monkeypatch):
    store = FakeStore()
    repo = AdminRepo(store, ttl_seconds=1000)
    await repo.add(1, name="Owner", role="owner", added_by=1)
    await repo.is_admin(1)  # warms cache

    # mutate the store directly, bypassing the repo, to prove the cache is
    # actually being served rather than hitting the store every call.
    store._admins.pop(1)

    assert await repo.is_admin(1) is True

    monkeypatch.setattr("time.monotonic", lambda: 10_000_000)
    assert await repo.is_admin(1) is False
