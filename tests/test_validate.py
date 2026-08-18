from app.importers.validate import validate_text

GOOD_IBAN = "UA563052990000026007030135112"
GOOD_EDRPOU = "46088552"


def test_known_good_iban_has_no_warning():
    warnings = validate_text(f"Рахунок: {GOOD_IBAN}")
    assert [w for w in warnings if w.kind == "iban"] == []


def test_mutated_iban_is_flagged():
    mutated = GOOD_IBAN[:-1] + ("1" if GOOD_IBAN[-1] != "1" else "2")
    warnings = validate_text(f"Рахунок: {mutated}")
    iban_warnings = [w for w in warnings if w.kind == "iban"]
    assert len(iban_warnings) == 1
    assert mutated in iban_warnings[0].text


def test_known_good_edrpou_has_no_warning():
    warnings = validate_text(f"Код отримувача: {GOOD_EDRPOU}")
    assert [w for w in warnings if w.kind == "edrpou"] == []


def test_mutated_edrpou_is_flagged():
    mutated = GOOD_EDRPOU[:-1] + ("1" if GOOD_EDRPOU[-1] != "1" else "2")
    warnings = validate_text(f"Код отримувача: {mutated}")
    edrpou_warnings = [w for w in warnings if w.kind == "edrpou"]
    assert len(edrpou_warnings) == 1
    assert mutated in edrpou_warnings[0].text


def test_second_known_edrpou_from_seed_data():
    # a second real-world EDRPOU checksum example, distinct from GOOD_EDRPOU
    assert validate_text("40538421") == []


def test_valid_phone_prefix_has_no_warning():
    warnings = validate_text("093 86 89 471")
    assert [w for w in warnings if w.kind == "phone"] == []


def test_unusual_phone_prefix_is_flagged():
    warnings = validate_text("075 123 36 91")
    phone_warnings = [w for w in warnings if w.kind == "phone"]
    assert len(phone_warnings) == 1
    assert "075" in phone_warnings[0].message


def test_international_format_phone_normalizes_correctly():
    warnings = validate_text("+380 (50) 434 19 15")
    assert [w for w in warnings if w.kind == "phone"] == []  # 050 is a valid prefix


def test_no_false_positives_on_plain_text():
    assert validate_text("Дякую, все зрозуміло, до зустрічі!") == []
