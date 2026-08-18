from pathlib import Path

import pytest
from telegram.ext import ConversationHandler

from app.handlers import admin_import
from app.repo.admins import AdminRepo
from app.repo.entries import EntryCache, EntryRepo
from app.repo.logs import LogRepo
from app.services import Services
from tests.fakes import FakeStore
from tests.telegram_fakes import RecordingBot, make_context, make_update_for_message

ADMIN_ID = 2002
CHAT_ID = ADMIN_ID

SEED_PATH = Path(__file__).parent / "fixtures" / "faq_example.md"


def _extract_seed_blocks_source() -> str:
    text = SEED_PATH.read_text(encoding="utf-8")
    start = text.index("```\nQ:")
    end = text.index("\n```", start)
    return text[start + 4 : end]


@pytest.fixture
async def rig():
    store = FakeStore()
    entry_repo = EntryRepo(store)
    admin_repo = AdminRepo(store)
    await admin_repo.add(ADMIN_ID, name="Owner", role="owner", added_by=ADMIN_ID)
    entry_cache = EntryCache(entry_repo, store)
    await entry_cache.refresh(force=True)
    services = Services(
        settings=None,
        store=store,
        entry_repo=entry_repo,
        entry_cache=entry_cache,
        admin_repo=admin_repo,
        log_repo=LogRepo(store),
    )
    bot = RecordingBot()
    context = make_context({"services": services}, bot=bot)
    return services, bot, context


def _msg(bot, text, **kwargs):
    return make_update_for_message(bot, chat_id=CHAT_ID, user_id=ADMIN_ID, text=text, **kwargs)


async def test_import_example_seed_content_end_to_end(rig):
    services, bot, context = rig

    state = await admin_import.cmd_import(_msg(bot, "/import"), context)
    assert state == admin_import.IMPORT_WAIT_CONTENT

    source = _extract_seed_blocks_source()
    state = await admin_import.import_receive_content(_msg(bot, source), context)

    # strict format, no orphans -> straight to the dry-run summary
    assert state == admin_import.IMPORT_CONFIRM
    summary = bot.sent[-1]["text"]
    assert "13 записів" in summary
    assert "13 нових" in summary
    # the 075-prefix duty-officer numbers should trip the phone-prefix warning
    assert "Попередження валідації" in summary

    state = await _confirm(bot, context)
    assert state == ConversationHandler.END

    entries = await services.entry_repo.list_all()
    assert len(entries) == 13

    router = next(e for e in entries if e.type == "router")
    assert router.title == "Куди платити внески"
    assert set(router.children) == {e.id for e in entries if e.title in {
        "Рахунок для оплати внесків на спільноту",
        "Рахунок для оплати через Партнер-Оплата",
        "Квитанції за додаткові послуги (Приклад Сервіс)",
        "Квитанції спільноти (охорона, чергові, прибирання, вивіз сміття)",
        "Прилади обліку та щорічна перевірка",
    }}

    dm_only = next(e for e in entries if e.title == "Електронна пошта учасників")
    assert dm_only.visibility == "dm_only"

    reviewed = next(e for e in entries if e.title == "Рахунок для оплати внесків на спільноту")
    assert reviewed.review_after.isoformat() == "2027-02-01"


async def _confirm(bot, context):
    from tests.telegram_fakes import make_update_for_callback

    update = make_update_for_callback(bot, chat_id=CHAT_ID, user_id=ADMIN_ID, data="imconf:yes")
    return await admin_import.import_confirm(update, context)


async def test_reimporting_unchanged_content_reports_all_unchanged(rig):
    services, bot, context = rig
    source = _extract_seed_blocks_source()

    await admin_import.cmd_import(_msg(bot, "/import"), context)
    await admin_import.import_receive_content(_msg(bot, source), context)
    await _confirm(bot, context)

    bot._sent.clear()
    await admin_import.cmd_import(_msg(bot, "/import"), context)
    await admin_import.import_receive_content(_msg(bot, source), context)
    summary = bot.sent[-1]["text"]
    assert "13 без змін" in summary


async def test_freeform_orphan_fixup_set_title(rig):
    services, bot, context = rig
    from tests.telegram_fakes import make_update_for_callback

    text = "Це просто параграф без явного заголовку і без наступного рядка тому стає сиротою."
    await admin_import.cmd_import(_msg(bot, "/import"), context)
    state = await admin_import.import_receive_content(_msg(bot, text), context)
    assert state == admin_import.IMPORT_FIXUP
    assert "Не вдалося визначити заголовок" in bot.sent[-1]["text"]

    cb = make_update_for_callback(bot, chat_id=CHAT_ID, user_id=ADMIN_ID, data="imfix:title")
    state = await admin_import.import_fixup_choice(cb, context)
    assert state == admin_import.IMPORT_FIXUP
    assert context.user_data["import_awaiting_title"] is True

    state = await admin_import.import_fixup_title_received(_msg(bot, "Заданий заголовок"), context)
    assert state == admin_import.IMPORT_CONFIRM

    candidates_summary = bot.sent[-1]["text"]
    assert "1 записів" in candidates_summary
    assert "1 нових" in candidates_summary


async def test_freeform_orphan_attach_to_previous(rig):
    services, bot, context = rig
    from tests.telegram_fakes import make_update_for_callback

    text = (
        "Короткий заголовок\n"
        "Перший рядок тіла\n"
        "\n"
        "Це другий блок без заголовка що є довгим суцільним абзацом без явної структури взагалі."
    )
    await admin_import.cmd_import(_msg(bot, "/import"), context)
    state = await admin_import.import_receive_content(_msg(bot, text), context)
    assert state == admin_import.IMPORT_FIXUP

    cb = make_update_for_callback(bot, chat_id=CHAT_ID, user_id=ADMIN_ID, data="imfix:attach")
    state = await admin_import.import_fixup_choice(cb, context)
    assert state == admin_import.IMPORT_CONFIRM

    candidates = context.user_data["import_candidates"]
    assert len(candidates) == 1
    assert "довгим суцільним абзацом" in candidates[0]["answer"]


async def test_orphan_skip_discards_block(rig):
    services, bot, context = rig
    from tests.telegram_fakes import make_update_for_callback

    text = "Це довгий одинокий абзац що не матиме заголовка і буде повністю пропущений при імпорті цього тесту."
    await admin_import.cmd_import(_msg(bot, "/import"), context)
    state = await admin_import.import_receive_content(_msg(bot, text), context)
    assert state == admin_import.IMPORT_FIXUP

    cb = make_update_for_callback(bot, chat_id=CHAT_ID, user_id=ADMIN_ID, data="imfix:skip")
    state = await admin_import.import_fixup_choice(cb, context)
    assert state == ConversationHandler.END
    assert bot.sent[-1]["text"] == admin_import.texts.IMPORT_NOTHING_TO_IMPORT


async def test_export_round_trips_seed_content(rig):
    services, bot, context = rig
    source = _extract_seed_blocks_source()
    await admin_import.cmd_import(_msg(bot, "/import"), context)
    await admin_import.import_receive_content(_msg(bot, source), context)
    await _confirm(bot, context)

    await admin_import.cmd_export(_msg(bot, "/export"), context)

    from app.importers.text_blocks import parse_strict

    entries = await services.entry_repo.list_all()
    from app.importers.text_blocks import render_strict_export

    exported = render_strict_export(entries)
    reimported, errors = parse_strict(exported)
    assert errors == []
    assert len(reimported) == len(entries)
