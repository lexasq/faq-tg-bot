"""Regression test for a bug caught mid bulk-import against real Firestore:
google-cloud-firestore's encoder only knows datetime.datetime, not
datetime.date, and raises TypeError('Cannot convert to a Firestore
Value', ...) on Entry.review_after. FakeStore never caught this — it
just stores whatever Python object it's given, with no serialization
layer at all.
"""
from datetime import date, datetime

from app.repo.firestore import _decode_entry_dates, _encode_entry_dates


def test_encode_converts_date_to_datetime():
    encoded = _encode_entry_dates({"title": "x", "review_after": date(2027, 2, 1)})
    assert isinstance(encoded["review_after"], datetime)
    assert encoded["review_after"].date() == date(2027, 2, 1)


def test_encode_leaves_none_alone():
    encoded = _encode_entry_dates({"title": "x", "review_after": None})
    assert encoded["review_after"] is None


def test_encode_does_not_mutate_input():
    original = {"title": "x", "review_after": date(2027, 2, 1)}
    _encode_entry_dates(original)
    assert original["review_after"] == date(2027, 2, 1)  # still a plain date


def test_decode_converts_datetime_back_to_date():
    decoded = _decode_entry_dates({"title": "x", "review_after": datetime(2027, 2, 1, 0, 0)})
    assert decoded["review_after"] == date(2027, 2, 1)
    assert type(decoded["review_after"]) is date


def test_round_trip_preserves_the_date():
    original = date(2026, 11, 1)
    round_tripped = _decode_entry_dates(_encode_entry_dates({"review_after": original}))["review_after"]
    assert round_tripped == original
