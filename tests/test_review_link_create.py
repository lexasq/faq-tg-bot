import asyncio

import pytest
from telegram.ext import ConversationHandler

from app.handlers import admin_crud, ops
from app.models import Entry
from app.repo.admins import AdminRepo
from app.repo.entries import EntryCache, EntryRepo, short_id
from app.repo.logs import LogRepo
from app.services import Services
from tests.fakes import FakeStore
from tests.telegram_fakes import RecordingBot, make_context, make_update_for_callback, make_update_for_message

ADMIN_ID = 7007


async def _flush():
    await asyncio.sleep(0)


@pytest.fixture
async def rig():
    store = FakeStore()
    entry_repo = EntryRepo(store)
    admin_repo = AdminRepo(store)
    await admin_repo.add(ADMIN_ID, name="Owner", role="owner", added_by=ADMIN_ID)
    existing = await entry_repo.save(
        Entry.create(title="Бухгалтерія ОСББ", answer="графік тут", updated_by=ADMIN_ID, patterns=[r"бухгалтер"]),
        actor_id=ADMIN_ID,
    )
    entry_cache = EntryCache(entry_repo, store)
    await entry_cache.refresh(force=True)
    services = Services(
        settings=None, store=store, entry_repo=entry_repo, entry_cache=entry_cache,
        admin_repo=admin_repo, log_repo=LogRepo(store),
    )
    bot = RecordingBot()
    context = make_context({"services": services}, bot=bot)
    return services, bot, context, existing


def _msg(bot, text):
    return make_update_for_message(bot, chat_id=ADMIN_ID, user_id=ADMIN_ID, text=text)


def _cb(bot, data):
    return make_update_for_callback(bot, chat_id=ADMIN_ID, user_id=ADMIN_ID, data=data)


async def test_review_create_prefills_add_flow_with_miss_text(rig):
    services, bot, context, existing = rig
    services.log_repo.log_miss(chat_id=1, user_id=1, text="коли приймає бухгалтерія", top_entry_id=None, top_score=0.3)
    await _flush()
    misses = await ops.reviewable_misses(services)
    doc_id = misses[0]["id"]

    state = await admin_crud.review_create_entry(_cb(bot, f"rvc:{doc_id}"), context)
    assert state == admin_crud.ADD_CATEGORY
    assert context.user_data["add_title"] == "коли приймає бухгалтерія"
    assert context.user_data["add_extra_pattern"] == "коли приймає бухгалтерія"

    # the miss is marked handled immediately so it doesn't linger in the queue
    assert await ops.reviewable_misses(services) == []

    # finish the flow: category -> answer -> confirm patterns include the miss text
    state = await admin_crud.add_category_chosen(_cb(bot, "addcat:new"), context)
    assert state == admin_crud.ADD_CATEGORY_NEW
    state = await admin_crud.add_category_new(_msg(bot, "Загальне"), context)
    assert state == admin_crud.ADD_ANSWER
    state = await admin_crud.add_answer_line(_msg(bot, "Відповідь"), context)
    state = await admin_crud.add_answer_done(_msg(bot, "/done"), context)
    assert state == admin_crud.ADD_PATTERNS

    suggested_text = bot.sent[-1]["text"]
    import re as _re

    assert _re.escape("коли приймає бухгалтерія") in suggested_text


async def test_review_link_appends_pattern_to_existing_entry(rig):
    services, bot, context, existing = rig
    services.log_repo.log_miss(chat_id=1, user_id=1, text="де взяти довідку про склад сім'ї", top_entry_id=None, top_score=0.1)
    await _flush()
    misses = await ops.reviewable_misses(services)
    doc_id = misses[0]["id"]

    state = await admin_crud.review_link_entry(_cb(bot, f"rvl:{doc_id}"), context)
    assert state == admin_crud.REVIEW_LINK_SEARCH
    assert context.user_data["review_link_miss_id"] == doc_id

    state = await admin_crud.review_link_search(_msg(bot, "бухгалтерія"), context)
    assert state == admin_crud.REVIEW_LINK_SEARCH
    keyboard = bot.sent[-1]["kwargs"]["reply_markup"]
    token = keyboard.inline_keyboard[0][0].callback_data.split(":", 1)[1]
    assert token == short_id(existing.id)

    state = await admin_crud.review_link_pick(_cb(bot, f"rvlpick:{token}"), context)
    assert state == ConversationHandler.END

    updated = await services.entry_repo.get(existing.id)
    assert any("довідку" in p or "довідк" in p for p in updated.patterns)
    assert len(updated.patterns) == 2  # original + the new one
    assert await ops.reviewable_misses(services) == []
