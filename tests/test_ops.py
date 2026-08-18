import asyncio
from datetime import datetime, timedelta

import pytest

from app.handlers import ops
from app.matching.regex_matcher import RegexMatcher
from app.models import Entry
from app.repo.admins import AdminRepo
from app.repo.entries import EntryCache, EntryRepo
from app.repo.logs import LogRepo
from app.services import Services
from tests.fakes import FakeStore
from tests.telegram_fakes import RecordingBot, make_context, make_update_for_message

ADMIN_ID = 6006


async def _flush():
    await asyncio.sleep(0)


@pytest.fixture
async def rig():
    store = FakeStore()
    entry_repo = EntryRepo(store)
    admin_repo = AdminRepo(store)
    await admin_repo.add(ADMIN_ID, name="Owner", role="owner", added_by=ADMIN_ID)
    entry = await entry_repo.save(
        Entry.create(title="Рахунок ДТЕК", answer="a", updated_by=ADMIN_ID, patterns=[r"дтек"]), actor_id=ADMIN_ID
    )
    entry_cache = EntryCache(entry_repo, store)
    await entry_cache.refresh(force=True)
    services = Services(
        settings=None,
        store=store,
        entry_repo=entry_repo,
        entry_cache=entry_cache,
        admin_repo=admin_repo,
        log_repo=LogRepo(store),
        matcher=RegexMatcher(entry_cache),
    )
    bot = RecordingBot()
    context = make_context({"services": services}, bot=bot)
    return services, bot, context, entry


def _msg(bot, text, args=None):
    return make_update_for_message(bot, chat_id=ADMIN_ID, user_id=ADMIN_ID, text=text)


async def test_stats_reports_replies_and_top_entries(rig):
    services, bot, context, entry = rig
    services.log_repo.log_match(chat_id=1, user_id=10, text="дтек?", entry_id=entry.id, score=0.9, action="replied")
    services.log_repo.log_match(chat_id=1, user_id=11, text="дтек??", entry_id=entry.id, score=0.9, action="replied")
    services.log_repo.log_miss(chat_id=1, user_id=12, text="хто голова", top_entry_id=None, top_score=0.2)
    services.log_repo.log_feedback(match_log_id=None, entry_id=entry.id, user_id=10, vote="down")
    await _flush()

    context.args = []
    await ops.cmd_stats(_msg(bot, "/stats"), context)

    text = bot.sent[-1]["text"]
    assert "Автовідповідей: 2" in text
    assert "Унікальних авторів запитань: 2" in text
    assert "Пропущено (без відповіді): 1" in text
    assert "Рахунок ДТЕК" in text


async def test_stats_period_filters_out_old_entries(rig):
    services, bot, context, entry = rig
    old_ts = datetime.utcnow() - timedelta(days=40)
    await services.store.add_log(
        "match_log", {"chat_id": 1, "user_id": 1, "text": "x", "entry_id": entry.id, "score": 0.9, "action": "replied", "ts": old_ts}
    )

    context.args = ["30d"]
    await ops.cmd_stats(_msg(bot, "/stats 30d"), context)
    assert "Даних ще немає" in bot.sent[-1]["text"]


async def test_review_empty_queue(rig):
    services, bot, context, entry = rig
    context.args = []
    await ops.cmd_review(_msg(bot, "/review"), context)
    assert bot.sent[-1]["text"] == ops.texts.REVIEW_EMPTY


async def test_review_lists_deduplicated_unhandled_misses(rig):
    services, bot, context, entry = rig
    services.log_repo.log_miss(chat_id=1, user_id=1, text="хто новий голова?", top_entry_id=None, top_score=0.1)
    services.log_repo.log_miss(chat_id=1, user_id=2, text="Хто новий голова???", top_entry_id=None, top_score=0.1)
    services.log_repo.log_miss(chat_id=1, user_id=3, text="інше запитання", top_entry_id=None, top_score=0.1)
    await _flush()

    await ops.cmd_review(_msg(bot, "/review"), context)
    text = bot.sent[-1]["text"]
    assert "1/2" in text  # deduplicated: "хто новий голова" variants collapse to 1


async def test_review_ignore_marks_handled_and_advances(rig):
    from tests.telegram_fakes import make_update_for_callback

    services, bot, context, entry = rig
    services.log_repo.log_miss(chat_id=1, user_id=1, text="перше питання", top_entry_id=None, top_score=0.1)
    await _flush()
    misses = await ops.reviewable_misses(services)
    doc_id = misses[0]["id"]

    update = make_update_for_callback(bot, chat_id=ADMIN_ID, user_id=ADMIN_ID, data=f"rvi:{doc_id}")
    await ops.cb_review_ignore(update, context)

    assert bot.edited[-1]["text"] == ops.texts.REVIEW_IGNORED
    assert await ops.reviewable_misses(services) == []


async def test_test_command_reports_top_matches_and_would_do(rig):
    services, bot, context, entry = rig
    context.args = ["який", "рахунок", "дтек?"]
    await ops.cmd_test(_msg(bot, "/test який рахунок дтек?"), context)

    debug_text = bot.sent[0]["text"]
    assert "Рахунок ДТЕК" in debug_text
    assert "У групі:" in debug_text
    assert "При згадці:" in debug_text


async def test_test_command_also_shows_the_actual_rendered_answer(rig):
    services, bot, context, entry = rig
    context.args = ["який", "рахунок", "дтек?"]
    await ops.cmd_test(_msg(bot, "/test який рахунок дтек?"), context)

    assert len(bot.sent) == 2
    preview = bot.sent[1]
    assert preview["text"].startswith(ops.texts.TEST_PREVIEW_HEADER)
    assert entry.answer in preview["text"]
    assert preview["kwargs"]["parse_mode"] == "HTML"


async def test_test_command_below_threshold_shows_no_preview(rig):
    services, bot, context, entry = rig
    context.args = ["зовсім", "нерелевантний", "текст"]
    await ops.cmd_test(_msg(bot, "/test зовсім нерелевантний текст"), context)

    assert len(bot.sent) == 1  # debug message only, no preview


async def test_test_command_no_args_prompts_usage(rig):
    services, bot, context, entry = rig
    context.args = []
    await ops.cmd_test(_msg(bot, "/test"), context)
    assert bot.sent[-1]["text"] == ops.texts.TEST_ASK_TEXT


async def test_health_replies_ok(rig):
    services, bot, context, entry = rig
    context.args = []
    await ops.cmd_health(_msg(bot, "/health"), context)
    assert bot.sent[-1]["text"] == ops.texts.HEALTH_OK


async def test_touch_liveness_file_writes_timestamp(tmp_path, monkeypatch):
    liveness_path = tmp_path / "liveness"
    monkeypatch.setattr(ops, "LIVENESS_FILE", str(liveness_path))

    await ops.touch_liveness_file(context=None)

    assert liveness_path.exists()
    assert float(liveness_path.read_text()) > 0
