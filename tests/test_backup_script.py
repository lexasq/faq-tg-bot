import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.backup import KEEP_LAST, run_backup
from app.models import Entry
from app.repo.entries import EntryRepo
from tests.fakes import FakeStore


async def test_run_backup_writes_strict_format_export(tmp_path):
    store = FakeStore()
    entry_repo = EntryRepo(store)
    await entry_repo.save(Entry.create(title="Тест", answer="Відповідь", updated_by=1), actor_id=1)

    out_path = await run_backup(entry_repo, tmp_path)

    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert content.startswith("Q: Тест")
    assert "Відповідь" in content


async def test_run_backup_prunes_to_last_14(tmp_path):
    store = FakeStore()
    entry_repo = EntryRepo(store)

    for i in range(KEEP_LAST + 5):
        (tmp_path / f"faq_backup_2020010{i:02d}_000000_000000.md").write_text("old", encoding="utf-8")

    await run_backup(entry_repo, tmp_path)

    remaining = sorted(tmp_path.glob("faq_backup_*.md"))
    assert len(remaining) == KEEP_LAST
