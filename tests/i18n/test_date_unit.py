"""A letter's date in the language of the ad (#146): the date is filled by Python, babel's \\today is gone."""
from datetime import date

import pytest

from door import i18n


@pytest.mark.parametrize("code,expected", [
    ("en", "November 16, 2026"), ("da", "16. november 2026"), ("fr", "16 novembre 2026"),
    ("hu", "2026. november 16."), ("sv", "16 november 2026"),
])
def test_the_date_is_written_the_way_the_language_does(code, expected):
    assert i18n.format_date(date(2026, 11, 16), code) == expected


def test_french_writes_the_first_of_the_month_with_an_ordinal():
    assert i18n.format_date(date(2026, 11, 1), "fr") == "1er novembre 2026"
    assert i18n.format_date(date(2026, 11, 2), "fr") == "2 novembre 2026"


@pytest.mark.parametrize("code,expected", [
    ("en", "November 1, 2026"), ("da", "1. november 2026"), ("hu", "2026. november 1."), ("sv", "1 november 2026"),
])
def test_other_languages_write_the_first_like_any_day(code, expected):
    assert i18n.format_date(date(2026, 11, 1), code) == expected


def test_an_unknown_or_missing_language_is_english():
    assert i18n.format_date(date(2026, 1, 5), "xx") == "January 5, 2026"
    assert i18n.format_date(date(2026, 1, 5), None) == "January 5, 2026"


def test_a_language_file_names_all_twelve_months(tmp_path):
    bad = tmp_path / "xx.toml"
    bad.write_text('code = "xx"\nname = "X"\n[date]\npattern = "{day} {month} {year}"\nmonths = ["a"]\n')
    with pytest.raises(Exception, match="twelve"):
        i18n.load_language_file(bad)


def test_only_french_has_typography_rules():
    langs = i18n.languages()
    assert langs["fr"].typography.space_before == [":", ";", "!", "?"]
    for code in ("en", "da", "hu", "sv"):
        assert langs[code].typography.space_before == []
