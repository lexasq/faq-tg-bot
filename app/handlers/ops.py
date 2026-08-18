from __future__ import annotations

import difflib
import os
import time as time_module
from collections import Counter
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from app import texts
from app.handlers import menu
from app.handlers.admin_crud import admin_only
from app.logging_conf import get_logger
from app.matching.normalize import normalize_text
from app.matching.regex_matcher import decide_with_router_precedence
from app.rendering import render_answer
from app.repo.logs import FEEDBACK_LOG, MATCH_LOG, MISS_LOG
from app.services import get_services

logger = get_logger(__name__)

_PERIODS = {"7d": 7, "30d": 30}
_DEFAULT_PERIOD = "7d"
_NEAR_DUP_RATIO = 0.8

LIVENESS_FILE = os.environ.get("LIVENESS_FILE", "/tmp/faq-bot-liveness")


# --- /stats ----------------------------------------------------------------


def _period_from_args(args: list[str]) -> tuple[str, int]:
    if args and args[0] in _PERIODS:
        return args[0], _PERIODS[args[0]]
    return _DEFAULT_PERIOD, _PERIODS[_DEFAULT_PERIOD]


def _group_near_duplicate_misses(miss_logs: list[dict]) -> list[tuple[str, int]]:
    groups: list[list[str]] = []
    for m in miss_logs:
        text = m["text"]
        cleaned, _ = normalize_text(text)
        placed = False
        for group in groups:
            if difflib.SequenceMatcher(None, cleaned, normalize_text(group[0])[0]).ratio() > _NEAR_DUP_RATIO:
                group.append(text)
                placed = True
                break
        if not placed:
            groups.append([text])
    groups.sort(key=len, reverse=True)
    return [(g[0], len(g)) for g in groups]


@admin_only
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context.bot_data)
    period_label, days = _period_from_args(context.args)
    since = datetime.utcnow() - timedelta(days=days)

    match_logs = await services.log_repo.list_recent(MATCH_LOG, limit=2000, since=since)
    miss_logs = await services.log_repo.list_recent(MISS_LOG, limit=2000, since=since)
    feedback_logs = await services.log_repo.list_recent(FEEDBACK_LOG, limit=2000, since=since)

    replies = [m for m in match_logs if m["action"] in ("replied", "mention")]
    unique_askers = len({m["user_id"] for m in replies})
    downvotes = sum(1 for f in feedback_logs if f["vote"] == "down")
    downvote_rate = downvotes / len(feedback_logs) if feedback_logs else 0.0

    hits = Counter(m["entry_id"] for m in replies if m["entry_id"])
    top_entries = []
    for entry_id, count in hits.most_common(10):
        entry = services.entry_cache.get(entry_id)
        top_entries.append((entry.title if entry else entry_id, count))

    lines = [
        texts.STATS_HEADER.format(period=period_label),
        texts.STATS_BODY.format(
            replies=len(replies), unique_askers=unique_askers, misses=len(miss_logs), downvote_rate=downvote_rate
        ),
    ]
    if top_entries:
        lines.append(texts.STATS_TOP_ENTRIES_HEADER)
        lines.extend(
            texts.STATS_TOP_ENTRIES_ITEM.format(rank=i + 1, title=t, hits=c) for i, (t, c) in enumerate(top_entries)
        )

    top_misses = _group_near_duplicate_misses(miss_logs)[:5]
    if top_misses:
        lines.append(texts.STATS_TOP_MISSES_HEADER)
        lines.extend(
            texts.STATS_TOP_MISSES_ITEM.format(rank=i + 1, text=text[:60], count=count)
            for i, (text, count) in enumerate(top_misses)
        )

    if not replies and not miss_logs:
        lines.append(texts.STATS_NO_DATA)

    await update.message.reply_text("\n".join(lines))


# --- /review (miss queue) --------------------------------------------------


def _dedup_key(text: str) -> str:
    # Trailing "?"/"!" repeats ("хто голова?" vs "хто голова???") shouldn't
    # count as distinct questions for review purposes.
    cleaned, _ = normalize_text(text)
    return cleaned.rstrip("?")


async def reviewable_misses(services) -> list[dict]:
    """Newest-first, deduplicated by normalized text, unhandled only."""
    all_misses = await services.log_repo.list_recent(MISS_LOG, limit=500)
    seen: set[str] = set()
    result = []
    for m in all_misses:
        if m.get("handled"):
            continue
        key = _dedup_key(m["text"])
        if key in seen:
            continue
        seen.add(key)
        result.append(m)
    return result


