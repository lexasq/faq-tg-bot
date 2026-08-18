from __future__ import annotations

import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import MessageEntityType
from telegram.error import Forbidden
from telegram.ext import ContextTypes, MessageHandler, filters

from app import texts
from app.handlers import menu
from app.logging_conf import get_logger
from app.matching.normalize import normalize_text
from app.matching.regex_matcher import decide_with_router_precedence, has_question_marker
from app.models import Entry
from app.rendering import render_answer
from app.repo.entries import short_id
from app.services import Services, get_services

logger = get_logger(__name__)

_MIN_TEXT_LEN = 3
_DEFAULT_HOURLY_CAP = 5


class CooldownStore:
    """In-memory anti-flood state. A restart resetting this is harmless —
    worst case a group gets one extra autoreply."""

    def __init__(self) -> None:
        self._last_reply: dict[tuple[int, str], float] = {}
        self._recent_replies: dict[int, list[float]] = {}

    def is_cooling_down(self, chat_id: int, entry_id: str, cooldown_seconds: int) -> bool:
        last = self._last_reply.get((chat_id, entry_id))
        return last is not None and (time.monotonic() - last) < cooldown_seconds

    def hourly_cap_reached(self, chat_id: int, cap: int = _DEFAULT_HOURLY_CAP) -> bool:
        now = time.monotonic()
        recent = [t for t in self._recent_replies.get(chat_id, []) if now - t < 3600]
        self._recent_replies[chat_id] = recent
        return len(recent) >= cap

    def record_reply(self, chat_id: int, entry_id: str) -> None:
        now = time.monotonic()
        self._last_reply[(chat_id, entry_id)] = now
        self._recent_replies.setdefault(chat_id, []).append(now)


def _is_mention_or_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    message = update.effective_message
    bot = context.bot

    reply_to = message.reply_to_message
    if reply_to is not None and reply_to.from_user is not None and reply_to.from_user.id == bot.id:
        return True

    try:
        bot_username = bot.username
    except RuntimeError:
        bot_username = None
    if bot_username and message.entities:
        for entity in message.entities:
            if entity.type in (MessageEntityType.MENTION, MessageEntityType.TEXT_MENTION):
                mention_text = message.text[entity.offset : entity.offset + entity.length]
                if mention_text.lstrip("@").lower() == bot_username.lower():
                    return True
    return False


def _feedback_keyboard(entry_id: str) -> InlineKeyboardMarkup:
    sid = short_id(entry_id)
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(texts.BTN_THUMBS_UP, callback_data=f"fb:up:{sid}"),
                InlineKeyboardButton(texts.BTN_THUMBS_DOWN, callback_data=f"fb:down:{sid}"),
                InlineKeyboardButton(texts.BTN_ALL_QUESTIONS, callback_data="m:0:_:0"),
            ]
        ]
    )


async def _deliver_answer(
    update: Update, context: ContextTypes.DEFAULT_TYPE, message, entry: Entry, *, thread_id: int | None, services: Services
) -> None:
    if entry.visibility == "dm_only":
        # Plan A5: never let dm_only text touch the group. Post only the
        # notice publicly, DM the real answer, and if the user has never
        # started the bot (Forbidden), fall back to a deep-link button.
        notice = await message.reply_text(texts.SENT_TO_DM, message_thread_id=thread_id)
        try:
            await context.bot.send_message(
                chat_id=update.effective_user.id, text=render_answer(entry), parse_mode="HTML"
            )
        except Forbidden:
            try:
                bot_username = context.bot.username
            except RuntimeError:
                bot_username = None
            if bot_username:
                link = f"https://t.me/{bot_username}?start=faq_{entry.id}"
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(texts.BTN_OPEN_IN_DM, url=link)]])
                await notice.edit_text(texts.SENT_TO_DM_FAILED, reply_markup=keyboard)
        return

    if entry.type == "router":
        text, keyboard = menu.entry_view_content(entry, services, in_group=True)
        await message.reply_text(text, parse_mode="HTML", reply_markup=keyboard, message_thread_id=thread_id)
        return

    await message.reply_text(
        render_answer(entry),
        parse_mode="HTML",
        reply_markup=_feedback_keyboard(entry.id),
        message_thread_id=thread_id,
    )


