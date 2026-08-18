from __future__ import annotations

import re
from datetime import datetime
from functools import wraps

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app import texts
from app.importers.text_blocks import split_pattern_list
from app.logging_conf import get_logger
from app.matching.normalize import normalize_text
from app.models import Entry, slugify
from app.rendering import paginate, render_answer
from app.repo.entries import short_id
from app.services import Services, get_services

logger = get_logger(__name__)

LIST_PAGE_SIZE = 8
HISTORY_PAGE_SIZE = 5

STOPWORDS = {
    "для", "та", "і", "й", "в", "у", "на", "з", "із", "зі", "як", "що",
    "це", "або", "чи", "до", "від", "по", "за", "не", "ми", "ви", "він",
    "вона", "воно", "вони", "але", "коли", "де",
}

(
    ADD_TITLE,
    ADD_CATEGORY,
    ADD_CATEGORY_NEW,
    ADD_ANSWER,
    ADD_PATTERNS,
    ADD_PATTERNS_OWN,
    ADD_CONFIRM,
    EDIT_ANSWER,
    EDIT_PATTERNS,
    EDIT_CATEGORY,
    EDIT_CATEGORY_NEW,
    REVIEW_LINK_SEARCH,
    RESET_CONFIRM,
) = range(13)

RESET_CONFIRMATION_WORD = "RESET"

_CONVERSATION_STATE_KEYS = (
    "add_title", "add_category", "add_answer_lines", "add_answer", "add_patterns",
    "add_extra_pattern", "categories_map", "edit_entry_id", "edit_answer_lines",
    "review_link_miss_id", "import_awaiting_title",
)


