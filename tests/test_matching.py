from pathlib import Path

import pytest
import yaml

from app.matching.regex_matcher import RegexMatcher, is_ambiguous, top_decision
from app.models import Entry
from app.repo.entries import EntryCache, EntryRepo
from tests.fakes import FakeStore

ACTOR = 1
AUTO_THRESHOLD = 0.75
SUGGEST_THRESHOLD = 0.45

CORPUS = yaml.safe_load(Path(__file__).parent.joinpath("corpus.yaml").read_text(encoding="utf-8"))

DTEK_ACCOUNT = {
    "title": "Рахунок ДТЕК",
    "category": "Комуналка",
    "answer": "Оплата за електроенергію: ...",
    "patterns": [r"дтек", r"рахун\w*\s+дтек", r"куди.{0,15}(плат|оплач).{0,15}світл"],
    "keywords": ["дтек", "світло", "рахунок"],
}
HEAD_CONTACT = {
    "title": "Контакт голови спільноти",
    "category": "Контакти",
    "answer": "Іваненко Іван Іванович",
    "patterns": [r"голов\w*\s+спільнот", r"хто.{0,10}голова"],
    "keywords": ["голова", "спільнота"],
}


@pytest.fixture
async def cache():
    store = FakeStore()
    repo = EntryRepo(store)
    for data in (DTEK_ACCOUNT, HEAD_CONTACT):
        await repo.save(Entry.create(updated_by=ACTOR, **data), actor_id=ACTOR)
    cache = EntryCache(repo, store)
    await cache.refresh(force=True)
    return cache


def _entry_id(title: str) -> str:
    from app.models import slugify

    return slugify(title)


@pytest.mark.parametrize("case", CORPUS, ids=[c["text"] for c in CORPUS])
async def test_corpus(cache, case):
    matcher = RegexMatcher(cache)
    results = await matcher.match(case["text"], cache.get_all_enabled())
    decision = top_decision(results, AUTO_THRESHOLD)
    got = decision.entry_id if decision else None
    assert got == case["expect"], f"results={results}"


async def test_dtek_scores_above_auto_threshold(cache):
    matcher = RegexMatcher(cache)
    results = await matcher.match("Люди, а який зараз рахунок у ДТЕК?", cache.get_all_enabled())
    assert results[0].entry_id == _entry_id(DTEK_ACCOUNT["title"])
    assert results[0].score >= AUTO_THRESHOLD
    assert not is_ambiguous(results)


async def test_keyword_without_question_stays_below_auto_threshold_but_above_suggest(cache):
    matcher = RegexMatcher(cache)
    results = await matcher.match("дтек знову світло вимкнув", cache.get_all_enabled())
    assert results[0].score == pytest.approx(0.60)
    assert SUGGEST_THRESHOLD <= results[0].score < AUTO_THRESHOLD
    assert top_decision(results, AUTO_THRESHOLD) is None
    assert top_decision(results, SUGGEST_THRESHOLD) is not None


async def test_ambiguous_top_two_close_scores_suppresses_decision(cache):
    store = FakeStore()
    repo = EntryRepo(store)
    await repo.save(Entry.create(title="Запис А", answer="a", updated_by=ACTOR, patterns=[r"плат"]), actor_id=ACTOR)
    await repo.save(Entry.create(title="Запис Б", answer="b", updated_by=ACTOR, patterns=[r"плат"]), actor_id=ACTOR)
    c2 = EntryCache(repo, store)
    await c2.refresh(force=True)
    matcher = RegexMatcher(c2)

    results = await matcher.match("як платити?", c2.get_all_enabled())
    assert len(results) == 2
    assert results[0].score == results[1].score
    assert is_ambiguous(results)
    assert top_decision(results, AUTO_THRESHOLD) is None


async def test_long_message_caps_score_at_050(cache):
    matcher = RegexMatcher(cache)
    long_text = "дтек " + "х" * 400 + " ?"
    results = await matcher.match(long_text, cache.get_all_enabled())
    assert results[0].score <= 0.50


async def test_priority_bonus_breaks_near_tie(cache):
    store = FakeStore()
    repo = EntryRepo(store)
    await repo.save(
        Entry.create(title="Низький", answer="a", updated_by=ACTOR, patterns=[r"плат"], priority=0),
        actor_id=ACTOR,
    )
    await repo.save(
        Entry.create(title="Високий", answer="b", updated_by=ACTOR, patterns=[r"плат"], priority=5),
        actor_id=ACTOR,
    )
    c2 = EntryCache(repo, store)
    await c2.refresh(force=True)
    matcher = RegexMatcher(c2)

    results = await matcher.match("як платити?", c2.get_all_enabled())
    assert results[0].entry_id == _entry_id("Високий")
    assert results[0].score > results[1].score
