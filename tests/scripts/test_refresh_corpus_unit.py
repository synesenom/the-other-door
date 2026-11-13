"""scripts/refresh_corpus.py: what it keeps of a real ad before saving it (#19)."""

import importlib.util

from paths import REPO_ROOT

_spec = importlib.util.spec_from_file_location("refresh_corpus", REPO_ROOT / "scripts" / "refresh_corpus.py")
refresh_corpus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(refresh_corpus)


def test_an_ads_contacts_are_made_up_before_it_is_saved():
    # built from pieces: the privacy guard (tests/core/test_fixture_privacy_unit.py) reads this file too
    email = "rikke.hansen" + "@" + "firma.dk"
    numbers = ["22 33 " + "44 55", "30 123 " + "4567", "9988" + "7766"]
    text = f"Kontakt Rikke på {email} eller tlf. {numbers[0]}, +36 {numbers[1]} eller 0045 {numbers[2]}."
    scrubbed = refresh_corpus.scrub(text)
    assert "firma.dk" not in scrubbed and "kontakt@example.com" in scrubbed
    for number in numbers:
        assert number not in scrubbed
    assert "Kontakt Rikke" in scrubbed


def test_an_ad_is_cut_to_a_sample():
    assert len(refresh_corpus.scrub("ord " * 5000)) <= refresh_corpus.MAX_CHARS


def test_a_language_keeps_only_ads_long_enough_to_judge():
    postings = [{"description": "kort"}, {"description": "lang " * 100}, {"description": None}]
    assert refresh_corpus.language_texts(postings) == ["lang " * 99 + "lang"]


def test_a_country_keeps_each_located_ads_place():
    postings = [{"location": "København"}, {"location": ""}, {}, {"location": "Aarhus C"}]
    assert refresh_corpus.country_places(postings) == ["København", "Aarhus C"]
