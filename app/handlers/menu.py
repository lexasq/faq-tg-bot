from __future__ import annotations

import contextlib
from collections import Counter

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, JobQueue, MessageHandler, filters

from app import texts
from app.models import Entry, slugify
from app.rendering import paginate, render_answer
from app.repo.entries import short_id
from app.services import Services, get_services

ENTRIES_PER_PAGE = 8
MENU_AUTO_DELETE_SECONDS = 600


def _visible_entries(entries: list[Entry], *, in_group: bool) -> list[Entry]:
    # dm_only entries never appear in a group /faq menu (plan A5) — from a
    # DM they're fine to browse since the chat is already private.
    enabled = [e for e in entries if e.enabled]
    return [e for e in enabled if e.visibility == "public"] if in_group else enabled


def _categories_keyboard(entries: list[Entry]) -> InlineKeyboardMarkup:
    counts = Counter(e.category for e in entries)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for category, count in counts.most_common():
        row.append(InlineKeyboardButton(f"{category} ({count})", callback_data=f"m:1:{slugify(category)}:0"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def _entries_keyboard(
    page_entries: list[Entry], page: int, total_pages: int, category_slug: str
) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(e.title, callback_data=f"m:2:{short_id(e.id)}:0")] for e in page_entries]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(texts.BTN_PREV, callback_data=f"m:1:{category_slug}:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(texts.BTN_NEXT, callback_data=f"m:1:{category_slug}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(texts.BTN_BACK, callback_data="m:0:_:0")])
    return InlineKeyboardMarkup(rows)


def entry_view_content(entry: Entry, services: Services, *, in_group: bool) -> tuple[str, InlineKeyboardMarkup]:
    """Shared by the /faq menu, the router autoreply in group.py, and the
    /start faq_<id> deep link — one place that knows how to render a
    single entry, including a router's child buttons."""
    rows: list[list[InlineKeyboardButton]] = []
    if entry.type == "router":
        for child_id in entry.children:
            child = services.entry_cache.get(child_id)
            if child is not None and child.enabled and not (in_group and child.visibility == "dm_only"):
                rows.append([InlineKeyboardButton(child.title, callback_data=f"m:2:{short_id(child.id)}:0")])
    rows.append([InlineKeyboardButton(texts.BTN_BACK_TO_LIST, callback_data="m:0:_:0")])
    return render_answer(entry), InlineKeyboardMarkup(rows)


def _schedule_menu_deletion(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> None:
    job_queue: JobQueue | None = context.job_queue
    if job_queue is None:
        return

    async def _delete(job_context: ContextTypes.DEFAULT_TYPE) -> None:
        with contextlib.suppress(Exception):
            await job_context.bot.delete_message(chat_id=chat_id, message_id=message_id)

    job_queue.run_once(_delete, MENU_AUTO_DELETE_SECONDS)


async def cmd_faq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context.bot_data)
    in_group = update.effective_chat.type != ChatType.PRIVATE
    entries = _visible_entries(services.entry_cache.get_all_enabled(), in_group=in_group)
    if not entries:
        await update.message.reply_text(texts.LIST_EMPTY)
        return
    message = await update.message.reply_text(texts.MENU_ROOT_HEADER, reply_markup=_categories_keyboard(entries))
    if in_group:
        _schedule_menu_deletion(context, message.chat_id, message.message_id)


async def cb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, level_str, key, page_str = query.data.split(":")
    level, page = int(level_str), int(page_str)

    services = get_services(context.bot_data)
    in_group = update.effective_chat.type != ChatType.PRIVATE
    entries = _visible_entries(services.entry_cache.get_all_enabled(), in_group=in_group)

    if level == 0:
        if not entries:
            await query.edit_message_text(texts.LIST_EMPTY)
            return
        await query.edit_message_text(texts.MENU_ROOT_HEADER, reply_markup=_categories_keyboard(entries))
        return

    if level == 1:
        cat_entries = sorted((e for e in entries if slugify(e.category) == key), key=lambda e: e.title)
        page_entries, total_pages = paginate(cat_entries, page, ENTRIES_PER_PAGE)
        category_name = cat_entries[0].category if cat_entries else key
        header = texts.MENU_CATEGORY_HEADER.format(category=category_name, page=page + 1, total=total_pages)
        await query.edit_message_text(header, reply_markup=_entries_keyboard(page_entries, page, total_pages, key))
        return

    # level == 2: a single entry's answer
    entry_id = services.entry_cache.resolve_short(key)
    entry = services.entry_cache.get(entry_id) if entry_id else None
    if entry is None or not entry.enabled or (in_group and entry.visibility == "dm_only"):
        await query.edit_message_text(texts.LIST_EMPTY)
        return
    text, keyboard = entry_view_content(entry, services, in_group=in_group)
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")


HANDLERS = [
    CommandHandler("faq", cmd_faq),
    # Telegram bot commands are ASCII-only ([a-zA-Z0-9_]) — a client never
    # tags "/довідка" as a bot_command entity, so CommandHandler can't see
    # it. Matched as plain text instead.
    MessageHandler(filters.Regex(r"^/довідка(?:@\w+)?\b"), cmd_faq),
    CallbackQueryHandler(cb_menu, pattern=r"^m:"),
]
