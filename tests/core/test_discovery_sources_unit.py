"""The registry of discovery sources: which modules exist, which ones a profile runs."""

import sys
import types

import pytest

from door.core import discovery_sources as reg


@pytest.fixture
def fake_module(monkeypatch):
    def make(name="fake", countries=("hu",), key="fake_discovery"):
        mod = types.ModuleType(f"fake_source_{name}")
        mod.NAME, mod.COUNTRIES, mod.CONFIG_KEY = name, countries, key
        mod.run = lambda config, **kw: {}
        mod.VERDICT, mod.TERMS_URL, mod.TERMS_SUMMARY = "unsure", "https://example.com/terms", "its terms ban bots"
        monkeypatch.setitem(sys.modules, mod.__name__, mod)
        monkeypatch.setitem(reg.SOURCES, name, mod.__name__)
        return mod
    return make


def test_linkedin_is_registered_and_resolved_lazily_by_dotted_name():
    assert reg.SOURCES["linkedin"] == "door.scrapers.discovery.linkedin"
    mod = reg.get("linkedin")
    assert (mod.NAME, mod.COUNTRIES, mod.CONFIG_KEY) == ("linkedin", (), "linkedin_discovery")


def test_a_worldwide_source_runs_anywhere_once_the_user_turned_it_on():
    got = {n: reason for n, _, reason in reg.selected({"location": "Copenhagen", "linkedin_discovery": True})}
    assert got["linkedin"] is None
    got = {n: reason for n, _, reason in reg.selected({"location": "nowhere-land", "linkedin_discovery": True})}
    assert got["linkedin"] is None


def test_a_source_nobody_chose_does_not_run_and_says_so():
    got = {n: reason for n, _, reason in reg.selected({"location": "Copenhagen"})}
    assert got["linkedin"] == "linkedin_discovery not chosen"


def test_a_source_for_another_country_is_not_for_it_whatever_its_key(fake_module):
    fake_module()
    got = {n: r for n, _, r in reg.selected({"location": "Copenhagen", **ON})}
    assert got["fake"] == "not for dk"


def test_for_location_lists_the_sources_serving_the_city_with_key_and_label():
    keys = lambda loc: [s["key"] for s in reg.for_location(loc)]
    assert keys("Copenhagen") == ["linkedin_discovery"]
    assert keys("Budapest") == ["linkedin_discovery", "profession_discovery"]
    assert keys("nowhere-land") == ["linkedin_discovery"]
    assert reg.for_location("Copenhagen")[0] == reg.info("linkedin")


def test_unchosen_lists_the_serving_sources_whose_key_is_not_set():
    config = {"location": "Budapest", "linkedin_discovery": False}
    assert [s["key"] for s in reg.unchosen(config)] == ["profession_discovery"]


def test_a_key_set_to_false_gives_its_reason():
    got = {n: reason for n, _, reason in reg.selected({"location": "Copenhagen", "linkedin_discovery": False})}
    assert got["linkedin"] == "linkedin_discovery is off"


def test_the_country_gate_skips_a_source_for_other_countries(fake_module):
    fake_module()
    dk = {n: r for n, _, r in reg.selected({"location": "Copenhagen", "fake_discovery": True})}
    hu = {n: r for n, _, r in reg.selected({"location": "Budapest", "fake_discovery": True})}
    assert dk["fake"] == "not for dk" and hu["fake"] is None


def test_a_country_source_does_not_run_for_an_unknown_country(fake_module):
    fake_module()
    got = {n: r for n, _, r in reg.selected({"location": "nowhere-land"})}
    assert got["fake"] is not None


def test_the_fake_key_off_skips_only_the_fake(fake_module):
    fake_module()
    got = {n: r for n, _, r in reg.selected({"location": "Budapest", "fake_discovery": False, "linkedin_discovery": True})}
    assert got["fake"] == "fake_discovery is off" and got["linkedin"] is None


ON = {"linkedin_discovery": True, "profession_discovery": True}


def test_profession_is_registered_for_hungary_only():
    assert reg.SOURCES["profession"] == "door.scrapers.discovery.profession"
    mod = reg.get("profession")
    assert (mod.NAME, mod.COUNTRIES, mod.CONFIG_KEY) == ("profession", ("hu",), "profession_discovery")
    hu = {n: r for n, _, r in reg.selected({"location": "Budapest", **ON})}
    dk = {n: r for n, _, r in reg.selected({"location": "Copenhagen", **ON})}
    assert hu["profession"] is None and hu["linkedin"] is None
    assert dk["profession"] == "not for dk" and dk["linkedin"] is None
    off = {n: r for n, _, r in reg.selected({"location": "Budapest", "profession_discovery": False})}
    assert off["profession"] == "profession_discovery is off"


