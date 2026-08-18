"""Regression test for a bug caught during live Firestore verification:
config/bot doesn't exist until the very first entry is saved. Firestore's
.update() requires the target document to already exist and 404s
otherwise — only .set(..., merge=True) creates-or-merges. FakeStore
doesn't model that distinction (it pre-seeds config in __init__), so the
whole test suite passed against the fake while this broke on a fresh
real database. Guard the actual FirestoreStore source directly since
faithfully modeling Firestore's create-vs-update semantics in the fake
is a bigger undertaking than this bug warrants.
"""
from pathlib import Path

SOURCE = (Path(__file__).parent.parent / "app" / "repo" / "firestore.py").read_text(encoding="utf-8")


def test_config_writes_never_use_bare_update():
    # bare `.update(` on config_ref would 404 against a brand-new database
    assert "transaction.update(config_ref" not in SOURCE
    assert "config_ref.update(" not in SOURCE


def test_config_writes_use_set_with_merge():
    assert SOURCE.count("config_ref, {\"entries_version\": firestore.Increment(1)}, merge=True") >= 1 or \
        SOURCE.count('config_ref.set({"entries_version": firestore.Increment(1)}, merge=True)') >= 1
