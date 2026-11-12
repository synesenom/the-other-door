from datetime import datetime, timedelta, timezone

import pytest

from door.core import ats_detect, freshness
from door.matching import locality, title_fit
from door.scrapers import sdk
from door import i18n


def test_every_export_is_documented():
    for name in sdk.__all__:
        obj = getattr(sdk, name)
        if name in sdk._DOCS:
            assert sdk._DOCS[name].strip(), name
        else:
            assert (obj.__doc__ or "").strip(), f"{name} has no docstring"


def test_the_docs_table_only_names_exports():
    assert set(sdk._DOCS) <= set(sdk.__all__)


def test_the_module_docstring_names_the_context_keys():
    assert "_mode" in sdk.__doc__ and "_country" in sdk.__doc__ and "_names" in sdk.__doc__


def test_wrappers_follow_a_patch_of_the_defining_module(monkeypatch):
    monkeypatch.setattr(title_fit, "on_topic", lambda title, terms: ("t", title, terms))
    monkeypatch.setattr(locality, "country_is_non_local", lambda c, config, remote=False: ("l", c, remote))
    monkeypatch.setattr(i18n, "career_site_words", lambda: ["patched"])
    monkeypatch.setattr(ats_detect, "from_url", lambda url: ("a", url))
    monkeypatch.setattr(freshness, "days_back", lambda since, now: "patched")
    assert sdk.on_topic("x", ["y"]) == ("t", "x", ["y"])
    assert sdk.country_is_non_local("SE", {}, remote=True) == ("l", "SE", True)
    assert sdk.career_site_words() == ["patched"]
    assert sdk.from_url("u") == ("a", "u")
    assert sdk.look_back_days(datetime.now(timezone.utc), datetime.now(timezone.utc)) == "patched"


def test_the_matching_and_i18n_wrappers_return_what_their_sources_do():
    cfg = {"location": "Copenhagen", "role_targets": ["data engineer"], "search_keywords": ["data engineer"]}
    assert sdk.keywords(cfg) == title_fit.keywords(cfg)
    assert sdk.topic_terms(cfg) == title_fit.topic_terms(cfg)
    assert sdk.topic_words(cfg) == title_fit.topic_words(cfg)
    assert sdk.squash("A b") == title_fit.squash("A b")
    assert sdk.name_pattern(["Acme"]).pattern == title_fit.name_pattern(["Acme"]).pattern
    assert sdk.local_names(cfg) == locality.local_names(cfg)
    assert sdk.split_urls([], cfg) == locality.split_urls([], cfg)
    assert sdk.location_filter(None, cfg) == locality.location_filter(None, cfg)
    assert sdk.career_path_stems() == i18n.career_path_stems()
    assert sdk.career_nav_words() == i18n.career_nav_words()
    assert sdk.career_apply_words() == i18n.career_apply_words()
    assert sdk.city_names("Copenhagen") == i18n.city_names("Copenhagen")
    assert sdk.seniority_words() == i18n.seniority_words()
    assert sdk.stop_words() == i18n.stop_words()
    assert sdk.transliteration() == i18n.transliteration()
    assert sdk.generic_host_labels() == i18n.generic_host_labels()
    assert sdk.tld_labels() == i18n.tld_labels()
    assert {"generic_host_labels", "tld_labels"} <= set(sdk.__all__)
    assert sdk.word_pattern(["a"]) == i18n.word_pattern(["a"])
    assert sdk.compile_words(["a"]).pattern == i18n.compile_words(["a"]).pattern
    assert sdk.ad_links("<html></html>", "https://x.test/") == ats_detect.ad_links("<html></html>", "https://x.test/")


def test_country_name():
    assert sdk.country_name("dk") == i18n.countries()["dk"].name
    assert sdk.country_name("zz") == "ZZ"


