import pytest
from telegram.ext import ConversationHandler

from app.handlers import admin_crud
from app.repo.admins import AdminRepo
from app.repo.entries import EntryCache, EntryRepo, short_id
from app.repo.logs import LogRepo
from app.services import Services
from tests.fakes import FakeStore
from tests.telegram_fakes import (
    RecordingBot,
    make_context,
    make_update_for_callback,
    make_update_for_group_message,
    make_update_for_message,
)

ADMIN_ID = 1001
CHAT_ID = ADMIN_ID  # DM: chat id == user id


@pytest.fixture
async def rig():
    store = FakeStore()
    entry_repo = EntryRepo(store)
    admin_repo = AdminRepo(store)
    services = Services(
        settings=None,
        store=store,
        entry_repo=entry_repo,
        entry_cache=EntryCache(entry_repo, store),
        admin_repo=admin_repo,
        log_repo=LogRepo(store),
    )
    await admin_repo.add(ADMIN_ID, name="Owner", role="owner", added_by=ADMIN_ID)
    bot = RecordingBot()
    context = make_context({"services": services})
    return services, bot, context


def _msg(bot, text, user_id=ADMIN_ID):
    return make_update_for_message(bot, chat_id=CHAT_ID, user_id=user_id, text=text)


def _cb(bot, data, user_id=ADMIN_ID):
    return make_update_for_callback(bot, chat_id=CHAT_ID, user_id=user_id, data=data)


async def test_full_add_flow_creates_entry(rig):
    services, bot, context = rig

    state = await admin_crud.cmd_add(_msg(bot, "/add"), context)
    assert state == admin_crud.ADD_TITLE
    assert bot.sent[-1]["text"] == admin_crud.texts.ADD_ASK_TITLE

    state = await admin_crud.add_title(_msg(bot, "Тестовий запис"), context)
    assert state == admin_crud.ADD_CATEGORY

    state = await admin_crud.add_category_chosen(_cb(bot, "addcat:new"), context)
    assert state == admin_crud.ADD_CATEGORY_NEW

    state = await admin_crud.add_category_new(_msg(bot, "Тестова категорія"), context)
    assert state == admin_crud.ADD_ANSWER
    assert context.user_data["add_category"] == "Тестова категорія"

    state = await admin_crud.add_answer_line(_msg(bot, "Рядок відповіді 1"), context)
    assert state == admin_crud.ADD_ANSWER
    state = await admin_crud.add_answer_line(_msg(bot, "Рядок відповіді 2"), context)
    assert state == admin_crud.ADD_ANSWER

    state = await admin_crud.add_answer_done(_msg(bot, "/done"), context)
    assert state == admin_crud.ADD_PATTERNS

    state = await admin_crud.add_patterns_choice(_cb(bot, "addpat:accept"), context)
    assert state == admin_crud.ADD_CONFIRM

    state = await admin_crud.add_confirm(_cb(bot, "addconf:yes"), context)
    assert state == ConversationHandler.END
    assert context.user_data == {}

    entries = await services.entry_repo.list_all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.title == "Тестовий запис"
    assert entry.category == "Тестова категорія"
    assert entry.answer == "Рядок відповіді 1\nРядок відповіді 2"
    assert entry.patterns  # auto-suggested patterns were accepted

    # entry card was sent as the final message
    assert "Тестовий запис" in bot.sent[-1]["text"]


async def test_cancel_mid_flow_creates_nothing(rig):
    services, bot, context = rig
    await admin_crud.cmd_add(_msg(bot, "/add"), context)
    await admin_crud.add_title(_msg(bot, "Незавершений"), context)

    state = await admin_crud.cmd_cancel(_msg(bot, "/cancel"), context)

    assert state == ConversationHandler.END
    assert context.user_data == {}
    assert await services.entry_repo.list_all() == []
    assert bot.sent[-1]["text"] == admin_crud.texts.CANCELLED


async def test_non_admin_is_silently_ignored(rig):
    services, bot, context = rig
    state = await admin_crud.cmd_add(_msg(bot, "/add", user_id=9999), context)
    assert state is None
    assert bot.sent == []


async def test_group_chat_is_ignored(rig):
    services, bot, context = rig
    update = make_update_for_group_message(bot, chat_id=-500, user_id=ADMIN_ID, text="/add")
    state = await admin_crud.cmd_add(update, context)
    assert state is None
    assert bot.sent == []


async def test_help_shows_admin_menu_for_admin(rig):
    services, bot, context = rig
    await admin_crud.cmd_help(_msg(bot, "/help"), context)
    assert bot.sent[-1]["text"] == admin_crud.texts.START_ADMIN_MENU


async def test_help_shows_non_admin_message_for_stranger(rig):
    services, bot, context = rig
    await admin_crud.cmd_help(_msg(bot, "/help", user_id=9999), context)
    assert bot.sent[-1]["text"] == admin_crud.texts.START_NON_ADMIN


async def test_help_is_ignored_in_groups(rig):
    services, bot, context = rig
    update = make_update_for_group_message(bot, chat_id=-500, user_id=ADMIN_ID, text="/help")
    await admin_crud.cmd_help(update, context)
    assert bot.sent == []


