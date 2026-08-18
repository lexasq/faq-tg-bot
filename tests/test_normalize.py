from app.matching.normalize import normalize_pattern, normalize_text


def test_lowercases_and_collapses_whitespace():
    cleaned, tokens = normalize_text("  Хто    ГОЛОВА   ОСББ?  ")
    assert cleaned == "хто голова осбб?"
    assert tokens == ["хто", "голова", "осбб?"]


def test_homoglyph_mapping_reconstructs_mixed_word():
    # 'c','b','i','t','o' typed on a Latin layout, 'л' typed on Cyrillic —
    # a common wrong-layout typo for "світло" (light/power).
    cleaned, _ = normalize_text("cbitлo")
    assert cleaned == "світло"


def test_homoglyph_table_only_covers_listed_letters():
    # 'd' has no Cyrillic lookalike in the plan's table (section 5.1), so
    # "dtek" only partially normalizes — documenting the known limit.
    cleaned, _ = normalize_text("DTEK")
    assert cleaned == "dтек"


def test_apostrophe_variants_unified():
    cleaned, _ = normalize_text("зв'язок звʼязок зв’язок")
    assert cleaned == "зв'язок зв'язок зв'язок"


def test_strips_punctuation_but_keeps_hyphen_and_question_mark():
    cleaned, tokens = normalize_text("науково-технічний, справді?! так.")
    assert cleaned == "науково-технічний справді? так"
    assert tokens == ["науково-технічний", "справді?", "так"]


def test_empty_input():
    cleaned, tokens = normalize_text("   ")
    assert cleaned == ""
    assert tokens == []


def test_normalize_pattern_maps_homoglyphs_without_lowercasing_escapes():
    assert normalize_pattern(r"\w*кoнсьєрж") == r"\w*консьєрж"  # 'o' -> 'о'
    assert normalize_pattern(r"\W+тест") == r"\W+тест"  # \W untouched, not lowercased into \w
