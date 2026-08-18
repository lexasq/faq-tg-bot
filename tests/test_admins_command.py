import pytest

from app.handlers import admin_crud
from app.repo.admins import AdminRepo
from app.repo.entries import EntryCache, EntryRepo
from app.repo.logs import LogRepo
from app.services import Services
from tests.fakes import FakeStore
from tests.telegram_fakes import RecordingBot, make_context, make_update_for_message

OWNER_ID = 9001
EDITOR_ID = 9002
STRANGER_ID = 9999
CHAT_ID = OWNER_ID


@pytest.fixture
async def rig():
    store = FakeStore()
    entry_repo = EntryRepo(store)
    admin_repo = AdminRepo(store)
    await admin_repo.add(OWNER_ID, name="Owner", role="owner", added_by=OWNER_ID)
    await admin_repo.add(EDITOR_ID, name="Editor", role="editor", added_by=OWNER_ID)
    entry_cache = EntryCache(entry_repo, store)
    await entry_cache.refresh(force=True)
    services = Services(
        settings=None, store=store, entry_repo=entry_repo, entry_cache=entry_cache,
        admin_repo=admin_repo, log_repo=LogRepo(store),
    )
    bot = RecordingBot()
    return services, bot


async def _ctx(services, args=None):
    context = make_context({"services": services}, args=args)
    return context


async def test_owner_lists_admins(rig):
    services, bot = rig
    context = await _ctx(services)
    update = make_update_for_message(bot, chat_id=CHAT_ID, user_id=OWNER_ID, text="/admins")

    await admin_crud.cmd_admins(update, context)

    text = bot.sent[-1]["text"]
    assert "2" in text
    assert "Owner" in text
    assert "Editor" in text
    assert str(OWNER_ID) in text
    assert str(EDITOR_ID) in text


async def test_editor_can_list_but_not_add(rig):
    services, bot = rig
    context = await _ctx(services, args=["add", "12345", "New", "Guy"])
    update = make_update_for_message(bot, chat_id=CHAT_ID, user_id=EDITOR_ID, text="/admins add 12345 New Guy")

    await admin_crud.cmd_admins(update, context)

    assert bot.sent[-1]["text"] == admin_crud.texts.ADMINS_NOT_OWNER
    assert await services.admin_repo.get(12345) is None


async def test_stranger_is_silently_ignored(rig):
    services, bot = rig
    context = await _ctx(services)
    update = make_update_for_message(bot, chat_id=CHAT_ID, user_id=STRANGER_ID, text="/admins")

    await admin_crud.cmd_admins(update, context)

    assert bot.sent == []


async def test_owner_adds_new_editor(rig):
    services, bot = rig
    context = await _ctx(services, args=["add", "12345", "New", "Guy"])
    update = make_update_for_message(bot, chat_id=CHAT_ID, user_id=OWNER_ID, text="/admins add 12345 New Guy")

    await admin_crud.cmd_admins(update, context)

    added = await services.admin_repo.get(12345)
    assert added is not None
    assert added.name == "New Guy"
    assert added.role == "editor"
    assert added.added_by == OWNER_ID
    assert "New Guy" in bot.sent[-1]["text"]
    assert "12345" in bot.sent[-1]["text"]


async def test_add_rejects_non_numeric_user_id(rig):
    services, bot = rig
    context = await _ctx(services, args=["add", "not-a-number", "Name"])
    update = make_update_for_message(bot, chat_id=CHAT_ID, user_id=OWNER_ID, text="/admins add not-a-number Name")

    await admin_crud.cmd_admins(update, context)

    assert bot.sent[-1]["text"] == admin_crud.texts.ADMIN_ID_NOT_A_NUMBER


async def test_add_rejects_missing_name(rig):
    services, bot = rig
    context = await _ctx(services, args=["add", "12345"])
    update = make_update_for_message(bot, chat_id=CHAT_ID, user_id=OWNER_ID, text="/admins add 12345")

    await admin_crud.cmd_admins(update, context)

    assert bot.sent[-1]["text"] == admin_crud.texts.ADMIN_ADD_USAGE


