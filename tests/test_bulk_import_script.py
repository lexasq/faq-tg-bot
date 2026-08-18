from pathlib import Path

from scripts.bulk_import import bulk_import, extract_strict_block
from app.repo.entries import EntryRepo
from tests.fakes import FakeStore

SEED_PATH = Path(__file__).parent / "fixtures" / "faq_example.md"
ACTOR_ID = 1


async def test_bulk_import_loads_example_seed_content():
    store = FakeStore()
    entry_repo = EntryRepo(store)
    content = extract_strict_block(SEED_PATH.read_text(encoding="utf-8"))

    await bulk_import(entry_repo, content, ACTOR_ID)

    entries = await entry_repo.list_all()
    assert len(entries) == 13
    router = next(e for e in entries if e.type == "router")
    assert len(router.children) == 5


async def test_bulk_import_is_idempotent_on_rerun():
    store = FakeStore()
    entry_repo = EntryRepo(store)
    content = extract_strict_block(SEED_PATH.read_text(encoding="utf-8"))

    await bulk_import(entry_repo, content, ACTOR_ID)
    entries_before = await entry_repo.list_all()
    versions_before = {e.id: e.version for e in entries_before}

    await bulk_import(entry_repo, content, ACTOR_ID)
    entries_after = await entry_repo.list_all()
    versions_after = {e.id: e.version for e in entries_after}

    assert versions_before == versions_after  # unchanged content -> no new revisions


async def test_extract_strict_block_handles_bare_content():
    bare = "Q: Тест\nA:\nВідповідь"
    assert extract_strict_block(bare) == bare
