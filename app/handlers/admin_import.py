from __future__ import annotations

import csv
import io

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from app import texts
from app.handlers.admin_crud import admin_only, suggest_patterns
from app.importers import freeform, text_blocks
from app.importers.validate import validate_text
from app.models import Entry, slugify
from app.services import get_services

MAX_FILE_SIZE = 1_000_000

(IMPORT_WAIT_CONTENT, IMPORT_FIXUP, IMPORT_CONFIRM) = range(3)

Candidate = dict  # {title, category, answer, patterns, visibility, type, children, review_after}


def _candidate_from_strict(e: text_blocks.ParsedEntry) -> Candidate:
    return {
        "title": e.title,
        "category": e.category,
        "answer": e.answer,
        "patterns": e.patterns,
        "visibility": e.visibility,
        "type": e.type,
        "children": e.children,
        "review_after": e.review_after,
    }


def _candidate_from_freeform(title: str, body: str) -> Candidate:
    return {
        "title": title,
        "category": "Загальне",
        "answer": body,
        "patterns": suggest_patterns(title),
        "visibility": "public",
        "type": "answer",
        "children": [],
        "review_after": None,
    }


_COMPARE_FIELDS = ("category", "answer", "patterns", "visibility", "type", "children", "review_after")


def _diff_status(existing: Entry | None, candidate: Candidate) -> str:
    if existing is None:
        return "new"
    if all(getattr(existing, f) == candidate[f] for f in _COMPARE_FIELDS):
        return "unchanged"
    return "updated"


def _render_csv(entries: list[Entry]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["title", "category", "answer", "patterns"])
    for e in entries:
        writer.writerow([e.title, e.category, e.answer, "|".join(e.patterns)])
    return buf.getvalue()


# --- /import conversation ---------------------------------------------


@admin_only
async def cmd_import(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    for key in ("import_candidates", "import_orphans", "import_errors", "import_awaiting_title"):
        context.user_data.pop(key, None)
    await update.message.reply_text(texts.IMPORT_ASK_CONTENT)
    return IMPORT_WAIT_CONTENT


async def import_receive_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.message
    if message.document is not None:
        document = message.document
        if document.file_size and document.file_size > MAX_FILE_SIZE:
            await message.reply_text(texts.IMPORT_FILE_TOO_LARGE)
            return IMPORT_WAIT_CONTENT
        telegram_file = await context.bot.get_file(document.file_id)
        raw = await telegram_file.download_as_bytearray()
        content = bytes(raw).decode("utf-8", errors="replace")
    else:
        content = message.text or ""

    if not content.strip():
        await message.reply_text(texts.IMPORT_EMPTY)
        return IMPORT_WAIT_CONTENT

    candidates: list[Candidate] = []
    orphans: list[dict] = []
    errors: list[str] = []

    if text_blocks.is_strict_format(content):
        parsed_entries, parse_errors = text_blocks.parse_strict(content)
        candidates = [_candidate_from_strict(e) for e in parsed_entries]
        errors = [f"Рядок {e.line}: {e.message}" for e in parse_errors]
    else:
        for block in freeform.segment_freeform(content):
            if block.confidence == "orphan":
                orphans.append({"body": block.body})
            else:
                candidates.append(_candidate_from_freeform(block.title, block.body))

    context.user_data["import_candidates"] = candidates
    context.user_data["import_orphans"] = orphans
    context.user_data["import_errors"] = errors

    return await _process_next_orphan_or_summary(message, context)


async def _process_next_orphan_or_summary(message, context: ContextTypes.DEFAULT_TYPE) -> int:
    orphans = context.user_data.get("import_orphans", [])
    if not orphans:
        return await _show_dry_run(message, context)

    orphan = orphans[0]
    body = orphan["body"]
    preview = body if len(body) <= 300 else body[:300] + "…"
    candidates = context.user_data.get("import_candidates", [])

    rows = [[InlineKeyboardButton(texts.BTN_SET_TITLE, callback_data="imfix:title")]]
    if candidates:
        rows.append([InlineKeyboardButton(texts.BTN_ATTACH_PREVIOUS, callback_data="imfix:attach")])
    rows.append([InlineKeyboardButton(texts.BTN_SKIP, callback_data="imfix:skip")])

    text = texts.IMPORT_ORPHAN.format(remaining=len(orphans), preview=preview)
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows))
    return IMPORT_FIXUP


async def import_fixup_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data.split(":", 1)[1]

    orphans = context.user_data.get("import_orphans", [])
    if not orphans:
        return await _show_dry_run(query.message, context)
    orphan = orphans[0]

    if action == "title":
        context.user_data["import_awaiting_title"] = True
        await query.edit_message_text(texts.IMPORT_ASK_TITLE)
        return IMPORT_FIXUP

    if action == "attach":
        candidates = context.user_data.get("import_candidates", [])
        if candidates:
            candidates[-1]["answer"] = candidates[-1]["answer"] + "\n\n" + orphan["body"]
        orphans.pop(0)
        return await _process_next_orphan_or_summary(query.message, context)

    # "skip"
    orphans.pop(0)
    return await _process_next_orphan_or_summary(query.message, context)


async def import_fixup_title_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not context.user_data.get("import_awaiting_title"):
        return IMPORT_FIXUP
    context.user_data["import_awaiting_title"] = False

    orphans = context.user_data.get("import_orphans", [])
    if not orphans:
        return await _show_dry_run(update.message, context)
    orphan = orphans.pop(0)

    title = update.message.text.strip()
    if title:
        candidates = context.user_data.setdefault("import_candidates", [])
        candidates.append(_candidate_from_freeform(title, orphan["body"]))
    return await _process_next_orphan_or_summary(update.message, context)


