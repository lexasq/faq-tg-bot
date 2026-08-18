import re
from pathlib import Path

from app.importers.text_blocks import is_strict_format, parse_strict, render_strict_block

SEED_PATH = Path(__file__).parent / "fixtures" / "faq_example.md"


def _extract_seed_blocks_source() -> str:
    """The example file is a markdown doc with prose around a fenced code
    block containing the actual Q:/CAT:/.../A: content — pull just that."""
    text = SEED_PATH.read_text(encoding="utf-8")
    start = text.index("```\nQ:")
    end = text.index("\n```", start)
    return text[start + 4 : end]


def test_parses_the_example_seed_content_with_no_errors():
    source = _extract_seed_blocks_source()
    assert is_strict_format(source)
    entries, errors = parse_strict(source)

    assert errors == []
    assert len(entries) == 13  # 12 answer entries + 1 router

    titles = [e.title for e in entries]
    assert "Номери чергових" in titles
    assert "Куди платити внески" in titles


def test_seed_router_entry_has_type_and_children():
    source = _extract_seed_blocks_source()
    entries, _errors = parse_strict(source)
    router = next(e for e in entries if e.title == "Куди платити внески")

    assert router.type == "router"
    assert len(router.children) == 5
    assert "rakhunok_dlia_oplaty_vneskiv_na_spilnotu" in router.children


def test_seed_dm_only_entry_has_visibility_and_review():
    source = _extract_seed_blocks_source()
    entries, _errors = parse_strict(source)
    emails = next(e for e in entries if e.title == "Електронна пошта учасників")
    fees_account = next(e for e in entries if e.title == "Рахунок для оплати внесків на спільноту")

    assert emails.visibility == "dm_only"
    assert fees_account.review_after.isoformat() == "2027-02-01"


def test_seed_answers_preserve_verbatim_financial_data():
    source = _extract_seed_blocks_source()
    entries, _errors = parse_strict(source)
    fees_account = next(e for e in entries if e.title == "Рахунок для оплати внесків на спільноту")

    assert "UA079999000000000000000000001" in fees_account.answer
    assert "99990002" in fees_account.answer
    assert "<b>" in fees_account.answer  # HTML formatting preserved as-is


def test_missing_answer_is_a_parse_error():
    entries, errors = parse_strict("Q: Немає відповіді\nCAT: Тест\n---\nQ: Друге\nA:\nОк")
    assert len(entries) == 1
    assert entries[0].title == "Друге"
    assert len(errors) == 1
    assert "Немає відповіді" in errors[0].message


def test_missing_q_prefix_is_a_parse_error():
    entries, errors = parse_strict("Не питання, просто текст\nA:\nВідповідь")
    assert entries == []
    assert len(errors) == 1


def test_round_trip_export_reimport():
    source = _extract_seed_blocks_source()
    entries, _errors = parse_strict(source)
    exported = "\n---\n".join(render_strict_block(e) for e in entries)

    reimported, errors = parse_strict(exported)
    assert errors == []
    assert len(reimported) == len(entries)
    assert {e.title for e in reimported} == {e.title for e in entries}
    router = next(e for e in reimported if e.type == "router")
    assert len(router.children) == 5


def test_every_seed_pattern_compiles_and_survives_intact():
    # Regression: naive comma-splitting on KEYS used to silently mangle
    # any pattern with a {n,m} quantifier (see test_split_pattern_list.py)
    # — most fragments still compiled, just matched the wrong thing, so
    # "no parse errors" alone (the older assertion above) didn't catch it.
    source = _extract_seed_blocks_source()
    entries, _errors = parse_strict(source)

    for entry in entries:
        for pattern in entry.patterns:
            re.compile(pattern)

    router = next(e for e in entries if e.title == "Куди платити внески")
    assert "рахунок(?!.{0,20}(внеск|послуг))" in router.patterns


def test_crlf_and_blank_lines_are_tolerated():
    text = "Q: Тест\r\nCAT: Загальне\r\n\r\nA:\r\nВідповідь\r\n"
    entries, errors = parse_strict(text)
    assert errors == []
    assert entries[0].answer == "Відповідь"