def _review_keyboard(item: dict, index: int, total: int) -> InlineKeyboardMarkup:
    nav = []
    if index > 0:
        nav.append(InlineKeyboardButton(texts.BTN_PREV, callback_data=f"rv:{index - 1}"))
    if index < total - 1:
        nav.append(InlineKeyboardButton(texts.BTN_NEXT, callback_data=f"rv:{index + 1}"))
    rows = [nav] if nav else []
    rows.append([InlineKeyboardButton(texts.BTN_REVIEW_CREATE, callback_data=f"rvc:{item['id']}")])
    rows.append([InlineKeyboardButton(texts.BTN_REVIEW_LINK, callback_data=f"rvl:{item['id']}")])
    rows.append([InlineKeyboardButton(texts.BTN_REVIEW_IGNORE, callback_data=f"rvi:{item['id']}")])
    return InlineKeyboardMarkup(rows)


async def _render_review(send, services, index: int) -> None:
    misses = await reviewable_misses(services)
    if not misses:
        await send(texts.REVIEW_EMPTY)
        return
    index = max(0, min(index, len(misses) - 1))
    item = misses[index]
    text = texts.REVIEW_ITEM.format(
        index=index + 1, total=len(misses), score=item.get("top_score", 0.0), text=item["text"]
    )
    await send(text, reply_markup=_review_keyboard(item, index, len(misses)))


@admin_only
async def cmd_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context.bot_data)
    await _render_review(update.message.reply_text, services, 0)


@admin_only
async def cb_review_nav(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    index = int(query.data.split(":", 1)[1])
    services = get_services(context.bot_data)
    await _render_review(query.edit_message_text, services, index)


@admin_only
async def cb_review_ignore(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    doc_id = query.data.split(":", 1)[1]
    services = get_services(context.bot_data)
    await services.log_repo.mark_handled(MISS_LOG, doc_id)
    await query.edit_message_text(texts.REVIEW_IGNORED)


# --- /test -------------------------------------------------------------


@admin_only
async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(texts.TEST_ASK_TEXT)
        return
    text = " ".join(context.args)
    services = get_services(context.bot_data)
    entries = services.entry_cache.get_all_enabled()
    entries_by_id = {e.id: e for e in entries}
    results = await services.matcher.match(text, entries)

    lines = [texts.TEST_HEADER.format(text=text)]
    if not results:
        lines.append(texts.TEST_NO_MATCH)
    for i, r in enumerate(results[:3]):
        entry = entries_by_id.get(r.entry_id)
        lines.append(
            texts.TEST_RESULT_ITEM.format(rank=i + 1, title=entry.title if entry else r.entry_id, score=r.score, reason=r.reason)
        )

    config = services.entry_cache.config
    group_decision = decide_with_router_precedence(results, entries_by_id, config.auto_threshold)
    mention_decision = decide_with_router_precedence(results, entries_by_id, config.suggest_threshold)
    group_text = entries_by_id[group_decision.entry_id].title if group_decision else "мовчати"
    mention_text = entries_by_id[mention_decision.entry_id].title if mention_decision else "не знайшов"
    lines.append(texts.TEST_WOULD_DO.format(group=group_text, mention=mention_text))

    await update.message.reply_text("\n".join(lines))

    # /test only shows scores above — also show the actual rendered
    # answer text (what an end user would really see), since the debug
    # breakdown alone doesn't answer "what would the bot say".
    preview_decision = group_decision or mention_decision
    if preview_decision is not None:
        preview_entry = entries_by_id.get(preview_decision.entry_id)
        if preview_entry is not None:
            if preview_entry.type == "router":
                preview_text, _kb = menu.entry_view_content(preview_entry, services, in_group=True)
            else:
                preview_text = render_answer(preview_entry)
            await update.message.reply_text(
                texts.TEST_PREVIEW_HEADER + preview_text, parse_mode="HTML"
            )


# --- /health + liveness -----------------------------------------------


@admin_only
async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(texts.HEALTH_OK)


async def touch_liveness_file(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        with open(LIVENESS_FILE, "w") as f:
            f.write(str(time_module.time()))
    except OSError:
        logger.warning("liveness_touch_failed", exc_info=True)


HANDLERS = [
    CommandHandler("stats", cmd_stats),
    CommandHandler("review", cmd_review),
    CommandHandler("test", cmd_test),
    CommandHandler("health", cmd_health),
    CallbackQueryHandler(cb_review_nav, pattern=r"^rv:"),
    CallbackQueryHandler(cb_review_ignore, pattern=r"^rvi:"),
]
