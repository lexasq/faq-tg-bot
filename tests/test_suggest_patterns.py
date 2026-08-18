import re

from app.handlers.admin_crud import suggest_patterns


def test_suggests_full_title_and_significant_tokens():
    patterns = suggest_patterns("Рахунок ДТЕК")
    compiled = [re.compile(p) for p in patterns]  # must all be valid regex
    assert any(p.search("рахунок дтек") for p in compiled)
    assert any(p.search("дтек") for p in compiled)


def test_drops_short_tokens_and_stopwords():
    patterns = suggest_patterns("Хто у нас голова ОСББ")
    # patterns[0] is always the whole (escaped) title, so check the
    # per-token patterns specifically rather than substring-in-joined,
    # which the full-title pattern would trivially satisfy either way.
    token_patterns = patterns[1:]
    assert re.escape("хто") not in token_patterns  # 3 chars, dropped
    assert re.escape("голова") in token_patterns
    assert re.escape("осбб") in token_patterns


def test_regex_metacharacters_in_title_are_escaped():
    # a literal '?' or '(' in a title must not break the generated regex
    patterns = suggest_patterns("Що робити, якщо немає води?")
    for p in patterns:
        re.compile(p)  # would raise re.error if unescaped


def test_multi_word_pattern_uses_whitespace_between_tokens():
    patterns = suggest_patterns("Графік роботи бухгалтерії")
    joined_pattern = next((p for p in patterns if r"\s+" in p), None)
    assert joined_pattern is not None
    assert re.compile(joined_pattern).search("графік    роботи бухгалтерії")


def test_no_duplicate_patterns():
    patterns = suggest_patterns("Тест тест тест")
    assert len(patterns) == len(set(patterns))
