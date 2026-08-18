"""Bulk-loads FAQ entries from a strict Q:/CAT:/KEYS:/.../A: text file
straight into Firestore, bypassing the /import Telegram conversation.

Reuses the exact same candidate-building and new/updated/unchanged logic
as app.handlers.admin_import (the bot's own /import flow), so the result
is identical to pasting the same content through /import and confirming
— just without needing to paste a multi-KB block into a chat window.

Usage:
    python scripts/bulk_import.py <path-to-md> <admin-user-id>
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from app.config import get_settings
from app.handlers.admin_import import _candidate_from_strict, _diff_status
from app.importers import text_blocks
from app.importers.validate import validate_text
from app.models import Entry, slugify
from app.repo.entries import EntryRepo
from app.repo.firestore import FirestoreStore, build_firestore_client


def extract_strict_block(text: str) -> str:
    """A seed file is typically a markdown doc with prose around a fenced
    code block holding the actual Q:/... content (see
    tests/fixtures/faq_example.md) — pull just that. A file that's already
    bare Q:/... content passes through unchanged."""
    if text.lstrip().startswith("Q:"):
        return text
    marker = "```\nQ:"
    if marker in text:
        start = text.index(marker) + len("```\n")
        end = text.index("\n```", start)
        return text[start:end]
    return text


async def bulk_import(entry_repo: EntryRepo, content: str, actor_id: int) -> None:
    if not text_blocks.is_strict_format(content):
        raise SystemExit(
            "content must be in the strict Q:/CAT:/.../A: format (see tests/fixtures/faq_example.md)"
        )

    parsed_entries, errors = text_blocks.parse_strict(content)
    for e in errors:
        print(f"PARSE ERROR line {e.line}: {e.message}")

    candidates = [_candidate_from_strict(e) for e in parsed_entries]
    created = updated = unchanged = 0

    for c in candidates:
        slug = slugify(c["title"])
        existing = await entry_repo.get(slug)
        status = _diff_status(existing, c)

        for w in validate_text(c["answer"]):
            print(f"WARNING [{c['title']}]: {w.message}")

        if status == "unchanged":
            unchanged += 1
            continue

        if existing is not None:
            entry = existing.model_copy(
                update={
                    "title": c["title"],
                    "category": c["category"],
                    "answer": c["answer"],
                    "patterns": c["patterns"],
                    "visibility": c["visibility"],
                    "type": c["type"],
                    "children": c["children"],
                    "review_after": c["review_after"],
                }
            )
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

        await entry_repo.save(entry, actor_id=actor_id)
        print(f"{'created' if status == 'new' else 'updated'}: {c['title']} ({slug})")

    print(f"\nDone: {created} created, {updated} updated, {unchanged} unchanged.")


async def main(path: Path, actor_id: int) -> None:
    settings = get_settings()
    store = FirestoreStore(build_firestore_client(settings))
    entry_repo = EntryRepo(store)
    content = extract_strict_block(path.read_text(encoding="utf-8"))
    await bulk_import(entry_repo, content, actor_id)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit("usage: python scripts/bulk_import.py <path-to-md> <admin-user-id>")
    asyncio.run(main(Path(sys.argv[1]), int(sys.argv[2])))
