import pytest

from app.handlers import menu
from app.models import Entry
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

ADMIN_ID = 3003
GROUP_CHAT_ID = -3003


@pytest.fixture
async def rig():
    store = FakeStore()
    entry_repo = EntryRepo(store)

    router = await entry_repo.save(
        Entry.create(
            title="Куди платити",
            answer="Оберіть варіант:",
            updated_by=ADMIN_ID,
            category="Оплата",
            type="router",
        ),
        actor_id=ADMIN_ID,
    )
    leaf_public = await entry_repo.save(
        Entry.create(title="Рахунок ОСББ", answer="IBAN тут", updated_by=ADMIN_ID, category="Оплата"),
        actor_id=ADMIN_ID,
    )
    leaf_dm_only = await entry_repo.save(
        Entry.create(
            title="Список пошт", answer="секретний список", updated_by=ADMIN_ID, category="Документи", visibility="dm_only"
        ),
        actor_id=ADMIN_ID,
    )
    router = await entry_repo.save(
        router.model_copy(update={"children": [leaf_public.id, leaf_dm_only.id]}), actor_id=ADMIN_ID
    )
    contact = await entry_repo.save(
        Entry.create(title="Контакти", answer="телефон тут", updated_by=ADMIN_ID, category="Контакти"),
        actor_id=ADMIN_ID,
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
    return services, bot, context, {"router": router, "leaf_public": leaf_public, "leaf_dm_only": leaf_dm_only, "contact": contact}


async def test_faq_in_group_lists_categories_excluding_dm_only(rig):
    services, bot, context, entries = rig
    update = make_update_for_group_message(bot, chat_id=GROUP_CHAT_ID, user_id=ADMIN_ID, text="/faq")
    await menu.cmd_faq(update, context)

    keyboard = bot.sent[-1]["kwargs"]["reply_markup"]
    labels = [b.text for row in keyboard.inline_keyboard for b in row]
    assert any("Оплата" in l for l in labels)
    assert any("Контакти" in l for l in labels)
    assert not any("Документи" in l for l in labels)  # only the dm_only entry lives there


async def test_faq_in_dm_includes_dm_only_category(rig):
    services, bot, context, entries = rig
    update = make_update_for_message(bot, chat_id=ADMIN_ID, user_id=ADMIN_ID, text="/faq")
    await menu.cmd_faq(update, context)

    keyboard = bot.sent[-1]["kwargs"]["reply_markup"]
    labels = [b.text for row in keyboard.inline_keyboard for b in row]
    assert any("Документи" in l for l in labels)


async def test_category_level_lists_entries(rig):
    services, bot, context, entries = rig
    cat_slug = "oplata"
    update = make_update_for_callback(bot, chat_id=GROUP_CHAT_ID, user_id=ADMIN_ID, data=f"m:1:{cat_slug}:0", chat_type="supergroup")
    await menu.cb_menu(update, context)

    keyboard = bot.edited[-1]["kwargs"]["reply_markup"]
    labels = [b.text for row in keyboard.inline_keyboard for b in row]
    assert "Куди платити" in labels
    assert "Рахунок ОСББ" in labels


async def test_leaf_entry_view_has_back_button_only(rig):
    services, bot, context, entries = rig
    token = short_id(entries["leaf_public"].id)
    update = make_update_for_callback(bot, chat_id=GROUP_CHAT_ID, user_id=ADMIN_ID, data=f"m:2:{token}:0", chat_type="supergroup")
    await menu.cb_menu(update, context)

    edited = bot.edited[-1]
    assert "Рахунок ОСББ" in edited["text"]
    labels = [b.text for row in edited["kwargs"]["reply_markup"].inline_keyboard for b in row]
    assert labels == [menu.texts.BTN_BACK_TO_LIST]


async def test_router_entry_view_shows_public_child_only_in_group(rig):
    services, bot, context, entries = rig
    token = short_id(entries["router"].id)
    update = make_update_for_callback(bot, chat_id=GROUP_CHAT_ID, user_id=ADMIN_ID, data=f"m:2:{token}:0", chat_type="supergroup")
    await menu.cb_menu(update, context)

    edited = bot.edited[-1]
    labels = [b.text for row in edited["kwargs"]["reply_markup"].inline_keyboard for b in row]
    assert "Рахунок ОСББ" in labels
    assert "Список пошт" not in labels  # dm_only child hidden from group view


async def test_router_entry_view_shows_dm_only_child_in_dm(rig):
    services, bot, context, entries = rig
    token = short_id(entries["router"].id)
    update = make_update_for_callback(bot, chat_id=ADMIN_ID, user_id=ADMIN_ID, data=f"m:2:{token}:0")
    await menu.cb_menu(update, context)

    edited = bot.edited[-1]
    labels = [b.text for row in edited["kwargs"]["reply_markup"].inline_keyboard for b in row]
    assert "Список пошт" in labels


async def test_dm_only_entry_directly_requested_in_group_is_refused(rig):
    services, bot, context, entries = rig
    token = short_id(entries["leaf_dm_only"].id)
    update = make_update_for_callback(bot, chat_id=GROUP_CHAT_ID, user_id=ADMIN_ID, data=f"m:2:{token}:0", chat_type="supergroup")
    await menu.cb_menu(update, context)

    assert bot.edited[-1]["text"] == menu.texts.LIST_EMPTY


async def test_deep_link_start_shows_entry_in_dm():
    from app.handlers.admin_crud import start

    store = FakeStore()
    entry_repo = EntryRepo(store)
    entry = await entry_repo.save(
        Entry.create(title="Глибоке посилання", answer="секрет", updated_by=1, visibility="dm_only"), actor_id=1
    )
    entry_cache = EntryCache(entry_repo, store)
    await entry_cache.refresh(force=True)
    services = Services(
        settings=None, store=store, entry_repo=entry_repo, entry_cache=entry_cache,
        admin_repo=AdminRepo(store), log_repo=LogRepo(store),
    )
    bot = RecordingBot()
    context = make_context({"services": services}, bot=bot, args=[f"faq_{entry.id}"])
    update = make_update_for_message(bot, chat_id=1, user_id=1, text=f"/start faq_{entry.id}")

    await start(update, context)

    assert "Глибоке посилання" in bot.sent[-1]["text"]