def _reset_conversation_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Every entry-point handler calls this first. Two reasons: (1) a
    fresh /add or entry-card tap shouldn't inherit leftover state from an
    earlier abandoned flow, and (2) these same handlers are duplicated
    into `fallbacks` below so tapping one entry-card button while another
    edit is mid-flight interrupts and restarts cleanly instead of being
    silently dropped (PTB's ConversationHandler only checks entry_points
    when no conversation is active for that user — with one shared
    ConversationHandler across every entry-card action, an unfinished
    edit on entry A used to make every button on entry B a silent no-op
    until /cancel or the 15-minute timeout)."""
    for key in _CONVERSATION_STATE_KEYS:
        context.user_data.pop(key, None)


def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        chat = update.effective_chat
        if chat is None or chat.type != ChatType.PRIVATE:
            return None
        services = get_services(context.bot_data)
        user = update.effective_user
        if user is None or not await services.admin_repo.is_admin(user.id):
            return None
        return await func(update, context, *args, **kwargs)

    return wrapper


def suggest_patterns(title: str) -> list[str]:
    cleaned, tokens = normalize_text(title)
    significant = [t for t in tokens if len(t) > 3 and t not in STOPWORDS]

    patterns: list[str] = []
    if cleaned:
        patterns.append(re.escape(cleaned))
    for tok in significant:
        escaped = re.escape(tok)
        if escaped not in patterns:
            patterns.append(escaped)
    if len(significant) >= 2:
        patterns.append(r"\s+".join(re.escape(t) for t in significant))

    seen: set[str] = set()
    deduped: list[str] = []
    for p in patterns:
        if p not in seen:
            seen.add(p)
            deduped.append(p)
    return deduped


def _category_keyboard(categories: set[str], prefix: str) -> tuple[InlineKeyboardMarkup, dict[str, str]]:
    cat_map: dict[str, str] = {}
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for cat in sorted(categories):
        slug = slugify(cat) or "n"
        cat_map[slug] = cat
        row.append(InlineKeyboardButton(cat, callback_data=f"{prefix}:{slug}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(texts.BTN_NEW_CATEGORY, callback_data=f"{prefix}:new")])
    return InlineKeyboardMarkup(rows), cat_map


def _entry_card_text(entry: Entry) -> str:
    status_icon = "🟢" if entry.enabled else "🔇"
    preview = entry.answer if len(entry.answer) <= 300 else entry.answer[:300] + "…"
    return texts.ENTRY_CARD_TEMPLATE.format(
        status_icon=status_icon,
        title=entry.title,
        category=entry.category,
        type=entry.type,
        visibility=entry.visibility,
        version=entry.version,
        updated_at=entry.updated_at.strftime("%Y-%m-%d %H:%M"),
        pattern_count=len(entry.patterns),
        answer_preview=preview,
    )


def _entry_card_keyboard(entry: Entry) -> InlineKeyboardMarkup:
    sid = short_id(entry.id)
    toggle_label = texts.BTN_DISABLE if entry.enabled else texts.BTN_ENABLE
    visibility_label = texts.BTN_MAKE_DM_ONLY if entry.visibility == "public" else texts.BTN_MAKE_PUBLIC
    rows = [
        [
            InlineKeyboardButton(texts.BTN_EDIT_ANSWER, callback_data=f"ecedit:ans:{sid}"),
            InlineKeyboardButton(texts.BTN_EDIT_PATTERNS, callback_data=f"ecedit:pat:{sid}"),
        ],
        [
            InlineKeyboardButton(texts.BTN_EDIT_CATEGORY, callback_data=f"ecedit:cat:{sid}"),
            InlineKeyboardButton(visibility_label, callback_data=f"ec:vis:{sid}"),
        ],
        [
            InlineKeyboardButton(toggle_label, callback_data=f"ec:tog:{sid}"),
            InlineKeyboardButton(texts.BTN_HISTORY, callback_data=f"ec:hist:{sid}:0"),
        ],
        [
            InlineKeyboardButton(texts.BTN_DELETE, callback_data=f"ec:del:{sid}"),
        ],
    ]
    return InlineKeyboardMarkup(rows)


async def _send_entry_card(message_target, entry: Entry) -> None:
    await message_target.reply_text(
        _entry_card_text(entry), reply_markup=_entry_card_keyboard(entry), parse_mode="HTML"
    )


async def _edit_entry_card(query, entry: Entry) -> None:
    await query.edit_message_text(
        _entry_card_text(entry), reply_markup=_entry_card_keyboard(entry), parse_mode="HTML"
    )


def _resolve_entry(services: Services, token: str) -> Entry | None:
    entry_id = services.entry_cache.resolve_short(token)
    if entry_id is None:
        return None
    return services.entry_cache.get(entry_id)


# --- /start ---------------------------------------------------------------


async def _send_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context.bot_data)
    user = update.effective_user
    if user is not None and await services.admin_repo.is_admin(user.id):
        await update.message.reply_text(texts.START_ADMIN_MENU)
    else:
        await update.message.reply_text(texts.START_NON_ADMIN)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_chat.type != ChatType.PRIVATE:
        return
    services = get_services(context.bot_data)

    if context.args and context.args[0].startswith("faq_"):
        from app.handlers import menu  # local import: menu.py doesn't depend on admin_crud

        entry_id = context.args[0][len("faq_") :]
        entry = services.entry_cache.get(entry_id)
        if entry is not None and entry.enabled:
            text, keyboard = menu.entry_view_content(entry, services, in_group=False)
            await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
            return

    await _send_menu(update, context)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_chat.type != ChatType.PRIVATE:
        return
    await _send_menu(update, context)


# --- /reset (owner only — deletes every FAQ entry) -------------------------


@admin_only
async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    services = get_services(context.bot_data)
    if not await services.admin_repo.is_owner(update.effective_user.id):
        await update.message.reply_text(texts.RESET_NOT_OWNER)
        return ConversationHandler.END

    _reset_conversation_state(context)
    entries = await services.entry_repo.list_all()
    if not entries:
        await update.message.reply_text(texts.RESET_EMPTY)
        return ConversationHandler.END

    await update.message.reply_text(texts.RESET_WARNING.format(count=len(entries), word=RESET_CONFIRMATION_WORD))
    return RESET_CONFIRM


async def reset_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text.strip() != RESET_CONFIRMATION_WORD:
        await update.message.reply_text(texts.RESET_WRONG_CONFIRMATION.format(word=RESET_CONFIRMATION_WORD))
        return RESET_CONFIRM

    services = get_services(context.bot_data)
    entries = await services.entry_repo.list_all()
    for entry in entries:
        await services.entry_repo.delete(entry.id)
    await services.entry_cache.refresh(force=True)

    await update.message.reply_text(texts.RESET_DONE.format(count=len(entries)))
    context.user_data.clear()
    return ConversationHandler.END


# --- /add conversation ------------------------------------------------------


@admin_only
async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _reset_conversation_state(context)
    await update.message.reply_text(texts.ADD_ASK_TITLE)
    return ADD_TITLE


async def add_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    title = update.message.text.strip()
    if len(title) > 100:
        await update.message.reply_text(texts.ADD_TITLE_TOO_LONG)
        return ADD_TITLE
    context.user_data["add_title"] = title

    services = get_services(context.bot_data)
    categories = {e.category for e in services.entry_cache.get_all()}
    keyboard, cat_map = _category_keyboard(categories, "addcat")
    context.user_data["categories_map"] = cat_map
    await update.message.reply_text(texts.ADD_ASK_CATEGORY, reply_markup=keyboard)
    return ADD_CATEGORY


async def add_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _, slug = query.data.split(":", 1)
    if slug == "new":
        await query.edit_message_text(texts.ADD_ASK_CATEGORY_NEW)
        return ADD_CATEGORY_NEW
    cat_map = context.user_data.get("categories_map", {})
    context.user_data["add_category"] = cat_map.get(slug, "Загальне")
    await query.edit_message_text(texts.ADD_ASK_ANSWER)
    return ADD_ANSWER


async def add_category_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["add_category"] = update.message.text.strip() or "Загальне"
    await update.message.reply_text(texts.ADD_ASK_ANSWER)
    return ADD_ANSWER


async def add_answer_line(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lines = context.user_data.setdefault("add_answer_lines", [])
    lines.append(update.message.text)
    return ADD_ANSWER


async def add_answer_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lines = context.user_data.get("add_answer_lines", [])
    answer = "\n".join(lines).strip()
    if not answer:
        await update.message.reply_text(texts.ADD_ANSWER_EMPTY)
        return ADD_ANSWER
    context.user_data["add_answer"] = answer

    title = context.user_data["add_title"]
    suggested = suggest_patterns(title)
    extra = context.user_data.pop("add_extra_pattern", None)
    if extra:
        # /review's "Create entry" prefills the miss text itself as a
        # pattern candidate, ahead of the title-derived suggestions.
        extra_pattern = re.escape(normalize_text(extra)[0])
        if extra_pattern not in suggested:
            suggested.insert(0, extra_pattern)
    context.user_data["add_patterns"] = suggested
    listing = "\n".join(f"• <code>{p}</code>" for p in suggested) or "(немає)"
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(texts.BTN_ACCEPT_PATTERNS, callback_data="addpat:accept"),
                InlineKeyboardButton(texts.BTN_OWN_PATTERNS, callback_data="addpat:own"),
            ]
        ]
    )
    await update.message.reply_text(
        texts.ADD_SUGGESTED_PATTERNS.format(patterns=listing), reply_markup=keyboard, parse_mode="HTML"
    )
    return ADD_PATTERNS


async def add_patterns_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":", 1)[1]
    if choice == "own":
        await query.edit_message_text(texts.ADD_ASK_OWN_PATTERNS)
        return ADD_PATTERNS_OWN
    return await _show_add_preview(query.message, context, edit=True)


async def add_patterns_own(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    patterns = split_pattern_list(update.message.text)
    context.user_data["add_patterns"] = patterns
    return await _show_add_preview(update.message, context, edit=False)


async def _show_add_preview(message, context: ContextTypes.DEFAULT_TYPE, *, edit: bool) -> int:
    title = context.user_data["add_title"]
    answer = context.user_data["add_answer"]
    category = context.user_data["add_category"]
    patterns = context.user_data["add_patterns"]

    preview_entry = Entry.create(title=title, answer=answer, updated_by=0, category=category, patterns=patterns)
    body = render_answer(preview_entry)
    footer = texts.ADD_PREVIEW_FOOTER.format(category=category, patterns=", ".join(patterns) or "—")
    text = texts.ADD_PREVIEW_HEADER + body + footer
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(texts.BTN_CONFIRM, callback_data="addconf:yes"),
          InlineKeyboardButton(texts.BTN_CANCEL, callback_data="addconf:no")]]
    )
    if edit:
        await message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    return ADD_CONFIRM


async def add_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":", 1)[1]
    if choice == "no":
        await query.edit_message_text(texts.CANCELLED)
        context.user_data.clear()
        return ConversationHandler.END

    services = get_services(context.bot_data)
    user_id = update.effective_user.id
    entry = Entry.create(
        title=context.user_data["add_title"],
        answer=context.user_data["add_answer"],
        updated_by=user_id,
        category=context.user_data["add_category"],
        patterns=context.user_data["add_patterns"],
    )
    saved = await services.entry_repo.save(entry, actor_id=user_id)
    await services.entry_cache.refresh(force=True)
    await query.edit_message_text(texts.ADD_CREATED)
    await _send_entry_card(query.message, saved)
    context.user_data.clear()
    return ConversationHandler.END


# --- entry-field edit flows (opened from the entry card) ------------------


@admin_only
async def edit_answer_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    token = query.data.split(":")[2]
    services = get_services(context.bot_data)
    entry = _resolve_entry(services, token)
    if entry is None:
        await query.edit_message_text(texts.LIST_EMPTY)
        return ConversationHandler.END
    _reset_conversation_state(context)
    context.user_data["edit_entry_id"] = entry.id
    context.user_data["edit_answer_lines"] = []
    await query.message.reply_text(texts.EDIT_ANSWER_ASK)
    return EDIT_ANSWER


async def edit_answer_line(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.setdefault("edit_answer_lines", []).append(update.message.text)
    return EDIT_ANSWER


async def edit_answer_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    services = get_services(context.bot_data)
    entry_id = context.user_data["edit_entry_id"]
    entry = await services.entry_repo.get(entry_id)
    if entry is None:
        await update.message.reply_text(texts.LIST_EMPTY)
        return ConversationHandler.END
    answer = "\n".join(context.user_data.get("edit_answer_lines", [])).strip()
    if not answer:
        await update.message.reply_text(texts.ADD_ANSWER_EMPTY)
        return EDIT_ANSWER
    updated = await services.entry_repo.save(
        entry.model_copy(update={"answer": answer}), actor_id=update.effective_user.id
    )
    await services.entry_cache.refresh(force=True)
    await update.message.reply_text(texts.EDIT_ANSWER_DONE)
    await _send_entry_card(update.message, updated)
    context.user_data.clear()
    return ConversationHandler.END


@admin_only
async def edit_patterns_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    token = query.data.split(":")[2]
    services = get_services(context.bot_data)
    entry = _resolve_entry(services, token)
    if entry is None:
        await query.edit_message_text(texts.LIST_EMPTY)
        return ConversationHandler.END
    _reset_conversation_state(context)
    context.user_data["edit_entry_id"] = entry.id
    listing = "\n".join(f"• <code>{p}</code>" for p in entry.patterns) or texts.PATTERNS_EMPTY
    prompt = texts.EDIT_PATTERNS_ASK.format(count=len(entry.patterns), patterns=listing)
    await query.message.reply_text(prompt, parse_mode="HTML")
    return EDIT_PATTERNS


async def edit_patterns_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    services = get_services(context.bot_data)
    entry_id = context.user_data["edit_entry_id"]
    entry = await services.entry_repo.get(entry_id)
    if entry is None:
        await update.message.reply_text(texts.LIST_EMPTY)
        return ConversationHandler.END
    patterns = split_pattern_list(update.message.text)
    updated = await services.entry_repo.save(
        entry.model_copy(update={"patterns": patterns}), actor_id=update.effective_user.id
    )
    await services.entry_cache.refresh(force=True)
    await update.message.reply_text(texts.EDIT_PATTERNS_DONE)
    await _send_entry_card(update.message, updated)
    context.user_data.clear()
    return ConversationHandler.END


@admin_only
async def edit_category_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    token = query.data.split(":")[2]
    services = get_services(context.bot_data)
    entry = _resolve_entry(services, token)
    if entry is None:
        await query.edit_message_text(texts.LIST_EMPTY)
        return ConversationHandler.END
    _reset_conversation_state(context)
    context.user_data["edit_entry_id"] = entry.id
    categories = {e.category for e in services.entry_cache.get_all()}
    keyboard, cat_map = _category_keyboard(categories, "eccat")
    context.user_data["categories_map"] = cat_map
    await query.message.reply_text(texts.ADD_ASK_CATEGORY, reply_markup=keyboard)
    return EDIT_CATEGORY


async def edit_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    slug = query.data.split(":", 1)[1]
    if slug == "new":
        await query.edit_message_text(texts.ADD_ASK_CATEGORY_NEW)
        return EDIT_CATEGORY_NEW
    cat_map = context.user_data.get("categories_map", {})
    category = cat_map.get(slug, "Загальне")
    return await _apply_category(update, context, category, query=query)


async def edit_category_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    category = update.message.text.strip() or "Загальне"
    return await _apply_category(update, context, category, query=None)


async def _apply_category(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str, *, query) -> int:
    services = get_services(context.bot_data)
    entry_id = context.user_data["edit_entry_id"]
    entry = await services.entry_repo.get(entry_id)
    if entry is None:
        return ConversationHandler.END
    updated = await services.entry_repo.save(
        entry.model_copy(update={"category": category}), actor_id=update.effective_user.id
    )
    await services.entry_cache.refresh(force=True)
    text = texts.EDIT_CATEGORY_DONE.format(category=category)
    if query is not None:
        await query.edit_message_text(text)
        await _send_entry_card(query.message, updated)
    else:
        await update.message.reply_text(text)
        await _send_entry_card(update.message, updated)
    context.user_data.clear()
    return ConversationHandler.END


# --- /review actions that continue into this conversation -----------------


@admin_only
async def review_create_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from app.repo.logs import MISS_LOG

    query = update.callback_query
    await query.answer()
    doc_id = query.data.split(":", 1)[1]
    services = get_services(context.bot_data)
    miss = await services.log_repo.get(MISS_LOG, doc_id)
    if miss is None:
        await query.edit_message_text(texts.REVIEW_EMPTY)
        return ConversationHandler.END

    _reset_conversation_state(context)
    title = miss["text"][:100]
    context.user_data["add_title"] = title
    context.user_data["add_extra_pattern"] = miss["text"]
    categories = {e.category for e in services.entry_cache.get_all()}
    keyboard, cat_map = _category_keyboard(categories, "addcat")
    context.user_data["categories_map"] = cat_map
    await services.log_repo.mark_handled(MISS_LOG, doc_id)
    await query.edit_message_text(texts.ADD_ASK_CATEGORY_FOR.format(title=title), reply_markup=keyboard)
    return ADD_CATEGORY


@admin_only
async def review_link_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    doc_id = query.data.split(":", 1)[1]
    _reset_conversation_state(context)
    context.user_data["review_link_miss_id"] = doc_id
    await query.edit_message_text(texts.FIND_ASK)
    return REVIEW_LINK_SEARCH


async def review_link_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    services = get_services(context.bot_data)
    query_text, _ = normalize_text(update.message.text)
    matches = [
        e
        for e in services.entry_cache.get_all()
        if query_text in normalize_text(e.title)[0] or query_text in normalize_text(e.answer)[0]
    ][:8]
    if not matches:
        await update.message.reply_text(texts.FIND_EMPTY)
        return REVIEW_LINK_SEARCH
    rows = [[InlineKeyboardButton(e.title, callback_data=f"rvlpick:{short_id(e.id)}")] for e in matches]
    await update.message.reply_text(
        texts.FIND_RESULTS_HEADER.format(count=len(matches)), reply_markup=InlineKeyboardMarkup(rows)
    )
    return REVIEW_LINK_SEARCH


async def review_link_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from app.repo.logs import MISS_LOG

    query = update.callback_query
    await query.answer()
    token = query.data.split(":", 1)[1]
    services = get_services(context.bot_data)
    entry_id = services.entry_cache.resolve_short(token)
    doc_id = context.user_data.pop("review_link_miss_id", None)
    if entry_id is None or doc_id is None:
        context.user_data.clear()
        return ConversationHandler.END

    miss = await services.log_repo.get(MISS_LOG, doc_id)
    entry = await services.entry_repo.get(entry_id)
    if miss is None or entry is None:
        context.user_data.clear()
        return ConversationHandler.END

    new_pattern = re.escape(normalize_text(miss["text"])[0])
    patterns = entry.patterns if new_pattern in entry.patterns else [*entry.patterns, new_pattern]
    await services.entry_repo.save(entry.model_copy(update={"patterns": patterns}), actor_id=update.effective_user.id)
    await services.entry_cache.refresh(force=True)
    await services.log_repo.mark_handled(MISS_LOG, doc_id)
    await query.edit_message_text(texts.REVIEW_LINKED.format(title=entry.title))
    context.user_data.clear()
    return ConversationHandler.END


# --- shared conversation fallbacks -----------------------------------------


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(texts.CANCELLED)
    return ConversationHandler.END


async def conversation_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    if update and update.effective_message:
        await update.effective_message.reply_text(texts.SESSION_TIMED_OUT)


# Registered as BOTH entry_points and fallbacks: PTB's ConversationHandler
# only consults entry_points when no conversation is currently tracked for
# that (chat, user). With every entry-card action sharing one
# ConversationHandler, an abandoned edit on entry A used to make every
# button on entry B a silent no-op for up to 15 minutes — none of these
# patterns matched the stuck state's own handlers, and nothing fell back
# to entry_points. Listing them in fallbacks too means tapping any of
# these while another edit is mid-flight interrupts and restarts cleanly.
_ACTION_ENTRY_POINTS = [
    CommandHandler("add", cmd_add),
    CommandHandler("reset", cmd_reset),
    CallbackQueryHandler(edit_answer_entry, pattern=r"^ecedit:ans:"),
    CallbackQueryHandler(edit_patterns_entry, pattern=r"^ecedit:pat:"),
    CallbackQueryHandler(edit_category_entry, pattern=r"^ecedit:cat:"),
    CallbackQueryHandler(review_create_entry, pattern=r"^rvc:"),
    CallbackQueryHandler(review_link_entry, pattern=r"^rvl:"),
]

admin_conversation = ConversationHandler(
    entry_points=_ACTION_ENTRY_POINTS,
    states={
        ADD_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_title)],
        ADD_CATEGORY: [CallbackQueryHandler(add_category_chosen, pattern=r"^addcat:")],
        ADD_CATEGORY_NEW: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_category_new)],
        ADD_ANSWER: [
            CommandHandler("done", add_answer_done),
            MessageHandler(filters.TEXT & ~filters.COMMAND, add_answer_line),
        ],
        ADD_PATTERNS: [CallbackQueryHandler(add_patterns_choice, pattern=r"^addpat:")],
        ADD_PATTERNS_OWN: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_patterns_own)],
        ADD_CONFIRM: [CallbackQueryHandler(add_confirm, pattern=r"^addconf:")],
        EDIT_ANSWER: [
            CommandHandler("done", edit_answer_done),
            MessageHandler(filters.TEXT & ~filters.COMMAND, edit_answer_line),
        ],
        EDIT_PATTERNS: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_patterns_done)],
        EDIT_CATEGORY: [CallbackQueryHandler(edit_category_chosen, pattern=r"^eccat:")],
        EDIT_CATEGORY_NEW: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_category_new)],
        REVIEW_LINK_SEARCH: [
            CallbackQueryHandler(review_link_pick, pattern=r"^rvlpick:"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, review_link_search),
        ],
        RESET_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, reset_confirm)],
        ConversationHandler.TIMEOUT: [MessageHandler(filters.ALL, conversation_timeout)],
    },
    fallbacks=[CommandHandler("cancel", cmd_cancel), *_ACTION_ENTRY_POINTS],
    conversation_timeout=15 * 60,
    per_chat=True,
    per_user=True,
)


# --- /list, /find ------------------------------------------------------


def _list_keyboard(entries: list[Entry], page: int, total_pages: int, category: str | None) -> InlineKeyboardMarkup:
    cat_token = slugify(category) if category else "_"
    rows = [[InlineKeyboardButton(e.title, callback_data=f"ec:{short_id(e.id)}")] for e in entries]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(texts.BTN_PREV, callback_data=f"al:{page - 1}:{cat_token}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(texts.BTN_NEXT, callback_data=f"al:{page + 1}:{cat_token}"))
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(rows)


@admin_only
async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context.bot_data)
    category = " ".join(context.args) if context.args else None
    await _render_list(update.message.reply_text, services, page=0, category=category)


async def _render_list(sender, services: Services, *, page: int, category: str | None) -> None:
    entries = sorted(services.entry_cache.get_all(), key=lambda e: e.title)
    if category:
        entries = [e for e in entries if e.category == category]
    if not entries:
        await sender(texts.LIST_EMPTY)
        return
    page_entries, total_pages = paginate(entries, page, LIST_PAGE_SIZE)
    suffix = f" — {category}" if category else ""
    header = texts.LIST_HEADER.format(category_suffix=suffix, page=page + 1, total=total_pages)
    await sender(header, reply_markup=_list_keyboard(page_entries, page, total_pages, category))


@admin_only
async def cb_list_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, page_str, cat_token = query.data.split(":", 2)
    page = int(page_str)
    services = get_services(context.bot_data)
    category = None
    if cat_token != "_":
        for e in services.entry_cache.get_all():
            if slugify(e.category) == cat_token:
                category = e.category
                break
    entries = sorted(services.entry_cache.get_all(), key=lambda e: e.title)
    if category:
        entries = [e for e in entries if e.category == category]
    page_entries, total_pages = paginate(entries, page, LIST_PAGE_SIZE)
    suffix = f" — {category}" if category else ""
    header = texts.LIST_HEADER.format(category_suffix=suffix, page=page + 1, total=total_pages)
    await query.edit_message_text(header, reply_markup=_list_keyboard(page_entries, page, total_pages, category))


@admin_only
async def cmd_find(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context.bot_data)
    if not context.args:
        await update.message.reply_text(texts.FIND_ASK)
        return
    query_text, _ = normalize_text(" ".join(context.args))
    matches = [
        e
        for e in services.entry_cache.get_all()
        if query_text in normalize_text(e.title)[0]
        or query_text in normalize_text(e.answer)[0]
        or any(query_text in normalize_text(k)[0] for k in e.keywords)
    ]
    if not matches:
        await update.message.reply_text(texts.FIND_EMPTY)
        return
    page_entries, total_pages = paginate(matches, 0, LIST_PAGE_SIZE)
    header = texts.FIND_RESULTS_HEADER.format(count=len(matches))
    await update.message.reply_text(header, reply_markup=_list_keyboard(page_entries, 0, total_pages, None))


# --- entry card actions --------------------------------------------------


@admin_only
async def cb_open_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    token = query.data.split(":", 1)[1]
    services = get_services(context.bot_data)
    entry = _resolve_entry(services, token)
    if entry is None:
        await query.edit_message_text(texts.LIST_EMPTY)
        return
    await _edit_entry_card(query, entry)


@admin_only
async def cb_toggle_enabled(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    token = query.data.split(":")[2]
    services = get_services(context.bot_data)
    entry_id = services.entry_cache.resolve_short(token)
    if entry_id is None:
        return
    entry = await services.entry_repo.get(entry_id)
    if entry is None:
        return
    updated = await services.entry_repo.set_enabled(entry_id, not entry.enabled, actor_id=update.effective_user.id)
    await services.entry_cache.refresh(force=True)
    await _edit_entry_card(query, updated)


@admin_only
async def cb_toggle_visibility(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    token = query.data.split(":")[2]
    services = get_services(context.bot_data)
    entry_id = services.entry_cache.resolve_short(token)
    if entry_id is None:
        await query.answer()
        return
    entry = await services.entry_repo.get(entry_id)
    if entry is None:
        await query.answer()
        return
    new_visibility = "dm_only" if entry.visibility == "public" else "public"
    updated = await services.entry_repo.set_visibility(entry_id, new_visibility, actor_id=update.effective_user.id)
    await services.entry_cache.refresh(force=True)
    await query.answer(texts.VISIBILITY_CHANGED.format(visibility=new_visibility))
    await _edit_entry_card(query, updated)


@admin_only
async def cb_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    token = query.data.split(":")[2]
    services = get_services(context.bot_data)
    entry_id = services.entry_cache.resolve_short(token)
    if entry_id is None:
        return
    entry = await services.entry_repo.get(entry_id)
    if entry is None:
        return
    if entry.enabled:
        await services.entry_repo.set_enabled(entry_id, False, actor_id=update.effective_user.id)
        await services.entry_cache.refresh(force=True)
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(texts.BTN_DELETE_CONFIRM, callback_data=f"ec:delc:{token}")]]
        )
        await query.edit_message_text(texts.DELETE_SOFT_DONE, reply_markup=keyboard)
    else:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(texts.BTN_DELETE_CONFIRM, callback_data=f"ec:delc:{token}")]]
        )
        await query.edit_message_text(texts.DELETE_HARD_CONFIRM, reply_markup=keyboard)


@admin_only
async def cb_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    token = query.data.split(":")[2]
    services = get_services(context.bot_data)
    entry_id = services.entry_cache.resolve_short(token)
    if entry_id is None:
        return
    await services.entry_repo.delete(entry_id)
    await services.entry_cache.refresh(force=True)
    await query.edit_message_text(texts.DELETE_HARD_DONE)


@admin_only
async def cb_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, _, token, page_str = query.data.split(":")
    page = int(page_str)
    services = get_services(context.bot_data)
    entry_id = services.entry_cache.resolve_short(token)
    if entry_id is None:
        return
    revisions = sorted(await services.entry_repo.revisions(entry_id), key=lambda r: r["version"], reverse=True)
    if not revisions:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(texts.BTN_BACK, callback_data=f"ec:{token}")]]
        )
        await query.edit_message_text(texts.HISTORY_EMPTY, reply_markup=keyboard)
        return
    page_items, total_pages = paginate(revisions, page, HISTORY_PAGE_SIZE)
    body_parts = []
    for rev in page_items:
        preview = rev["answer"] if len(rev["answer"]) <= 150 else rev["answer"][:150] + "…"
        updated_at = rev["updated_at"]
        if isinstance(updated_at, datetime):
            updated_at = updated_at.strftime("%Y-%m-%d %H:%M")
        body_parts.append(texts.HISTORY_ITEM.format(version=rev["version"], updated_at=updated_at, answer_preview=preview))
    header = texts.HISTORY_HEADER.format(page=page + 1, total=total_pages)
    text = header + "\n\n" + "\n\n".join(body_parts)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(texts.BTN_PREV, callback_data=f"ec:hist:{token}:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(texts.BTN_NEXT, callback_data=f"ec:hist:{token}:{page + 1}"))
    rows = [nav] if nav else []
    rows.append([InlineKeyboardButton(texts.BTN_BACK, callback_data=f"ec:{token}")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))


HANDLERS = [
    CommandHandler("start", start),
    CommandHandler("help", cmd_help),
    admin_conversation,
    CommandHandler("list", cmd_list),
    CommandHandler("find", cmd_find),
    CallbackQueryHandler(cb_list_page, pattern=r"^al:"),
    CallbackQueryHandler(cb_open_card, pattern=r"^ec:[0-9a-f]+$"),
    CallbackQueryHandler(cb_toggle_enabled, pattern=r"^ec:tog:"),
    CallbackQueryHandler(cb_toggle_visibility, pattern=r"^ec:vis:"),
    CallbackQueryHandler(cb_delete_confirm, pattern=r"^ec:delc:"),
    CallbackQueryHandler(cb_delete, pattern=r"^ec:del:"),
    CallbackQueryHandler(cb_history, pattern=r"^ec:hist:"),
]