async def _show_dry_run(message, context: ContextTypes.DEFAULT_TYPE) -> int:
    services = get_services(context.bot_data)
    candidates: list[Candidate] = context.user_data.get("import_candidates", [])
    errors: list[str] = context.user_data.get("import_errors", [])

    if not candidates:
        if errors:
            await message.reply_text(texts.IMPORT_ERRORS_HEADER + "\n" + "\n".join(f"• {e}" for e in errors[:10]))
        else:
            await message.reply_text(texts.IMPORT_NOTHING_TO_IMPORT)
        context.user_data.clear()
        return ConversationHandler.END

    all_slugs = {slugify(c["title"]) for c in candidates} | {e.id for e in services.entry_cache.get_all()}

    counts = {"new": 0, "updated": 0, "unchanged": 0}
    warnings_by_title: dict[str, list[str]] = {}
    diffs: list[str] = []

    for c in candidates:
        slug = slugify(c["title"])
        existing = await services.entry_repo.get(slug)
        status = _diff_status(existing, c)
        counts[status] += 1
        if status == "updated":
            diffs.append(f"«{c['title']}»: {existing.answer[:80]!r} -> {c['answer'][:80]!r}")

        warnings = [w.message for w in validate_text(c["answer"])]
        if c["type"] == "router":
            missing = [child for child in c["children"] if child not in all_slugs]
            if missing:
                warnings.append(f"router children not found: {', '.join(missing)}")
        if warnings:
            warnings_by_title[c["title"]] = warnings

    lines = [
        texts.IMPORT_SUMMARY.format(
            total=len(candidates), new=counts["new"], updated=counts["updated"], unchanged=counts["unchanged"]
        )
    ]
    if errors:
        lines.append(texts.IMPORT_ERRORS_HEADER)
        lines.extend(f"• {e}" for e in errors[:10])
    if warnings_by_title:
        lines.append(texts.IMPORT_WARNINGS_HEADER)
        for title, msgs in list(warnings_by_title.items())[:10]:
            lines.append(f"«{title}»: " + "; ".join(msgs))
    if diffs:
        lines.append(texts.IMPORT_DIFFS_HEADER)
        lines.extend(diffs[:5])

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(texts.BTN_CONFIRM, callback_data="imconf:yes"),
          InlineKeyboardButton(texts.BTN_CANCEL, callback_data="imconf:no")]]
    )
    await message.reply_text("\n".join(lines), reply_markup=keyboard)
    return IMPORT_CONFIRM


async def import_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":", 1)[1]
    if choice == "no":
        await query.edit_message_text(texts.CANCELLED)
        context.user_data.clear()
        return ConversationHandler.END

    services = get_services(context.bot_data)
    actor_id = update.effective_user.id
    candidates: list[Candidate] = context.user_data.get("import_candidates", [])

    created = updated = unchanged = 0
    for c in candidates:
        slug = slugify(c["title"])
        existing = await services.entry_repo.get(slug)
        status = _diff_status(existing, c)
        if status == "unchanged":
            unchanged += 1
            continue

        if existing is not None:
            entry = existing.model_copy(update={f: c[f] for f in _COMPARE_FIELDS} | {"title": c["title"]})
            updated += 1
        else:
            entry = Entry.create(
                title=c["title"],
                answer=c["answer"],
                updated_by=actor_id,
                category=c["category"],
                patterns=c["patterns"],
                visibility=c["visibility"],
                type=c["type"],
                children=c["children"],
                review_after=c["review_after"],
            )
            created += 1
        await services.entry_repo.save(entry, actor_id=actor_id)

    await services.entry_cache.refresh(force=True)
    await query.edit_message_text(texts.IMPORT_DONE.format(created=created, updated=updated))
    context.user_data.clear()
    return ConversationHandler.END


async def import_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    if update and update.effective_message:
        await update.effective_message.reply_text(texts.SESSION_TIMED_OUT)


async def import_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(texts.CANCELLED)
    return ConversationHandler.END


admin_import_conversation = ConversationHandler(
    entry_points=[CommandHandler("import", cmd_import)],
    states={
        IMPORT_WAIT_CONTENT: [MessageHandler((filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, import_receive_content)],
        IMPORT_FIXUP: [
            CallbackQueryHandler(import_fixup_choice, pattern=r"^imfix:"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, import_fixup_title_received),
        ],
        IMPORT_CONFIRM: [CallbackQueryHandler(import_confirm, pattern=r"^imconf:")],
        ConversationHandler.TIMEOUT: [MessageHandler(filters.ALL, import_timeout)],
    },
    fallbacks=[CommandHandler("cancel", import_cancel)],
    conversation_timeout=15 * 60,
    per_chat=True,
    per_user=True,
)


# --- /export -------------------------------------------------------------


@admin_only
async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = get_services(context.bot_data)
    entries = sorted(services.entry_cache.get_all(), key=lambda e: e.title)
    if not entries:
        await update.message.reply_text(texts.EXPORT_EMPTY)
        return

    md_content = text_blocks.render_strict_export(entries)
    csv_content = _render_csv(entries)

    await update.message.reply_document(
        document=InputFile(io.BytesIO(md_content.encode("utf-8")), filename="faq_export.md")
    )
    await update.message.reply_document(
        document=InputFile(io.BytesIO(csv_content.encode("utf-8")), filename="faq_export.csv")
    )


HANDLERS = [admin_import_conversation, CommandHandler("export", cmd_export)]
