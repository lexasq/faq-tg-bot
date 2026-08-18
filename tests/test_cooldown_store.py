from app.handlers.group import CooldownStore


def test_is_cooling_down_within_window(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr("time.monotonic", lambda: t[0])
    store = CooldownStore()

    assert store.is_cooling_down(1, "e1", 900) is False
    store.record_reply(1, "e1")
    assert store.is_cooling_down(1, "e1", 900) is True

    t[0] += 901
    assert store.is_cooling_down(1, "e1", 900) is False


def test_hourly_cap_resets_after_an_hour(monkeypatch):
    t = [0.0]
    monkeypatch.setattr("time.monotonic", lambda: t[0])
    store = CooldownStore()

    for _ in range(5):
        store.record_reply(1, "e1")
    assert store.hourly_cap_reached(1, cap=5) is True

    t[0] += 3601
    assert store.hourly_cap_reached(1, cap=5) is False


def test_cooldown_and_cap_are_per_chat():
    store = CooldownStore()
    store.record_reply(1, "e1")
    assert store.is_cooling_down(2, "e1", 900) is False