def test_hellowork_is_registered_for_france_only():
    assert reg.SOURCES["hellowork"] == "door.scrapers.discovery.hellowork"
    mod = reg.get("hellowork")
    assert (mod.NAME, mod.COUNTRIES, mod.CONFIG_KEY) == ("hellowork", ("fr",), "hellowork_discovery")
    fr = {n: r for n, _, r in reg.selected({"location": "Paris", "hellowork_discovery": True})}
    dk = {n: r for n, _, r in reg.selected({"location": "Copenhagen", "hellowork_discovery": True})}
    assert fr["hellowork"] is None and fr["linkedin"] == "linkedin_discovery not chosen" and dk["hellowork"] == "not for dk"
    assert [s["key"] for s in reg.for_location("Paris")] == ["linkedin_discovery", "hellowork_discovery"]
    off = {n: r for n, _, r in reg.selected({"location": "Paris", "hellowork_discovery": False})}
    assert off["hellowork"] == "hellowork_discovery is off"


def test_jobbsafari_is_registered_for_sweden_only():
    assert reg.SOURCES["jobbsafari"] == "door.scrapers.discovery.jobbsafari"
    mod = reg.get("jobbsafari")
    assert (mod.NAME, mod.COUNTRIES, mod.CONFIG_KEY) == ("jobbsafari", ("se",), "jobbsafari_discovery")
    on = {**ON, "jobbsafari_discovery": True}
    se = {n: r for n, _, r in reg.selected({"location": "Stockholm", **on})}
    dk = {n: r for n, _, r in reg.selected({"location": "Copenhagen", **on})}
    assert se["jobbsafari"] is None and se["linkedin"] is None and se["profession"] == "not for se"
    assert dk["jobbsafari"] == "not for dk"
    off = {n: r for n, _, r in reg.selected({"location": "Stockholm", "jobbsafari_discovery": False})}
    assert off["jobbsafari"] == "jobbsafari_discovery is off"
    assert [s["key"] for s in reg.for_location("Stockholm")] == ["linkedin_discovery", "jobbsafari_discovery"]


def test_off_for_location_lists_serving_sources_not_turned_on():
    config = {"location": "Budapest", "linkedin_discovery": True}
    assert [s["key"] for s in reg.off_for_location(config)] == ["profession_discovery"]
    assert reg.off_for_location({"location": "Copenhagen", "linkedin_discovery": False})[0] == reg.info("linkedin")


def test_off_for_location_is_empty_when_every_serving_source_is_on():
    config = {"location": "Budapest", "linkedin_discovery": True, "profession_discovery": True}
    assert reg.off_for_location(config) == []


def test_off_for_location_leaves_out_sources_of_other_countries():
    keys = [s["key"] for s in reg.off_for_location({"location": "Copenhagen"})]
    assert "profession_discovery" not in keys and "linkedin_discovery" in keys


def test_every_source_module_declares_a_verdict_and_its_terms():
    for name in reg.SOURCES:
        module = reg.get(name)
        assert module.VERDICT in ("allowed", "unsure", "reserved"), name
        assert module.TERMS_URL.startswith("https://"), name
        assert module.TERMS_SUMMARY and "\n" not in module.TERMS_SUMMARY, name


def test_every_source_module_has_a_terms_passage():
    import re

    for name in reg.SOURCES:
        doc = reg.get(name).__doc__ or ""
        assert re.search(r"(?m)^\s*Terms\b", doc), (
            f"{name}: its module docstring needs a line starting 'Terms' quoting the terms its verdict rests on "
            "(docs/job-sites.md, How The other door fetches)"
        )


def test_the_four_sources_are_unsure():
    assert {n: reg.info(n)["verdict"] for n in reg.SOURCES} == {
        "linkedin": "unsure", "profession": "unsure", "hellowork": "unsure", "jobbsafari": "unsure",
    }


def test_info_carries_label_terms_and_the_disclaimer():
    info = reg.info("linkedin")
    assert set(info) == {"name", "key", "label", "verdict", "terms_url", "terms_summary", "disclaimer"}
    assert info["label"] == "LinkedIn" and info["key"] == "linkedin_discovery"
    for part in (info["label"], info["terms_summary"], info["terms_url"], "LEGAL_DISCLAIMER.md"):
        assert part in info["disclaimer"]


def test_on_lists_the_unsure_sources_the_user_turned_on_that_serve_the_city():
    config = {"location": "Copenhagen", "linkedin_discovery": True, "profession_discovery": True}
    assert [s["name"] for s in reg.on(config)] == ["linkedin"]
    assert reg.on({"location": "Copenhagen"}) == []
