import asyncio

from app.handlers import feedback
from app.models import Entry
from app.repo.admins import AdminRepo
from app.repo.entries import EntryCache, EntryRepo, short_id
from app.repo.logs import FEEDBACK_LOG, LogRepo
from app.services import Services
from tests.fakes import FakeStore
from tests.telegram_fakes import RecordingBot, make_context, make_update_for_callback


async def _flush():
    await asyncio.sleep(0)


async def test_feedback_records_vote_and_edits_keyboard_away():
    store = FakeStore()
    entry_repo = EntryRepo(store)
    entry = await entry_repo.save(
        Entry.create(title="Тест", answer="a", updated_by=1, patterns=["тест"]), actor_id=1
    )
    entry_cache = EntryCache(entry_repo, store)
    await entry_cache.refresh(force=True)
    services = Services(
        settings=None,
        store=store,
        entry_repo=entry_repo,
        entry_cache=entry_cache,
        admin_repo=AdminRepo(store),
        log_repo=LogRepo(store),
    )
    bot = RecordingBot()
    context = make_context({"services": services}, bot=bot)

    token = short_id(entry.id)
    update = make_update_for_callback(bot, chat_id=1, user_id=7, data=f"fb:up:{token}")

    await feedback.handle_feedback(update, context)
    await _flush()

    logs = await store.list_logs(FEEDBACK_LOG)
    assert len(logs) == 1
    assert logs[0]["entry_id"] == entry.id
    assert logs[0]["vote"] == "up"
    assert logs[0]["user_id"] == 7

    assert len(bot.edited) == 1
    keyboard = bot.edited[0]["kwargs"]["reply_markup"]
    button_texts = [b.text for row in keyboard.inline_keyboard for b in row]
    assert "👍" not in button_texts
    assert "👎" not in button_texts
