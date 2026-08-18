import asyncio
from datetime import datetime, timedelta

from app.repo.logs import FEEDBACK_LOG, MATCH_LOG, MISS_LOG, LogRepo
from tests.fakes import FakeStore


async def _flush():
    # log_* methods are fire-and-forget (asyncio.create_task); give the
    # event loop one pass so the write actually lands before we assert.
    await asyncio.sleep(0)


async def test_log_match_writes_truncated_text():
    store = FakeStore()
    repo = LogRepo(store)

    repo.log_match(chat_id=1, user_id=2, text="x" * 600, entry_id="e1", score=0.9, action="replied")
    await _flush()

    logs = await store.list_logs(MATCH_LOG)
    assert len(logs) == 1
    assert len(logs[0]["text"]) == 500
    assert logs[0]["entry_id"] == "e1"


async def test_log_miss_and_feedback():
    store = FakeStore()
    repo = LogRepo(store)

    repo.log_miss(chat_id=1, user_id=2, text="хто голова?", top_entry_id=None, top_score=0.2)
    repo.log_feedback(match_log_id="abc", entry_id="e1", user_id=2, vote="up")
    await _flush()

    assert len(await store.list_logs(MISS_LOG)) == 1
    assert len(await store.list_logs(FEEDBACK_LOG)) == 1


async def test_list_recent_since_filters_out_older_entries():
    # /stats used to fetch up to 2000 raw docs per collection and filter
    # by date in Python; `since` now pushes that filter down so old
    # entries are never even returned, not just fetched-then-discarded.
    store = FakeStore()
    repo = LogRepo(store)
    now = datetime.utcnow()

    await store.add_log(MATCH_LOG, {"chat_id": 1, "user_id": 1, "ts": now - timedelta(days=40)})
    await store.add_log(MATCH_LOG, {"chat_id": 1, "user_id": 2, "ts": now - timedelta(days=1)})

    recent = await repo.list_recent(MATCH_LOG, since=now - timedelta(days=7))
    assert len(recent) == 1
    assert recent[0]["user_id"] == 2

    everything = await repo.list_recent(MATCH_LOG)
    assert len(everything) == 2


async def test_list_recent_since_still_respects_limit():
    store = FakeStore()
    repo = LogRepo(store)
    now = datetime.utcnow()
    for i in range(5):
        await store.add_log(MATCH_LOG, {"chat_id": 1, "user_id": i, "ts": now - timedelta(minutes=i)})

    recent = await repo.list_recent(MATCH_LOG, limit=2, since=now - timedelta(days=1))
    assert len(recent) == 2
    assert recent[0]["user_id"] == 0  # newest first


async def test_log_write_failure_does_not_raise():
    class BrokenStore(FakeStore):
        async def add_log(self, collection, data):
            raise RuntimeError("firestore unavailable")

    store = BrokenStore()
    repo = LogRepo(store)

    repo.log_match(chat_id=1, user_id=2, text="hi", entry_id=None, score=0.0, action="silent")
    await _flush()  # must not raise despite the store failing
