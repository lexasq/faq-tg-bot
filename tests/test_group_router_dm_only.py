import asyncio

import pytest
from telegram.error import Forbidden

from app.handlers import group
from app.matching.regex_matcher import RegexMatcher
from app.models import Entry
from app.repo.admins import AdminRepo
from app.repo.entries import EntryCache, EntryRepo
from app.repo.logs import LogRepo
from app.services import Services
from tests.fakes import FakeStore
from tests.telegram_fakes import RecordingBot, make_context, make_update_for_group_message, set_bot_identity

CHAT_ID = -4004
USER_ID = 55


async def _flush():
    await asyncio.sleep(0)


@pytest.fixture
async def rig():
    store = FakeStore()
    entry_repo = EntryRepo(store)

    leaf_a = await entry_repo.save(
        Entry.create(title="Рахунок ОСББ", answer="IBAN A", updated_by=1, patterns=[r"осбб.{0,10}рахунок|рахунок.{0,10}осбб"]),
        actor_id=1,
    )
    leaf_b = await entry_repo.save(
        Entry.create(title="Рахунок Тепло", answer="IBAN B", updated_by=1, patterns=[r"тепло.{0,10}рахунок|рахунок.{0,10}тепло"]),
        actor_id=1,
    )
    router = await entry_repo.save(
        Entry.create(
            title="Куди платити",
            answer="Оберіть варіант оплати:",
            updated_by=1,
            type="router",
            patterns=[r"куди.{0,10}(плат|оплач)"],
            children=[leaf_a.id, leaf_b.id],
        ),
        actor_id=1,
    )
    dm_only = await entry_repo.save(
        Entry.create(
            title="Пошти власників", answer="секретний список email", updated_by=1,
            visibility="dm_only", patterns=[r"пошт\w*.{0,10}власник"],
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
    return services, bot, context, {"router": router, "leaf_a": leaf_a, "leaf_b": leaf_b, "dm_only": dm_only}


def _msg(bot, text, **kwargs):
    return make_update_for_group_message(bot, chat_id=CHAT_ID, user_id=USER_ID, text=text, **kwargs)


async def test_underspecified_question_gets_the_router_with_child_buttons(rig):
    services, bot, context, entries = rig
    await group.handle_group_message(_msg(bot, "куди платити за комуналку?"), context)

    assert len(bot.sent) == 1
    sent = bot.sent[0]
    assert "Оберіть варіант оплати" in sent["text"]
    labels = [b.text for row in sent["kwargs"]["reply_markup"].inline_keyboard for b in row]
    assert "Рахунок ОСББ" in labels
    assert "Рахунок Тепло" in labels
    # a router isn't something you thumbs-up
    assert "👍" not in labels


async def test_specific_leaf_question_bypasses_the_router(rig):
    services, bot, context, entries = rig
    await group.handle_group_message(_msg(bot, "який рахунок осбб для оплати?"), context)

    assert len(bot.sent) == 1
    assert "IBAN A" in bot.sent[0]["text"]


async def test_dm_only_match_posts_notice_publicly_and_dms_the_answer(rig):
    services, bot, context, entries = rig
    await group.handle_group_message(_msg(bot, "де список пошт власників?"), context)

    assert len(bot.sent) == 2
    public_notice = [m for m in bot.sent if m["chat_id"] == CHAT_ID]
    dm = [m for m in bot.sent if m["chat_id"] == USER_ID]
    assert len(public_notice) == 1
    assert public_notice[0]["text"] == group.texts.SENT_TO_DM
    assert len(dm) == 1
    assert "секретний список email" in dm[0]["text"]


async def test_dm_only_forbidden_falls_back_to_deep_link_button(rig):
    services, bot, context, entries = rig

    class ForbiddenOnDM(RecordingBot):
        async def send_message(self, chat_id, text, **kwargs):
            if chat_id == USER_ID:
                raise Forbidden("Forbidden: bot was blocked by the user")
            return await super().send_message(chat_id, text, **kwargs)

    forbidding_bot = ForbiddenOnDM()
    set_bot_identity(forbidding_bot)
    context.bot = forbidding_bot

    await group.handle_group_message(_msg(forbidding_bot, "де список пошт власників?"), context)

    assert len(forbidding_bot.edited) == 1
    edited = forbidding_bot.edited[0]
    assert edited["text"] == group.texts.SENT_TO_DM_FAILED
    keyboard = edited["kwargs"]["reply_markup"]
    assert keyboard.inline_keyboard[0][0].url.startswith("https://t.me/")
