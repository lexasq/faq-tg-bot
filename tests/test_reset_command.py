import pytest
from telegram.ext import ConversationHandler

from app.handlers import admin_crud
from app.models import Entry
from app.repo.admins import AdminRepo
from app.repo.entries import EntryCache, EntryRepo
from app.repo.logs import LogRepo
from app.services import Services
from tests.fakes import FakeStore
from tests.telegram_fakes import RecordingBot, make_context, make_update_for_message

OWNER_ID = 9001
EDITOR_ID = 9002
CHAT_ID = OWNER_ID


@pytest.fixture
async def rig():
    store = FakeStore()
    entry_repo = EntryRepo(store)
    admin_repo = AdminRepo(store)
    await admin_repo.add(OWNER_ID, name="Owner", role="owner", added_by=OWNER_ID)
    await admin_repo.add(EDITOR_ID, name="Editor", role="editor", added_by=OWNER_ID)
    for i in range(3):
        await entry_repo.save(Entry.create(title=f"Запис {i}", answer="a", updated_by=OWNER_ID), actor_id=OWNER_ID)
    entry_cache = EntryCache(entry_repo, store)
    await entry_cache.refresh(force=True)
    services = Services(
        settings=None, store=store, entry_repo=entry_repo, entry_cache=entry_cache,
        admin_repo=admin_repo, log_repo=LogRepo(store),
    )
    bot = RecordingBot()
    context = make_context({"services": services})
    return services, bot, context


def _msg(bot, text, user_id=OWNER_ID):
    return make_update_for_message(bot, chat_id=CHAT_ID, user_id=user_id, text=text)


async def test_editor_cannot_reset(rig):
    services, bot, context = rig
    state = await admin_crud.cmd_reset(_msg(bot, "/reset", user_id=EDITOR_ID), context)

    assert state == ConversationHandler.END
    assert bot.sent[-1]["text"] == admin_crud.texts.RESET_NOT_OWNER
    assert len(await services.entry_repo.list_all()) == 3  # untouched


async def test_owner_reset_requires_typed_confirmation(rig):
    services, bot, context = rig

    state = await admin_crud.cmd_reset(_msg(bot, "/reset"), context)
    assert state == admin_crud.RESET_CONFIRM
    assert "3" in bot.sent[-1]["text"]
    assert len(await services.entry_repo.list_all()) == 3  # not deleted yet

    state = await admin_crud.reset_confirm(_msg(bot, "please"), context)
    assert state == admin_crud.RESET_CONFIRM  # wrong word, stays open
    assert len(await services.entry_repo.list_all()) == 3

    state = await admin_crud.reset_confirm(_msg(bot, "RESET"), context)
    assert state == ConversationHandler.END
    assert await services.entry_repo.list_all() == []
    assert "3" in bot.sent[-1]["text"]


async def test_reset_with_no_entries_is_a_no_op(rig):
    services, bot, context = rig
    for e in await services.entry_repo.list_all():
        await services.entry_repo.delete(e.id)

    state = await admin_crud.cmd_reset(_msg(bot, "/reset"), context)

    assert state == ConversationHandler.END
    assert bot.sent[-1]["text"] == admin_crud.texts.RESET_EMPTY


async def test_reset_is_interruptible_via_conversation_fallback(rig):
    # same mechanism as the Категорія-button fix: /reset must be reachable
    # even if the owner is mid-way through some other unfinished flow
    services, bot, context = rig
    key = admin_crud.admin_conversation._get_key(_msg(bot, "/reset"))
    admin_crud.admin_conversation._conversations[key] = admin_crud.EDIT_ANSWER

    result = admin_crud.admin_conversation.check_update(_msg(bot, "/reset"))

    del admin_crud.admin_conversation._conversations[key]
    assert result is not None
