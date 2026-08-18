"""Integration tests against a real Cloud Firestore emulator.

Unlike the rest of the suite, these hit actual Firestore wire-format
behavior (field encoding, .update()-requires-existing-doc semantics,
transactions) — the exact class of bug that FakeStore's plain-dict
in-memory model can never catch, and the exact class that slipped
through to the live bot three times in one session: a bare
datetime.date couldn't be encoded, .update() 404'd on a brand-new
config/bot document, and (relatedly) PYTHONPATH broke script
invocation. The first two were Firestore-specific; this file exists so
the next one like them gets caught here instead of in production.

Opt-in twice over, deliberately:
1. A plain `pytest` run skips this whole module instantly unless
   RUN_FIRESTORE_EMULATOR_TESTS=1 is set (or FIRESTORE_EMULATOR_HOST
   already points at something) — otherwise, on any machine that
   happens to have firebase-tools installed, every single `pytest`
   invocation would eat a ~15s JVM startup it usually doesn't need.
2. Even when opted in, it self-skips if `firebase` isn't on PATH or a
   JDK 21+ runtime for the bundled emulator isn't available — this is
   local developer safety-net infrastructure, not something CI or the
   Docker image needs to carry.

    RUN_FIRESTORE_EMULATOR_TESTS=1 pytest tests/test_firestore_emulator.py

Auto-starts the emulator once per test session and tears it down after;
set FIRESTORE_EMULATOR_HOST yourself to point at an emulator you're
already running (e.g. in another terminal) and this reuses it instead
of spawning its own — RUN_FIRESTORE_EMULATOR_TESTS isn't needed in that
case, an explicit FIRESTORE_EMULATOR_HOST is opt-in enough on its own.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("google.cloud.firestore")

if not os.environ.get("FIRESTORE_EMULATOR_HOST") and os.environ.get("RUN_FIRESTORE_EMULATOR_TESTS") != "1":
    pytest.skip(
        "Firestore emulator tests are opt-in — set RUN_FIRESTORE_EMULATOR_TESTS=1 "
        "(or FIRESTORE_EMULATOR_HOST) to run them. See README.",
        allow_module_level=True,
    )

EMULATOR_HOST = "127.0.0.1"
EMULATOR_PORT = 8080
PROJECT_ID = "demo-nivki7-test"

# Common install locations for a JDK 21+ runtime, checked in addition to
# PATH — firebase-tools' bundled emulator needs 21+, but PATH's default
# `java` may well be an older version installed for something else.
_JDK21_CANDIDATES = [
    Path("C:/Program Files/Eclipse Adoptium"),
    Path("C:/Program Files/Java"),
]


def _find_jdk21_bin() -> str | None:
    for base in _JDK21_CANDIDATES:
        if not base.is_dir():
            continue
        for entry in sorted(base.glob("jdk-21*"), reverse=True):
            java = entry / "bin" / "java.exe"
            if java.exists():
                return str(entry / "bin")
    return None


def _kill_process_tree(proc: subprocess.Popen) -> None:
    # `firebase emulators:start` is a Node.js wrapper that spawns the
    # actual emulator as a child java process. On Windows,
    # proc.terminate() only kills the Node wrapper — the java child gets
    # orphaned and keeps running (and keeps holding the port) forever.
    # taskkill /T kills the whole tree; POSIX's terminate() doesn't have
    # this problem in practice for this tool.
    if sys.platform == "win32":
        with contextlib.suppress(Exception):
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=15,
            )
    else:
        with contextlib.suppress(Exception):
            proc.terminate()
            proc.wait(timeout=10)


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    with contextlib.suppress(OSError):
        with socket.create_connection((host, port), timeout=timeout):
            return True
    return False


@pytest.fixture(scope="session")
def firestore_emulator():
    if os.environ.get("FIRESTORE_EMULATOR_HOST"):
        yield os.environ["FIRESTORE_EMULATOR_HOST"]
        return

    firebase_bin = shutil.which("firebase")
    if firebase_bin is None:
        pytest.skip("firebase-tools not installed (npm i -g firebase-tools) — skipping emulator tests")

    if _port_open(EMULATOR_HOST, EMULATOR_PORT):
        os.environ["FIRESTORE_EMULATOR_HOST"] = f"{EMULATOR_HOST}:{EMULATOR_PORT}"
        yield os.environ["FIRESTORE_EMULATOR_HOST"]
        return

    env = os.environ.copy()
    jdk21_bin = _find_jdk21_bin()
    if jdk21_bin:
        env["PATH"] = jdk21_bin + os.pathsep + env.get("PATH", "")

    workdir = Path(__file__).parent / ".firestore_emulator_workdir"
    workdir.mkdir(exist_ok=True)
    (workdir / "firebase.json").write_text('{"firestore": {}}', encoding="utf-8")

    proc = subprocess.Popen(
        [firebase_bin, "emulators:start", "--only", "firestore", "--project", PROJECT_ID],
        cwd=workdir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    deadline = time.monotonic() + 90
    ready = False
    while time.monotonic() < deadline:
        if _port_open(EMULATOR_HOST, EMULATOR_PORT):
            ready = True
            break
        if proc.poll() is not None:
            break
        time.sleep(0.5)

    if not ready:
        output = proc.stdout.read() if proc.stdout else ""
        _kill_process_tree(proc)
        pytest.skip(f"Firestore emulator did not become ready (needs JDK 21+):\n{output[-2000:]}")

    os.environ["FIRESTORE_EMULATOR_HOST"] = f"{EMULATOR_HOST}:{EMULATOR_PORT}"
    yield os.environ["FIRESTORE_EMULATOR_HOST"]

    _kill_process_tree(proc)
    os.environ.pop("FIRESTORE_EMULATOR_HOST", None)


@pytest.fixture
async def real_store(firestore_emulator):
    from google.cloud import firestore as gcf

    from app.repo.firestore import FirestoreStore

    client = gcf.AsyncClient(project=PROJECT_ID)
    yield FirestoreStore(client)


@pytest.fixture
def unique_title(request) -> str:
    # keeps each test's data from colliding with another's in the same
    # (session-lived, never wiped between tests) emulator instance
    return f"{request.node.name}-{int(time.time() * 1000)}"


async def test_entry_with_review_after_date_round_trips(real_store, unique_title):
    from app.models import Entry
    from app.repo.entries import EntryRepo

    repo = EntryRepo(real_store)
    entry = Entry.create(
        title=unique_title, answer="ok", updated_by=1, review_after=date(2027, 6, 1)
    )

    saved = await repo.save(entry, actor_id=1)
    assert saved.version == 1

    fetched = await repo.get(saved.id)
    assert fetched is not None
    assert fetched.review_after == date(2027, 6, 1)
    assert type(fetched.review_after) is date


async def test_first_ever_write_creates_config_bot_document(real_store, unique_title):
    # regression: config/bot doesn't exist until the first entry is saved.
    # transaction.update() 404s on a nonexistent doc; only .set(merge=True)
    # creates-or-merges. This is impossible to catch against FakeStore,
    # which pre-seeds config in its constructor.
    from app.models import Entry
    from app.repo.entries import EntryRepo

    repo = EntryRepo(real_store)
    before = await real_store.get_config()
    version_before = before.get("entries_version", 0)

    await repo.save(Entry.create(title=unique_title, answer="ok", updated_by=1), actor_id=1)

    after = await real_store.get_config()
    assert after.get("entries_version", 0) == version_before + 1


async def test_editing_an_entry_writes_a_real_revision_snapshot(real_store, unique_title):
    from app.models import Entry
    from app.repo.entries import EntryRepo

    repo = EntryRepo(real_store)
    first = await repo.save(Entry.create(title=unique_title, answer="v1", updated_by=1), actor_id=1)
    updated = await repo.save(first.model_copy(update={"answer": "v2"}), actor_id=1)

    assert updated.version == 2
    revisions = await repo.revisions(first.id)
    assert len(revisions) == 1
    assert revisions[0]["answer"] == "v1"
    assert revisions[0]["version"] == 1


async def test_admin_and_log_round_trip_against_real_firestore(real_store):
    from app.repo.admins import AdminRepo
    from app.repo.logs import MATCH_LOG, LogRepo

    admins = AdminRepo(real_store)
    user_id = int(time.time() * 1000) % 1_000_000_000
    await admins.add(user_id, name="Emulator Test", role="owner", added_by=user_id)
    assert await admins.is_owner(user_id) is True

    logs = LogRepo(real_store)
    logs.log_match(chat_id=1, user_id=user_id, text="test", entry_id=None, score=0.5, action="silent")
    import asyncio

    await asyncio.sleep(0.2)  # fire-and-forget write needs a moment to land
    recent = await logs.list_recent(MATCH_LOG, limit=50)
    assert any(r["user_id"] == user_id for r in recent)
