import asyncio

import pytest
from telegram import MessageEntity
from telegram.constants import MessageEntityType

from app.handlers import group
from app.matching.regex_matcher import RegexMatcher
from app.models import Entry
from app.repo.admins import AdminRepo
from app.repo.entries import EntryCache, EntryRepo
from app.repo.logs import MATCH_LOG, MISS_LOG, LogRepo
from app.services import Services
from tests.fakes import FakeStore
from tests.telegram_fakes import (
    RecordingBot,
    make_context,
    make_update_for_group_message,
    set_bot_identity,
)

CHAT_ID = -1001
USER_ID = 42
DTEK_TITLE = "Рахунок ДТЕК"


async def _flush():
    await asyncio.sleep(0)


@pytest.fixture
async def rig():
    store = FakeStore()
    entry_repo = EntryRepo(store)
    await entry_repo.save(
        Entry.create(
            title=DTEK_TITLE,
            answer="Оплата за електроенергію: ...",
            updated_by=1,
            patterns=[r"дтек"],
        ),
        actor_id=1,
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
        matcher=RegexMatcher(entry_cache),
    )
    bot = RecordingBot()
    set_bot_identity(bot)
    context = make_context({"services": services}, bot=bot)
    return services, bot, context


def _msg(bot, text, **kwargs):
    return make_update_for_group_message(bot, chat_id=CHAT_ID, user_id=USER_ID, text=text, **kwargs)


async def test_confident_question_triggers_autoreply_with_feedback_buttons(rig):
    services, bot, context = rig
    await group.handle_group_message(_msg(bot, "який зараз рахунок у дтек?"), context)

    assert len(bot.sent) == 1
    sent = bot.sent[0]
    assert "Рахунок ДТЕК" in sent["text"]
    keyboard = sent["kwargs"]["reply_markup"]
    button_texts = [b.text for row in keyboard.inline_keyboard for b in row]
    assert "👍" in button_texts and "👎" in button_texts

    await _flush()
    logs = await services.store.list_logs(MATCH_LOG)
    assert len(logs) == 1
    assert logs[0]["action"] == "replied"


async def test_keyword_without_question_marker_stays_silent_but_logs_miss(rig):
    services, bot, context = rig
    await group.handle_group_message(_msg(bot, "дтек знову вимкнув світло"), context)

    assert bot.sent == []
    await _flush()
    assert len(await services.store.list_logs(MISS_LOG)) == 1


async def test_below_suggest_threshold_and_no_question_marker_logs_nothing(rig):
    services, bot, context = rig
    await group.handle_group_message(_msg(bot, "просто балачки без ключових слів тут"), context)

    assert bot.sent == []
    await _flush()
    assert await services.store.list_logs(MATCH_LOG) == []
    assert await services.store.list_logs(MISS_LOG) == []


async def test_mention_below_threshold_replies_not_found(rig):
    services, bot, context = rig
    entities = [MessageEntity(type=MessageEntityType.MENTION, offset=0, length=len("@test_faq_bot"))]
    text = "@test_faq_bot привіт, як справи?"
    await group.handle_group_message(_msg(bot, text, entities=entities), context)

    assert len(bot.sent) == 1
    assert bot.sent[0]["text"] == group.texts.NOT_FOUND_ON_MENTION
    await _flush()
    miss_logs = await services.store.list_logs(MISS_LOG)
    assert len(miss_logs) == 1
    assert miss_logs[0]["direct_ask"] is True


async def test_mention_at_suggest_threshold_gets_an_answer(rig):
    services, bot, context = rig
    entities = [MessageEntity(type=MessageEntityType.MENTION, offset=0, length=len("@test_faq_bot"))]
    text = "@test_faq_bot дтек"
    await group.handle_group_message(_msg(bot, text, entities=entities), context)

    assert len(bot.sent) == 1
    assert "Рахунок ДТЕК" in bot.sent[0]["text"]


async def test_reply_to_bot_is_treated_as_mention(rig):
    from tests.telegram_fakes import make_message

    services, bot, context = rig
    bot_reply_target = make_message(bot, chat_id=CHAT_ID, user_id=999, text="previous bot message")
    await group.handle_group_message(_msg(bot, "дтек", reply_to_message=bot_reply_target), context)

    assert len(bot.sent) == 1
    assert "Рахунок ДТЕК" in bot.sent[0]["text"]


async def test_cooldown_suppresses_repeat_autoreply(rig):
    services, bot, context = rig
    await group.handle_group_message(_msg(bot, "дтек?", message_id=1), context)
    await group.handle_group_message(_msg(bot, "дтек?", message_id=2), context)

    assert len(bot.sent) == 1


async def test_hourly_cap_suppresses_after_five_replies(rig):
    services, bot, context = rig
    entry_repo = services.entry_repo
    # give each message a distinct matching entry so cooldown-per-entry
    # doesn't mask the hourly cap
    for i in range(6):
        await entry_repo.save(
            Entry.create(title=f"Запис {i}", answer=f"a{i}", updated_by=1, patterns=[f"унікпат{i}"]),
            actor_id=1,
        )
    await services.entry_cache.refresh(force=True)

    for i in range(6):
        await group.handle_group_message(_msg(bot, f"унікпат{i}?", message_id=100 + i), context)

    assert len(bot.sent) == group._DEFAULT_HOURLY_CAP


async def test_ignores_edited_messages(rig):
    services, bot, context = rig
    from datetime import datetime

    edited = _msg(bot, "дтек?", edit_date=datetime.utcnow())
    await group.handle_group_message(edited, context)
    assert bot.sent == []


async def test_ignores_bot_senders(rig):
    services, bot, context = rig
    bot_sender_update = _msg(bot, "дтек?", user_is_bot=True)
    await group.handle_group_message(bot_sender_update, context)
    assert bot.sent == []


async def test_ignores_commands_and_short_messages(rig):
    services, bot, context = rig
    await group.handle_group_message(_msg(bot, "/dtek"), context)
    assert bot.sent == []

    await group.handle_group_message(_msg(bot, "ок"), context)
    assert bot.sent == []


async def test_autoreply_disabled_in_config_is_silent(rig):
    services, bot, context = rig
    await services.store.update_config({"autoreply_enabled": False})
    await services.entry_cache.refresh(force=True)

    await group.handle_group_message(_msg(bot, "дтек?"), context)
    assert bot.sent == []


async def test_chat_id_allowlist_filters_other_chats(rig):
    services, bot, context = rig
    await services.store.update_config({"chat_ids": [CHAT_ID + 1]})
    await services.entry_cache.refresh(force=True)

    await group.handle_group_message(_msg(bot, "дтек?"), context)
    assert bot.sent == []
