from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from app import texts
from app.logging_conf import get_logger
from app.services import get_services

logger = get_logger(__name__)


async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer(texts.FEEDBACK_THANKS)

    _, vote, token = query.data.split(":")
    services = get_services(context.bot_data)
    entry_id = services.entry_cache.resolve_short(token)
    if entry_id is not None:
        services.log_repo.log_feedback(
            match_log_id=None,
            entry_id=entry_id,
            user_id=update.effective_user.id,
            vote="up" if vote == "up" else "down",
        )

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(texts.BTN_ALL_QUESTIONS, callback_data="m:0:_:0")]])
    try:
        await query.edit_message_reply_markup(reply_markup=keyboard)
    except Exception:
        logger.debug("feedback_keyboard_edit_failed", exc_info=True)


HANDLERS = [CallbackQueryHandler(handle_feedback, pattern=r"^fb:(up|down):")]
