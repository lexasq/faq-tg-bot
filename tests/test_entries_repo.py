from app.models import Entry
from app.repo.entries import EntryCache, EntryRepo, short_id
from tests.fakes import FakeStore

ACTOR = 111


def make_entry(title="Тест", answer="Відповідь", patterns=None) -> Entry:
    return Entry.create(title=title, answer=answer, updated_by=ACTOR, patterns=patterns or [])


async def test_save_new_entry_sets_version_1_and_no_revision():
    store = FakeStore()
    repo = EntryRepo(store)

    saved = await repo.save(make_entry(), actor_id=ACTOR)

    assert saved.version == 1
    assert await repo.revisions(saved.id) == []
    assert (await store.get_config())["entries_version"] == 1


async def test_save_existing_entry_bumps_version_and_snapshots_previous():
    store = FakeStore()
    repo = EntryRepo(store)

    first = await repo.save(make_entry(answer="v1"), actor_id=ACTOR)
    updated = first.model_copy(update={"answer": "v2"})
    second = await repo.save(updated, actor_id=ACTOR)

    assert second.version == 2
    assert second.answer == "v2"

    revisions = await repo.revisions(first.id)
    assert len(revisions) == 1
    assert revisions[0]["answer"] == "v1"
    assert revisions[0]["version"] == 1

    assert (await store.get_config())["entries_version"] == 2


async def test_delete_bumps_entries_version():
    store = FakeStore()
    repo = EntryRepo(store)
    entry = await repo.save(make_entry(), actor_id=ACTOR)

    await repo.delete(entry.id)

    assert await repo.get(entry.id) is None
    assert (await store.get_config())["entries_version"] == 2


async def test_set_enabled_soft_disables():
    store = FakeStore()
    repo = EntryRepo(store)
    entry = await repo.save(make_entry(), actor_id=ACTOR)

    disabled = await repo.set_enabled(entry.id, False, actor_id=ACTOR)

    assert disabled.enabled is False
    assert (await repo.get(entry.id)).enabled is False


async def test_set_visibility_switches_to_dm_only_and_back():
    store = FakeStore()
    repo = EntryRepo(store)
    entry = await repo.save(make_entry(), actor_id=ACTOR)
    assert entry.visibility == "public"

    dm_only = await repo.set_visibility(entry.id, "dm_only", actor_id=ACTOR)
    assert dm_only.visibility == "dm_only"
    assert (await repo.get(entry.id)).visibility == "dm_only"

    public_again = await repo.set_visibility(entry.id, "public", actor_id=ACTOR)
    assert public_again.visibility == "public"


async def test_set_visibility_on_missing_entry_returns_none():
    store = FakeStore()
    repo = EntryRepo(store)
    assert await repo.set_visibility("does-not-exist", "dm_only", actor_id=ACTOR) is None


async def test_cache_loads_entries_and_only_refetches_on_version_change():
    store = FakeStore()
    repo = EntryRepo(store)
    entry = await repo.save(make_entry(patterns=[r"тест\w*"]), actor_id=ACTOR)

    cache = EntryCache(repo, store)
    await cache.refresh(force=True)

    assert cache.get(entry.id) is not None
    assert len(cache.compiled_patterns(entry.id)) == 1

    changed = await cache.refresh()
    assert changed is False

    await repo.save(make_entry(title="Інший", answer="інша"), actor_id=ACTOR)
    changed = await cache.refresh()
    assert changed is True
    assert len(cache.get_all_enabled()) == 2


async def test_cache_skips_malformed_regex_without_crashing():
    store = FakeStore()
    repo = EntryRepo(store)
    entry = await repo.save(make_entry(patterns=["добр(", r"добр\w*"]), actor_id=ACTOR)

    cache = EntryCache(repo, store)
    await cache.refresh(force=True)

    assert len(cache.compiled_patterns(entry.id)) == 1


async def test_cache_get_all_enabled_excludes_disabled():
    store = FakeStore()
    repo = EntryRepo(store)
    entry = await repo.save(make_entry(), actor_id=ACTOR)
    await repo.set_enabled(entry.id, False, actor_id=ACTOR)

    cache = EntryCache(repo, store)
    await cache.refresh(force=True)

    assert cache.get_all_enabled() == []
    assert cache.get(entry.id) is not None


async def test_short_id_round_trips_through_cache():
    store = FakeStore()
    repo = EntryRepo(store)
    entry = await repo.save(make_entry(title="Довгий заголовок з багатьма словами тест"), actor_id=ACTOR)

    cache = EntryCache(repo, store)
    await cache.refresh(force=True)

    token = short_id(entry.id)
    assert len(token.encode()) < 20
    assert cache.resolve_short(token) == entry.id
    assert cache.resolve_short("doesnotexist") is None
