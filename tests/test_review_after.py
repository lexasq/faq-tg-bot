from datetime import date, timedelta

from app.handlers import review_after
from app.models import Entry
from app.repo.admins import AdminRepo
from app.repo.entries import EntryCache, EntryRepo, short_id
from app.repo.logs import LogRepo
from app.services import Services
from tests.fakes import FakeStore
from tests.telegram_fakes import RecordingBot, make_context, make_update_for_callback

OWNER_ID = 5005
EDITOR_ID = 5006


async def _build_rig():
    store = FakeStore()
    entry_repo = EntryRepo(store)
    admin_repo = AdminRepo(store)
    await admin_repo.add(OWNER_ID, name="Owner", role="owner", added_by=OWNER_ID)
    await admin_repo.add(EDITOR_ID, name="Editor", role="editor", added_by=OWNER_ID)

    stale = await entry_repo.save(
        Entry.create(title="Прострочений запис", answer="a", updated_by=OWNER_ID, review_after=date.today() - timedelta(days=1)),
        actor_id=OWNER_ID,
    )
    fresh = await entry_repo.save(
        Entry.create(title="Свіжий запис", answer="a", updated_by=OWNER_ID, review_after=date.today() + timedelta(days=30)),
        actor_id=OWNER_ID,
    )
    no_review = await entry_repo.save(Entry.create(title="Без ревʼю", answer="a", updated_by=OWNER_ID), actor_id=OWNER_ID)

    entry_cache = EntryCache(entry_repo, store)
    await entry_cache.refresh(force=True)
    services = Services(
        settings=None, store=store, entry_repo=entry_repo, entry_cache=entry_cache,
        admin_repo=admin_repo, log_repo=LogRepo(store),
    )
    bot = RecordingBot()
    context = make_context({"services": services}, bot=bot)
    return services, bot, context, {"stale": stale, "fresh": fresh, "no_review": no_review}


async def test_digest_only_dms_owners_about_stale_entries():
    services, bot, context, entries = await _build_rig()

    await review_after.monthly_review_digest(context)

    assert len(bot.sent) == 1  # only the owner, not the editor
    sent = bot.sent[0]
    assert sent["chat_id"] == OWNER_ID
    assert "Прострочений запис" in sent["text"]
    assert "Свіжий запис" not in sent["text"]
    assert "Без ревʼю" not in sent["text"]


async def test_no_stale_entries_sends_nothing():
    services, bot, context, entries = await _build_rig()
    await services.entry_repo.save(
        entries["stale"].model_copy(update={"review_after": date.today() + timedelta(days=10)}), actor_id=OWNER_ID
    )
    await services.entry_cache.refresh(force=True)

    await review_after.monthly_review_digest(context)
    assert bot.sent == []


async def test_mark_ok_pushes_review_date_out_six_months():
    services, bot, context, entries = await _build_rig()
    token = short_id(entries["stale"].id)
    update = make_update_for_callback(bot, chat_id=OWNER_ID, user_id=OWNER_ID, data=f"rvok:{token}")

    await review_after.cb_review_ok(update, context)

    updated = await services.entry_repo.get(entries["stale"].id)
    assert updated.review_after > date.today() + timedelta(days=170)
    assert bot.edited[-1]["text"] == review_after.texts.REVIEW_MARKED_OK.format(title="Прострочений запис")


async def test_mark_ok_ignores_non_admin():
    services, bot, context, entries = await _build_rig()
    token = short_id(entries["stale"].id)
    update = make_update_for_callback(bot, chat_id=9999, user_id=9999, data=f"rvok:{token}")

    await review_after.cb_review_ok(update, context)

    unchanged = await services.entry_repo.get(entries["stale"].id)
    assert unchanged.review_after == entries["stale"].review_after
