"""Regression test for a serious bug caught during live bulk-import
verification: naive `raw.split(",")` on a KEYS line breaks any pattern
containing a comma inside a regex quantifier like {0,20} or nested
inside parens. Most such fragments still compile as *valid* (wrong)
regex, so no error was ever logged — only the one pattern that happened
to produce truly invalid syntax
(rахунок(?!.{0,20}(осбб|тепл)) -> "рахунок(?!.{0" + "20}(осбб|тепл))")
surfaced as a warning. The others were silently corrupted.
"""
import re

from app.importers.text_blocks import split_pattern_list


def test_splits_simple_comma_separated_list():
    assert split_pattern_list("дтек, світло, електро") == ["дтек", "світло", "електро"]


def test_does_not_split_inside_curly_brace_quantifier():
    assert split_pattern_list("куди.{0,10}(плат|оплач)") == ["куди.{0,10}(плат|оплач)"]


def test_does_not_split_inside_nested_parens_and_braces():
    raw = "рахунок(?!.{0,20}(осбб|тепл))"
    assert split_pattern_list(raw) == [raw]


def test_the_actual_router_keys_line_from_seed_data_splits_into_six_intact_patterns():
    raw = "куди.{0,10}(плат|оплач), як.{0,10}(сплат|оплат|заплат), комуналк, оплат\\w*.{0,15}комунальн, реквізит, рахунок(?!.{0,20}(осбб|тепл))"
    patterns = split_pattern_list(raw)
    assert patterns == [
        "куди.{0,10}(плат|оплач)",
        "як.{0,10}(сплат|оплат|заплат)",
        "комуналк",
        "оплат\\w*.{0,15}комунальн",
        "реквізит",
        "рахунок(?!.{0,20}(осбб|тепл))",
    ]
    for p in patterns:
        re.compile(p)  # every pattern must be valid regex on its own


def test_unbalanced_brackets_do_not_crash_the_splitter():
    # lenient: never raises, worst case treats a stray bracket as depth-0
    split_pattern_list("a)b, c(d")


def test_empty_and_whitespace_only_fragments_are_dropped():
    assert split_pattern_list("a, , b,  ") == ["a", "b"]