@pytest.mark.parametrize("config, served, expected", [
    ({"_country": "se"}, ("dk", "se"), "SE"),
    ({"_country": None}, ("dk",), "DK"),
    ({"location": "Stockholm"}, ("dk",), "DK"),
    ({"location": "Copenhagen"}, ("dk",), "DK"),
    ({}, ("dk", "se"), "DK"),
    ({"_country": "se"}, ("dk",), "DK"),
    ({"_country": None, "location": "Copenhagen"}, ("dk",), "DK"),
])
def test_country(config, served, expected):
    assert sdk.country(config, served) == expected


def test_look_back_days():
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    assert sdk.look_back_days(None, now) is None
    assert sdk.look_back_days(now - timedelta(days=2, hours=1), now) == 3


def test_the_feed_platform_section_exports_the_detection_helpers():
    for name in ("Detection", "Probe", "parts", "first", "NOT_ACCOUNTS", "unfollowable"):
        assert name in sdk.__all__ and hasattr(sdk, name)
    assert sdk.Detection is ats_detect.Detection


def test_parts_and_first_read_a_link():
    host, path, query = sdk.parts("https://Jobs.Example.com:443/Acme/jobs?For=X&b=1")
    assert (host, path, query) == ("jobs.example.com", ["Acme", "jobs"], {"for": "X", "b": "1"})
    assert sdk.first(["Acme", "jobs"]) == "acme"
    assert sdk.first(["www"]) is None and sdk.first([]) is None
    assert "careers" in sdk.NOT_ACCOUNTS


def test_unfollowable_names_the_platform_without_an_entry():
    det = sdk.unfollowable("phenom", "jobs.lego.com", "a front end; not followed")
    assert det == sdk.Detection("phenom", None, "jobs.lego.com: a front end; not followed", "must_not")


def test_unfollowable_says_whether_door_must_not_or_cannot_yet():
    """#438: a platform refused for its terms is not the same as one The other door has no way into yet."""
    assert sdk.unfollowable("x", "w", "r").refusal == "must_not"
    assert sdk.unfollowable("x", "w", "r", refusal="cant_yet").refusal == "cant_yet"
    assert sdk.Detection("x", "entry", "e").refusal is None


def test_a_probe_is_a_url_a_key_and_the_evidence():
    probe = sdk.Probe("https://x.test/jobs", "jobs", "X board acme")
    assert probe.params is None and probe.key == "jobs"


_NAMES = {"_names": {"greenhouse_boards": {"boards.greenhouse.io/acme": "Acme A/S"}, "lever_companies": {"globex": "Globex"}}}


def test_followed_name_wins_by_normalized_entry():
    assert sdk.followed_name(_NAMES, "greenhouse_boards", "HTTPS://boards.greenhouse.io/acme/", "feed") == "Acme A/S"
    assert sdk.followed_name(_NAMES, "lever_companies", " Globex ", "feed") == "Globex"


def test_followed_name_falls_back_without_a_map_or_key_or_entry():
    assert sdk.followed_name({}, "lever_companies", "globex", "feed") == "feed"
    assert sdk.followed_name(_NAMES, "ashby_companies", "globex", "feed") == "feed"
    assert sdk.followed_name(_NAMES, "lever_companies", "other", "feed") == "feed"
    assert sdk.followed_name(_NAMES, "lever_companies", "other") == ""


def test_followed_name_ignores_a_blank_name():
    assert sdk.followed_name({"_names": {"k": {"a": "  "}}}, "k", "a", "feed") == "feed"


def test_keep_local_filters_and_records(monkeypatch):
    recorded = []
    monkeypatch.setattr(sdk, "record_non_local", lambda site, n: recorded.append((site, n)))
    monkeypatch.setattr(locality, "split_postings", lambda postings, config: (postings[:1], 2))
    assert sdk.keep_local([{"a": 1}, {"b": 2}, {"c": 3}], {}, "x") == [{"a": 1}]
    assert recorded == [("x", 2)]
    recorded.clear()
    monkeypatch.setattr(locality, "split_postings", lambda postings, config: (postings, 0))
    assert sdk.keep_local([{"a": 1}], {}, "x") == [{"a": 1}]
    assert recorded == []