async def _send_not_found(message, *, thread_id: int | None) -> None:
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(texts.BTN_ALL_QUESTIONS, callback_data="m:0:_:0")]])
    await message.reply_text(texts.NOT_FOUND_ON_MENTION, reply_markup=keyboard, message_thread_id=thread_id)


async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.text:
        return
    if message.edit_date is not None:
        return
    user = update.effective_user
    if user is None or user.is_bot:
        return
    if message.text.startswith("/"):
        return
    if len(message.text) < _MIN_TEXT_LEN:
        return

    try:
        await _route(update, context)
    except Exception:
        logger.exception("group_handler_failed", chat_id=message.chat_id)


async def _route(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    services: Services = get_services(context.bot_data)
    config = services.entry_cache.config

    if not config.autoreply_enabled:
        return
    if config.chat_ids and message.chat_id not in config.chat_ids:
        return

    entries = services.entry_cache.get_all_enabled()
    entries_by_id = {e.id: e for e in entries}
    results = await services.matcher.match(message.text, entries)
    top = results[0] if results else None
    cleaned, _tokens = normalize_text(message.text)
    thread_id = message.message_thread_id
    mentioned = _is_mention_or_reply(update, context)

    if mentioned:
        decision = decide_with_router_precedence(results, entries_by_id, config.suggest_threshold)
        if decision is not None:
            entry = services.entry_cache.get(decision.entry_id)
            if entry is not None:
                await _deliver_answer(update, context, message, entry, thread_id=thread_id, services=services)
                services.log_repo.log_match(
                    chat_id=message.chat_id,
                    user_id=update.effective_user.id,
                    text=message.text,
                    entry_id=entry.id,
                    score=decision.score,
                    action="mention",
                )
                return
        await _send_not_found(message, thread_id=thread_id)
        services.log_repo.log_miss(
            chat_id=message.chat_id,
            user_id=update.effective_user.id,
            text=message.text,
            top_entry_id=top.entry_id if top else None,
            top_score=top.score if top else 0.0,
            direct_ask=True,
        )
        return

    # plain group message
    decision = decide_with_router_precedence(results, entries_by_id, config.auto_threshold)
    cooldown_store: CooldownStore = context.bot_data.setdefault("cooldown_store", CooldownStore())

    if decision is not None:
        if cooldown_store.is_cooling_down(message.chat_id, decision.entry_id, config.cooldown_seconds):
            return
        if cooldown_store.hourly_cap_reached(message.chat_id):
            return
        entry = services.entry_cache.get(decision.entry_id)
        if entry is None:
            return
        await _deliver_answer(update, context, message, entry, thread_id=thread_id, services=services)
        cooldown_store.record_reply(message.chat_id, decision.entry_id)
        services.log_repo.log_match(
            chat_id=message.chat_id,
            user_id=update.effective_user.id,
            text=message.text,
            entry_id=entry.id,
            score=decision.score,
            action="replied",
        )
        return

    # not confidently answered — log if it's worth reviewing later
    if top is not None and (top.score >= config.suggest_threshold or has_question_marker(cleaned)):
        services.log_repo.log_miss(
            chat_id=message.chat_id,
            user_id=update.effective_user.id,
            text=message.text,
            top_entry_id=top.entry_id,
            top_score=top.score,
        )
    elif top is None and has_question_marker(cleaned):
        services.log_repo.log_miss(
            chat_id=message.chat_id,
            user_id=update.effective_user.id,
            text=message.text,
            top_entry_id=None,
            top_score=0.0,
        )


HANDLERS = [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.ChatType.PRIVATE, handle_group_message)]
