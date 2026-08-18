from __future__ import annotations

from datetime import date, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from app import texts
from app.handlers.admin_crud import admin_only
from app.logging_conf import get_logger
from app.repo.entries import short_id
from app.services import get_services

logger = get_logger(__name__)

REVIEW_EXTENSION_DAYS = 180


async def monthly_review_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context.bot_data)
    today = date.today()
    stale = [e for e in services.entry_cache.get_all() if e.review_after is not None and e.review_after <= today]
    if not stale:
        return

    owners = [a for a in await services.admin_repo.list() if a.role == "owner"]
    if not owners:
        return

    lines = [texts.REVIEW_DIGEST_HEADER.format(count=len(stale))]
    rows = []
    for entry in stale:
        sid = short_id(entry.id)
        lines.append(f"• {entry.title} ({entry.review_after.isoformat()})")
        rows.append(
            [
                InlineKeyboardButton(f"{texts.BTN_REVIEW_OK} {entry.title[:20]}", callback_data=f"rvok:{sid}"),
                InlineKeyboardButton(f"{texts.BTN_REVIEW_EDIT} {entry.title[:20]}", callback_data=f"ec:{sid}"),
            ]
        )
    text = "\n".join(lines)
    keyboard = InlineKeyboardMarkup(rows)

    for owner in owners:
        try:
            await context.bot.send_message(chat_id=owner.user_id, text=text, reply_markup=keyboard)
        except Exception:
            logger.warning("review_digest_send_failed", owner_id=owner.user_id, exc_info=True)


@admin_only
async def cb_review_ok(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    token = query.data.split(":")[1]
    services = get_services(context.bot_data)
    entry_id = services.entry_cache.resolve_short(token)
    if entry_id is None:
        return
    entry = await services.entry_repo.get(entry_id)
    if entry is None:
        return

    new_review_after = date.today() + timedelta(days=REVIEW_EXTENSION_DAYS)
    await services.entry_repo.save(
        entry.model_copy(update={"review_after": new_review_after}), actor_id=update.effective_user.id
    )
    await services.entry_cache.refresh(force=True)
    await query.edit_message_text(texts.REVIEW_MARKED_OK.format(title=entry.title))


HANDLERS = [CallbackQueryHandler(cb_review_ok, pattern=r"^rvok:")]
