"""Nightly backup: dumps every FAQ entry to a timestamped .md file (the
same strict block format /export uses) and prunes anything past the last
14 archives. Run via cron (see deploy/backup.sh) — this talks to
Firestore directly, not through Telegram.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

from app.config import get_settings
from app.importers.text_blocks import render_strict_export
from app.repo.entries import EntryRepo
from app.repo.firestore import FirestoreStore, build_firestore_client

KEEP_LAST = 14


async def run_backup(entry_repo: EntryRepo, backup_dir: Path) -> Path:
    entries = await entry_repo.list_all()

    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    out_path = backup_dir / f"faq_backup_{stamp}.md"
    out_path.write_text(render_strict_export(entries), encoding="utf-8")
    print(f"wrote {out_path} ({len(entries)} entries)")

    archives = sorted(backup_dir.glob("faq_backup_*.md"))
    for stale in archives[:-KEEP_LAST]:
        stale.unlink()
        print(f"pruned {stale}")

    return out_path


async def main(backup_dir: Path) -> None:
    settings = get_settings()
    store = FirestoreStore(build_firestore_client(settings))
    await run_backup(EntryRepo(store), backup_dir)


if __name__ == "__main__":
    target_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/opt/faq-bot/backups")
    asyncio.run(main(target_dir))
