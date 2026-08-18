from app.matching.regex_matcher import decide_with_router_precedence
from app.models import Entry, MatchResult


def _entry(title, type_="answer", **kwargs):
    return Entry.create(title=title, answer="a", updated_by=1, type=type_, **kwargs)


def test_leaf_wins_when_it_clears_router_by_015():
    router = _entry("Router", type_="router")
    leaf = _entry("Leaf")
    results = [MatchResult(entry_id=leaf.id, score=0.80), MatchResult(entry_id=router.id, score=0.60)]
    entries_by_id = {router.id: router, leaf.id: leaf}

    decision = decide_with_router_precedence(results, entries_by_id, threshold=0.45)
    assert decision.entry_id == leaf.id


def test_router_wins_when_leaf_margin_is_below_015():
    router = _entry("Router", type_="router")
    leaf = _entry("Leaf")
    results = [MatchResult(entry_id=leaf.id, score=0.70), MatchResult(entry_id=router.id, score=0.60)]
    entries_by_id = {router.id: router, leaf.id: leaf}

    decision = decide_with_router_precedence(results, entries_by_id, threshold=0.45)
    assert decision.entry_id == router.id


def test_router_wins_even_if_its_raw_score_is_lower_than_leafs():
    # the whole point of the rule: router beats a leaf that's only
    # marginally ahead, even though a naive top-score pick would choose leaf
    router = _entry("Router", type_="router")
    leaf = _entry("Leaf")
    results = [MatchResult(entry_id=leaf.id, score=0.65), MatchResult(entry_id=router.id, score=0.55)]
    entries_by_id = {router.id: router, leaf.id: leaf}

    decision = decide_with_router_precedence(results, entries_by_id, threshold=0.45)
    assert decision.entry_id == router.id


def test_below_threshold_winner_is_suppressed():
    router = _entry("Router", type_="router")
    leaf = _entry("Leaf")
    results = [MatchResult(entry_id=leaf.id, score=0.50), MatchResult(entry_id=router.id, score=0.40)]
    entries_by_id = {router.id: router, leaf.id: leaf}

    assert decide_with_router_precedence(results, entries_by_id, threshold=0.75) is None


def test_no_router_present_falls_back_to_normal_top_decision():
    a = _entry("A")
    b = _entry("B")
    results = [MatchResult(entry_id=a.id, score=0.80), MatchResult(entry_id=b.id, score=0.40)]
    entries_by_id = {a.id: a, b.id: b}

    decision = decide_with_router_precedence(results, entries_by_id, threshold=0.75)
    assert decision.entry_id == a.id


def test_empty_results_returns_none():
    assert decide_with_router_precedence([], {}, threshold=0.5) is None


def test_router_default_priority_is_negative_five():
    router = _entry("Router", type_="router")
    answer = _entry("Answer")
    assert router.priority == -5
    assert answer.priority == 0


def test_explicit_priority_overrides_router_default():
    router = Entry.create(title="Router", answer="a", updated_by=1, type="router", priority=3)
    assert router.priority == 3
