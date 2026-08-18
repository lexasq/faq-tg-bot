from app.models import slugify


def test_slugify_generic_words():
    assert slugify("Рахунок") == "rakhunok"
    assert slugify("для") == "dlia"
    assert slugify("оплати") == "oplaty"
    assert slugify("комунальних") == "komunalnykh"
    assert slugify("Спільнота") == "spilnota"


def test_slugify_full_titles_match_example_fixture_children():
    assert (
        slugify("Рахунок для оплати внесків на спільноту")
        == "rakhunok_dlia_oplaty_vneskiv_na_spilnotu"
    )
    assert (
        slugify("Рахунок для оплати через Партнер-Оплата")
        == "rakhunok_dlia_oplaty_cherez_partner_oplata"
    )
    assert (
        slugify("Квитанції за додаткові послуги (Приклад Сервіс)")
        == "kvytantsii_za_dodatkovi_posluhy_pryklad_servis"
    )
    assert (
        slugify("Квитанції спільноти (охорона, чергові, прибирання, вивіз сміття)")
        == "kvytantsii_spilnoty_okhorona_cherhovi_prybyrannia_vyviz_smittia"
    )
    assert slugify("Прилади обліку та щорічна перевірка") == "prylady_obliku_ta_shchorichna_perevirka"
    assert slugify("Куди платити внески") == "kudy_platyty_vnesky"
    assert slugify("Заявки щодо технічних питань") == "zaiavky_shchodo_tekhnichnykh_pytan"
    assert (
        slugify("Бухгалтерія спільноти — графік роботи та контакти")
        == "bukhhalteriia_spilnoty_hrafik_roboty_ta_kontakty"
    )
    assert slugify("Бухгалтерія партнера (СЕРВІС+)") == "bukhhalteriia_partnera_servis"


def test_slugify_is_idempotent_and_ascii():
    slug = slugify("Номери консьєржів!!")
    assert slug == "nomery_konsierzhiv"
    assert slug.encode("ascii")
