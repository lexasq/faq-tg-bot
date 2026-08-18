from __future__ import annotations

from html import escape
from typing import TypeVar

from app.models import Entry

T = TypeVar("T")


def render_answer(entry: Entry) -> str:
    """The exact text sent for an autoreply, in /faq, and in previews.
    The title is admin free-text so it's escaped; the answer is HTML the
    admin composed on purpose (seed content relies on <b> tags rendering),
    so it is sent through as-is."""
    title = escape(entry.title)
    return f"📌 <b>{title}</b>\n\n{entry.answer}"


def paginate(items: list[T], page: int, per_page: int) -> tuple[list[T], int]:
    total_pages = max(1, (len(items) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    return items[start : start + per_page], total_pages
