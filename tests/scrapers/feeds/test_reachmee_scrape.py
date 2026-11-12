"""Fixture tests for the ReachMee feed: Örebro universitet's two publishing sites (Swedish and English) and
Arbetsgivarverket's empty one, trimmed from the live pages with the ad text rewritten."""

import pytest
import responses
from responses import matchers

from door.core.models import JobPosting
from door.scrapers import drain_errors, drain_non_local, drain_pushback
from door.scrapers.feeds import reachmee
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "reachmee"
_HOST = "https://web103.reachmee.com"
_JS_SV = f"{_HOST}/customerjs/I003-354-5.js"
_JS_EN = f"{_HOST}/customerjs/I003-354-12.js"
_JS_EMPTY = f"{_HOST}/customerjs/I021-1746-6.js"
_LIST_SV = f"{_HOST}/ext/I003/354/main"
_LIST_EN = f"{_HOST}/ext/I003/354/main"
_LIST_EMPTY = f"{_HOST}/ext/I021/1746/main"
_JOB = f"{_HOST}/ext/I003/354/job"
_KEY = "reachmee_companies"


def _fx(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


def _site(site: str):
    return matchers.query_param_matcher({"site": site}, strict_match=False)


def _mock_sv():
    responses.add(responses.GET, _JS_SV, body=_fx("customerjs_sv.js"))
    responses.add(responses.GET, _LIST_SV, body=_fx("list_sv.html"), match=[_site("5")])
    responses.add(responses.GET, _JOB, body=_fx("job_sv_12975.html"),
                  match=[matchers.query_param_matcher({"job_id": "12975"}, strict_match=False)])
    responses.add(responses.GET, _JOB, body=_fx("job_sv_12970.html"),
                  match=[matchers.query_param_matcher({"job_id": "12970"}, strict_match=False)])


def _mock_en():
    responses.add(responses.GET, _JS_EN, body=_fx("customerjs_en.js"))
    responses.add(responses.GET, _LIST_EN, body=_fx("list_en.html"), match=[_site("12")])
    responses.add(responses.GET, _JOB, body=_fx("job_en_12971.html"),
                  match=[matchers.query_param_matcher({"job_id": "12971"}, strict_match=False)])
    responses.add(responses.GET, _JOB, body=_fx("job_en_12985.html"),
                  match=[matchers.query_param_matcher({"job_id": "12985"}, strict_match=False)])


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("door.scrapers.http_client.time.sleep", lambda *a, **k: None)


@responses.activate
def test_scrape_reads_the_list_and_each_ad_and_maps_every_posting():
    _mock_sv()

    postings = reachmee.scrape({_KEY: ["I003/354/5"]})

    assert [p["platform_id"] for p in postings] == ["i003-354-12975", "i003-354-12970"]
    first = postings[0]
    JobPosting.model_validate(first)
    assert first["title"] == "Tentamensadministratör till Studentavdelningen"
    assert first["company"] == "Örebro universitet"
    assert first["location"] == "Örebro"
    assert first["url"].startswith(f"{_HOST}/ext/I003/354/job?site=5")
    assert first["url"].endswith("job_id=12975")
    assert first["description"].startswith("Vid Universitetet skapar vi framtiden")
    assert first["source"] == "reachmee" and first["id"] == "reachmee.i003-354-12975"


@responses.activate
def test_the_list_is_asked_with_the_validator_and_language_of_the_customer_script():
    _mock_sv()

    reachmee.scrape({_KEY: ["I003/354/5"]})

    list_call = next(c.request for c in responses.calls if "/main" in c.request.url)
    assert "validator=5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a" in list_call.url and "lang=SE" in list_call.url and "site=5" in list_call.url


@responses.activate
def test_a_swedish_and_an_english_publishing_site_both_come_through():
    _mock_sv()
    _mock_en()

    postings = reachmee.scrape({_KEY: ["I003/354/5", "I003/354/12"]})

    titles = [p["title"] for p in postings]
    assert "Tentamensadministratör till Studentavdelningen" in titles
    assert "Research Assistant in Biomedicine" in titles
    assert len(postings) == 4 and len({p["id"] for p in postings}) == 4
    english = next(p for p in postings if p["title"] == "Research Assistant in Biomedicine")
    assert english["description"].startswith("We are looking for a research assistant")


@responses.activate
def test_known_ids_are_left_out_and_their_pages_not_read():
    _mock_sv()

    postings = reachmee.scrape({_KEY: ["I003/354/5"]}, known_ids=frozenset({"i003-354-12975"}))

    assert [p["platform_id"] for p in postings] == ["i003-354-12970"]
    assert not any("job_id=12975" in c.request.url for c in responses.calls)


@responses.activate
def test_the_followed_name_wins():
    _mock_sv()

    postings = reachmee.scrape({_KEY: ["I003/354/5"], "_names": {_KEY: {"i003/354/5": "Örebro University"}}})

    assert {p["company"] for p in postings} == {"Örebro University"}


@responses.activate
def test_an_ad_page_that_fails_leaves_the_row_with_what_the_list_gives():
    responses.add(responses.GET, _JS_SV, body=_fx("customerjs_sv.js"))
    responses.add(responses.GET, _LIST_SV, body=_fx("list_sv.html"))
    responses.add(responses.GET, _JOB, status=500)

    drain_errors()
    postings = reachmee.scrape({_KEY: ["I003/354/5"]})

    assert [p["title"] for p in postings] == ["Tentamensadministratör till Studentavdelningen",
                                              "Forskningsassistent i biomedicin"]
    assert all(p["description"] == "" for p in postings)
    assert drain_errors().get("reachmee")


@responses.activate
def test_an_employer_with_no_open_ads_is_not_an_error():
    responses.add(responses.GET, _JS_EMPTY, body=_fx("customerjs_empty.js"))
    responses.add(responses.GET, _LIST_EMPTY, body=_fx("list_empty.html"))

    drain_errors()
    assert reachmee.scrape({_KEY: ["I021/1746/6"]}) == []
    assert not drain_errors().get("reachmee")


@responses.activate
def test_a_customer_script_without_a_validator_is_a_recorded_error():
    responses.add(responses.GET, _JS_SV, body="")

    drain_errors()
    assert reachmee.scrape({_KEY: ["I003/354/5"]}) == []
    assert "I003/354/5" in drain_errors()["reachmee"][0]


@responses.activate
def test_a_failed_list_is_a_recorded_error():
    responses.add(responses.GET, _JS_SV, body=_fx("customerjs_sv.js"))
    responses.add(responses.GET, _LIST_SV, status=500)

    drain_errors()
    assert reachmee.scrape({_KEY: ["I003/354/5"]}) == []
    assert drain_errors()["reachmee"]


@responses.activate
def test_a_refusal_is_recorded_as_pushback():
    responses.add(responses.GET, _JS_SV, status=429)

    drain_errors()
    drain_pushback("reachmee")
    assert reachmee.scrape({_KEY: ["I003/354/5"]}) == []
    assert drain_pushback("reachmee") is True
    assert drain_errors()["reachmee"]


def test_an_entry_that_is_no_site_is_a_recorded_error():
    drain_errors()
    assert reachmee.scrape({_KEY: ["oru"]}) == []
    assert "oru" in drain_errors()["reachmee"][0]


def test_scrape_without_entries_is_empty():
    assert reachmee.scrape({}) == []
    assert reachmee.probe({}) is None


@responses.activate
def test_postings_in_another_country_are_dropped_and_counted():
    _mock_sv()
    responses.replace(responses.GET, _JOB, body=_fx("job_sv_12975.html").replace(">Örebro<", ">Stockholm<"),
                      match=[matchers.query_param_matcher({"job_id": "12975"}, strict_match=False)])
    drain_non_local("reachmee")

    postings = reachmee.scrape({_KEY: ["I003/354/5"], "location": "Budapest, Hungary"})

    assert [p["platform_id"] for p in postings] == ["i003-354-12970"]   # a place the country file does not know stays
    assert drain_non_local("reachmee") == 1


@responses.activate
def test_postings_in_the_profiles_country_stay():
    _mock_sv()

    assert len(reachmee.scrape({_KEY: ["I003/354/5"], "location": "Stockholm, Sweden"})) == 2


# --- probe ---

@responses.activate
def test_probe_reads_the_list_page_only_and_leaves_no_errors():
    responses.add(responses.GET, _JS_SV, body=_fx("customerjs_sv.js"))
    responses.add(responses.GET, _LIST_SV, body=_fx("list_sv.html"))
    drain_errors()

    result = reachmee.probe({_KEY: ["I003/354/5"]})

    assert result["structure_ok"] is True and len(result["postings"]) == 2
    assert len(responses.calls) == 2   # the customer script and the list
    assert drain_errors() == {}


@responses.activate
def test_probe_of_a_list_without_its_table_is_not_ok():
    responses.add(responses.GET, _JS_SV, body=_fx("customerjs_sv.js"))
    responses.add(responses.GET, _LIST_SV, body="<html><title>x</title><body>moved</body></html>")

    result = reachmee.probe({_KEY: ["I003/354/5"]})

    assert result["structure_ok"] is False and result["reason"]


@responses.activate
def test_probe_of_an_empty_list_is_ok():
    responses.add(responses.GET, _JS_EMPTY, body=_fx("customerjs_empty.js"))
    responses.add(responses.GET, _LIST_EMPTY, body=_fx("list_empty.html"))

    result = reachmee.probe({_KEY: ["I021/1746/6"]})

    assert result["structure_ok"] is True and result["postings"] == []


@responses.activate
def test_probe_connection_error_is_unreachable():
    import requests
    responses.add(responses.GET, _JS_SV, body=requests.ConnectionError("down"))

    assert reachmee.probe({_KEY: ["I003/354/5"]})["unreachable"] is True


@responses.activate
def test_probe_forbidden_is_a_wall():
    responses.add(responses.GET, _JS_SV, status=403)

    assert reachmee.probe({_KEY: ["I003/354/5"]})["wall"] is True


# --- resolve (detection looks through the customer script) ---

@responses.activate
def test_resolve_keeps_an_entry_whose_customer_script_answers():
    from door.scrapers.sdk import PoliteSession
    responses.add(responses.GET, _JS_SV, body=_fx("customerjs_sv.js"))
    det = reachmee.detect_url("https://web103.reachmee.com/ext/I003/354/main?site=5&validator=x")

    assert reachmee.resolve(PoliteSession(), det, "u").entry == "I003/354/5"


@responses.activate
def test_resolve_refuses_an_entry_nobody_publishes_on():
    from door.scrapers.sdk import PoliteSession
    responses.add(responses.GET, f"{_HOST}/customerjs/I003-99999-5.js", body="")
    det = reachmee.detect_url("https://web103.reachmee.com/ext/I003/99999/main?site=5&validator=x")

    out = reachmee.resolve(PoliteSession(), det, "u")

    assert out.entry is None and out.refusal == "cant_yet"