async def test_help_menu_only_lists_commands_that_actually_exist():
    # regression: START_ADMIN_MENU used to advertise /settings and
    # /admins, neither of which was ever implemented
    assert "/settings" not in admin_crud.texts.START_ADMIN_MENU
    assert "/admins" not in admin_crud.texts.START_ADMIN_MENU
    for cmd in ("/add", "/list", "/find", "/import", "/export", "/review", "/stats", "/test", "/faq", "/health", "/cancel", "/help", "/reset"):
        assert cmd in admin_crud.texts.START_ADMIN_MENU, f"{cmd} missing from help text"


async def test_toggle_enable_disable(rig):
    from app.models import Entry

    services, bot, context = rig
    entry = await services.entry_repo.save(
        Entry.create(title="Перемикач", answer="a", updated_by=ADMIN_ID), actor_id=ADMIN_ID
    )
    await services.entry_cache.refresh(force=True)
    token = short_id(entry.id)

    await admin_crud.cb_toggle_enabled(_cb(bot, f"ec:tog:{token}"), context)
    assert (await services.entry_repo.get(entry.id)).enabled is False

    await admin_crud.cb_toggle_enabled(_cb(bot, f"ec:tog:{token}"), context)
    assert (await services.entry_repo.get(entry.id)).enabled is True


async def test_toggle_visibility(rig):
    from app.models import Entry

    services, bot, context = rig
    entry = await services.entry_repo.save(
        Entry.create(title="Приватний", answer="секрет", updated_by=ADMIN_ID), actor_id=ADMIN_ID
    )
    await services.entry_cache.refresh(force=True)
    token = short_id(entry.id)
    assert entry.visibility == "public"

    await admin_crud.cb_toggle_visibility(_cb(bot, f"ec:vis:{token}"), context)
    assert (await services.entry_repo.get(entry.id)).visibility == "dm_only"
    assert "dm_only" in bot.answered_callbacks[-1]["text"]

    await admin_crud.cb_toggle_visibility(_cb(bot, f"ec:vis:{token}"), context)
    assert (await services.entry_repo.get(entry.id)).visibility == "public"


async def test_patterns_button_shows_current_patterns_before_asking_to_replace(rig):
    from app.models import Entry

    services, bot, context = rig
    entry = await services.entry_repo.save(
        Entry.create(title="З патернами", answer="a", updated_by=ADMIN_ID, patterns=["дтек", r"рахун\w*"]),
        actor_id=ADMIN_ID,
    )
    await services.entry_cache.refresh(force=True)
    token = short_id(entry.id)

    state = await admin_crud.edit_patterns_entry(_cb(bot, f"ecedit:pat:{token}"), context)

    assert state == admin_crud.EDIT_PATTERNS
    prompt = bot.sent[-1]["text"]
    assert "дтек" in prompt
    assert r"рахун\w*" in prompt
    assert "2" in prompt  # pattern count


async def test_patterns_button_on_entry_with_no_patterns_shows_empty_placeholder(rig):
    from app.models import Entry

    services, bot, context = rig
    entry = await services.entry_repo.save(
        Entry.create(title="Без патернів", answer="a", updated_by=ADMIN_ID), actor_id=ADMIN_ID
    )
    await services.entry_cache.refresh(force=True)
    token = short_id(entry.id)

    await admin_crud.edit_patterns_entry(_cb(bot, f"ecedit:pat:{token}"), context)

    assert admin_crud.texts.PATTERNS_EMPTY in bot.sent[-1]["text"]


async def test_delete_is_soft_then_hard(rig):
    from app.models import Entry

    services, bot, context = rig
    entry = await services.entry_repo.save(
        Entry.create(title="Видалити мене", answer="a", updated_by=ADMIN_ID), actor_id=ADMIN_ID
    )
    await services.entry_cache.refresh(force=True)
    token = short_id(entry.id)

    await admin_crud.cb_delete(_cb(bot, f"ec:del:{token}"), context)
    assert (await services.entry_repo.get(entry.id)).enabled is False
    assert bot.edited[-1]["text"] == admin_crud.texts.DELETE_SOFT_DONE

    await admin_crud.cb_delete(_cb(bot, f"ec:del:{token}"), context)
    assert bot.edited[-1]["text"] == admin_crud.texts.DELETE_HARD_CONFIRM

    await admin_crud.cb_delete_confirm(_cb(bot, f"ec:delc:{token}"), context)
    assert await services.entry_repo.get(entry.id) is None


async def test_list_and_find(rig):
    from app.models import Entry

    services, bot, context = rig
    await services.entry_repo.save(
        Entry.create(title="Рахунок ДТЕК", answer="платіжка", updated_by=ADMIN_ID, category="Оплата"),
        actor_id=ADMIN_ID,
    )
    await services.entry_cache.refresh(force=True)

    await admin_crud.cmd_list(_msg(bot, "/list"), context)
    assert "Рахунок ДТЕК" not in bot.sent[-1]["text"]  # header only, title is a button label

    context.args = ["ДТЕК"]
    await admin_crud.cmd_find(_msg(bot, "/find ДТЕК"), context)
    assert admin_crud.texts.FIND_RESULTS_HEADER.format(count=1) == bot.sent[-1]["text"]

    context.args = ["Немаєтакого"]
    await admin_crud.cmd_find(_msg(bot, "/find x"), context)
    assert bot.sent[-1]["text"] == admin_crud.texts.FIND_EMPTY