async def test_add_rejects_duplicate_user_id(rig):
    services, bot = rig
    context = await _ctx(services, args=["add", str(EDITOR_ID), "Someone", "Else"])
    update = make_update_for_message(bot, chat_id=CHAT_ID, user_id=OWNER_ID, text="/admins add ...")

    await admin_crud.cmd_admins(update, context)

    assert "Editor" in bot.sent[-1]["text"]  # reports the existing admin's name
    admin = await services.admin_repo.get(EDITOR_ID)
    assert admin.name == "Editor"  # untouched


async def test_owner_removes_editor(rig):
    services, bot = rig
    context = await _ctx(services, args=["remove", str(EDITOR_ID)])
    update = make_update_for_message(bot, chat_id=CHAT_ID, user_id=OWNER_ID, text="/admins remove ...")

    await admin_crud.cmd_admins(update, context)

    assert await services.admin_repo.get(EDITOR_ID) is None
    assert "Editor" in bot.sent[-1]["text"]


async def test_remove_unknown_user_id(rig):
    services, bot = rig
    context = await _ctx(services, args=["remove", "424242"])
    update = make_update_for_message(bot, chat_id=CHAT_ID, user_id=OWNER_ID, text="/admins remove 424242")

    await admin_crud.cmd_admins(update, context)

    assert bot.sent[-1]["text"] == admin_crud.texts.ADMIN_NOT_FOUND


async def test_cannot_remove_the_last_owner(rig):
    services, bot = rig
    context = await _ctx(services, args=["remove", str(OWNER_ID)])
    update = make_update_for_message(bot, chat_id=CHAT_ID, user_id=OWNER_ID, text="/admins remove ...")

    await admin_crud.cmd_admins(update, context)

    assert bot.sent[-1]["text"] == admin_crud.texts.ADMIN_CANT_REMOVE_LAST_OWNER
    assert await services.admin_repo.get(OWNER_ID) is not None


async def test_removing_one_of_two_owners_is_allowed(rig):
    services, bot = rig
    await services.admin_repo.add(7777, name="Co-owner", role="owner", added_by=OWNER_ID)
    context = await _ctx(services, args=["remove", str(OWNER_ID)])
    update = make_update_for_message(bot, chat_id=CHAT_ID, user_id=OWNER_ID, text="/admins remove ...")

    await admin_crud.cmd_admins(update, context)

    assert await services.admin_repo.get(OWNER_ID) is None
    assert await services.admin_repo.get(7777) is not None


async def test_editor_cannot_remove(rig):
    services, bot = rig
    context = await _ctx(services, args=["remove", str(EDITOR_ID)])
    update = make_update_for_message(bot, chat_id=CHAT_ID, user_id=EDITOR_ID, text="/admins remove ...")

    await admin_crud.cmd_admins(update, context)

    assert bot.sent[-1]["text"] == admin_crud.texts.ADMINS_NOT_OWNER
    assert await services.admin_repo.get(EDITOR_ID) is not None


async def test_unknown_subcommand_shows_usage(rig):
    services, bot = rig
    context = await _ctx(services, args=["frobnicate"])
    update = make_update_for_message(bot, chat_id=CHAT_ID, user_id=OWNER_ID, text="/admins frobnicate")

    await admin_crud.cmd_admins(update, context)

    assert bot.sent[-1]["text"] == admin_crud.texts.ADMINS_USAGE


async def test_group_chat_is_ignored(rig):
    from tests.telegram_fakes import make_update_for_group_message

    services, bot = rig
    context = await _ctx(services)
    update = make_update_for_group_message(bot, chat_id=-500, user_id=OWNER_ID, text="/admins")

    await admin_crud.cmd_admins(update, context)

    assert bot.sent == []
