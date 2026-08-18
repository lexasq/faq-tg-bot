from app.importers.freeform import segment_freeform


def test_short_title_line_followed_by_content_is_high_confidence():
    text = "Номери консьєржів\n075 123 36 91 — 1 секція"
    blocks = segment_freeform(text)
    assert len(blocks) == 1
    assert blocks[0].title == "Номери консьєржів"
    assert blocks[0].confidence == "high"
    assert "075 123 36 91" in blocks[0].body


def test_title_line_ending_in_colon_strips_colon():
    text = "Контакти:\nІваненко Іван Іванович"
    blocks = segment_freeform(text)
    assert blocks[0].title == "Контакти"
    assert blocks[0].confidence == "high"


def test_text_then_url_splits_at_the_url():
    text = "Форма для реєстрації: https://example.com/form"
    blocks = segment_freeform(text)
    assert blocks[0].title == "Форма для реєстрації"
    assert blocks[0].body == "https://example.com/form"
    assert blocks[0].confidence == "high"


def test_long_first_line_is_orphan():
    long_line = "Це дуже довге речення яке точно перевищує шістдесят символів у довжину і тому не може бути заголовком"
    blocks = segment_freeform(long_line)
    assert blocks[0].title is None
    assert blocks[0].confidence == "orphan"
    assert long_line in blocks[0].body


def test_block_of_only_urls_is_orphan():
    text = "https://a.example.com\nhttps://b.example.com"
    blocks = segment_freeform(text)
    assert blocks[0].title is None
    assert blocks[0].confidence == "orphan"


def test_single_paragraph_with_no_continuation_is_orphan():
    text = "Коротке речення."
    blocks = segment_freeform(text)
    assert blocks[0].title is None
    assert blocks[0].confidence == "orphan"


def test_short_line_ending_in_sentence_punctuation_with_more_lines_is_orphan():
    text = "Дякую за терпіння.\nЦе продовження абзацу."
    blocks = segment_freeform(text)
    assert blocks[0].title is None
    assert blocks[0].confidence == "orphan"


def test_multiple_blocks_split_on_blank_lines():
    text = "Заголовок 1\nТіло 1\n\nЗаголовок 2\nТіло 2"
    blocks = segment_freeform(text)
    assert len(blocks) == 2
    assert blocks[0].title == "Заголовок 1"
    assert blocks[1].title == "Заголовок 2"


def test_body_text_is_never_modified():
    text = "Заголовок\nремотних тут навмисна помилка"
    blocks = segment_freeform(text)
    assert "ремотних" in blocks[0].body  # typos are preserved verbatim


def test_divider_line_of_underscores_splits_blocks():
    text = "Тема А\nВміст А\n________________________________\nТема Б\nВміст Б"
    blocks = segment_freeform(text)
    assert len(blocks) == 2
    assert blocks[0].title == "Тема А"
    assert blocks[1].title == "Тема Б"
    assert "Тема Б" not in blocks[0].body


def test_divider_line_of_dashes_splits_blocks():
    text = "Тема А\nВміст А\n----------\nТема Б\nВміст Б"
    blocks = segment_freeform(text)
    assert len(blocks) == 2


def test_short_hyphen_inside_a_line_is_not_treated_as_a_divider():
    # "1-3" and similar must not trigger a false split
    text = "Паролі однакові у підвалах 1-3 секції\nІ у консьєржів теж"
    blocks = segment_freeform(text)
    assert len(blocks) == 1


def test_real_multi_topic_paste_with_divider_lines_splits_into_separate_entries():
    # regression: this exact shape (___ and --- used as visual section
    # breaks instead of blank lines) previously glued 3 unrelated topics
    # into one entry, because _split_into_blocks only split on blank lines
    text = (
        "Загальний вайфай\n"
        "Паролі однакові у 1-3 секціях\n"
        "https://kyiv.poverka.net.ua/yak-peredaty-akty-pro-povirku-lichylnykiv-na-oblik/\n"
        "________________________________\n"
        "Реєстрація в Спільнота Онлайн\n"
        "Для реєстрації перейдіть за посиланням https://example.com/\n"
        "--------------------------------------------------------------------------------------------------------\n"
        "Бухгалтерія спільноти\n"
        "093 86 89 471\n"
    )
    blocks = segment_freeform(text)
    titles = [b.title for b in blocks]
    assert titles == ["Загальний вайфай", "Реєстрація в Спільнота Онлайн", "Бухгалтерія спільноти"]
    wifi_block = blocks[0]
    assert "Реєстрація" not in wifi_block.body
    assert "Бухгалтерія" not in wifi_block.body
