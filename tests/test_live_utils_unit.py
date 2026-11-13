"""The live tests' verdicts (#19): a site that refused the request was not reached; anything else is a change."""

import pytest

from live_utils import NOT_REACHED, not_reached, not_reached_if_refused, refused


@pytest.mark.parametrize("message", [
    "search error (keyword='x', page=1): 429 Client Error: Too Many Requests for url: https://x",
    "detail error (https://x): 403 Client Error: Forbidden for url: https://x",
    "401 Client Error: Unauthorized for url: https://x",
    "HTTPSConnectionPool(host='x', port=443): Read timed out. (read timeout=30)",
    "HTTPSConnectionPool(host='x', port=443): Max retries exceeded with url: / (Caused by NameResolutionError)",
    "('Connection aborted.', ConnectionResetError(54, 'Connection reset by peer'))",
    "reed: pushback (HTTP 429); stopped for this run",
    "503 Server Error: Service Unavailable for url: https://x",
])
def test_a_refusal_or_an_unreachable_host_is_not_reached(message):
    assert refused([message])


@pytest.mark.parametrize("errors", [
    [],
    ["no search results block on page (keyword='x', page=1)"],
    ["429 Client Error: Too Many Requests", "no search results block on page"],   # a parse failure too: changed
    ["KeyError: 'jobs'"],
])
def test_no_errors_or_a_parse_failure_is_not_a_refusal(errors):
    assert not refused(errors)


def test_a_refused_site_is_skipped_as_not_reached_everywhere(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    with pytest.raises(pytest.skip.Exception) as skipped:
        not_reached_if_refused("reed", ["403 Client Error: Forbidden for url: https://x"])
    assert str(skipped.value).startswith(f"{NOT_REACHED} reed: ")


def test_a_known_refusal_is_not_reached_whatever_its_wording():
    with pytest.raises(pytest.skip.Exception) as skipped:
        not_reached("wikidata", "Wikidata did not answer")
    assert str(skipped.value) == f"{NOT_REACHED} wikidata: Wikidata did not answer"


def test_a_site_that_answered_badly_is_left_to_fail():
    assert not_reached_if_refused("reed", ["no search results block on page"]) is None
    assert not_reached_if_refused("reed", []) is None


# --- discovery sources (#19): a refusal is not reached, an answer must yield employers --------------------------

from live_utils import assert_discovery  # noqa: E402


def _result(**kw):
    base = {"employers": [{"company": "Acme A/S", "titles": ["Data Scientist"], "links": ["https://acme.example/jobs/1"]}],
            "requests": 1, "pushback": False, "stopped": None, "outcome": "ok"}
    return base | kw


def test_a_discovery_refusal_is_not_reached():
    with pytest.raises(pytest.skip.Exception) as skipped:
        assert_discovery("hellowork", _result(employers=[], pushback=True, outcome="refused",
                                              stopped="a consent page instead of the results"), [])
    assert str(skipped.value).startswith(f"{NOT_REACHED} hellowork: a consent page")


def test_a_discovery_answer_with_employers_passes():
    assert_discovery("hellowork", _result(), [], link_prefix="https://acme.example/")


@pytest.mark.parametrize("result, message", [
    (_result(employers=[]), "no employers"),
    (_result(outcome="error", stopped="HTTP 500"), "HTTP 500"),
    (_result(employers=[{"company": "", "titles": ["x"], "links": []}]), "name"),
    (_result(employers=[{"company": "Acme", "titles": [], "links": []}]), "title"),
    (_result(employers=[{"company": "Acme", "titles": ["x"], "links": ["javascript:void(0)"]}]), "link"),
])
def test_a_discovery_answer_that_no_longer_parses_is_a_change_naming_the_source_and_mode(result, message):
    with pytest.raises(AssertionError) as failed:
        assert_discovery("jobbsafari", result, [], link_prefix="http")
    assert str(failed.value).startswith("jobbsafari [employers]:") and message in str(failed.value)


# --- feed detection (#19): a careers page still shows its platform ------------------------------------------------

import live_utils  # noqa: E402
from live_employers import Careers  # noqa: E402
from live_utils import assert_detects  # noqa: E402

_ROW = Careers("https://acme.example/careers", "Copenhagen", "teamtailor", "acme")


def _resolved(monkeypatch, **found):
    from door.commands import companies

    result = {"input": _ROW.page, "platform": None, "entry": None, "evidence": "", "notes": []} | found
    monkeypatch.setattr(companies, "_resolve_core", lambda inputs, location="": {"results": [result]})


def test_a_page_that_still_shows_its_platform_passes(monkeypatch):
    _resolved(monkeypatch, platform="teamtailor", entry="acme", evidence="links to it")
    assert_detects("teamtailor", _ROW)


@pytest.mark.parametrize("found, message", [
    ({}, "found no feed"),
    ({"platform": "lever", "entry": "acme"}, "lever"),
    ({"platform": "teamtailor", "entry": "other"}, "other"),
])
def test_a_page_that_no_longer_shows_its_platform_is_a_change_naming_it_and_the_mode(monkeypatch, found, message):
    _resolved(monkeypatch, **found)
    monkeypatch.setattr(live_utils, "_page_refusal", lambda url: None)
    with pytest.raises(AssertionError) as failed:
        assert_detects("teamtailor", _ROW)
    assert str(failed.value).startswith("teamtailor [detection]:") and message in str(failed.value)


def test_a_page_that_refused_is_not_reached(monkeypatch):
    _resolved(monkeypatch)
    monkeypatch.setattr(live_utils, "_page_refusal", lambda url: "403 Client Error: Forbidden")
    with pytest.raises(pytest.skip.Exception) as skipped:
        assert_detects("teamtailor", _ROW)
    assert str(skipped.value).startswith(f"{NOT_REACHED} teamtailor: 403")


def test_a_host_the_other_door_must_not_read_is_never_fetched_to_tell_a_refusal(monkeypatch):
    """iCIMS's and Welcome to the Jungle's terms bar automated reading: their detection is the URL's alone."""
    _resolved(monkeypatch)
    monkeypatch.setattr(live_utils, "_page_refusal", lambda url: pytest.fail(f"fetched {url}"))
    with pytest.raises(AssertionError) as failed:
        assert_detects("icims", Careers("https://careers-sisk.icims.com/jobs/search?ss=1", "London", "icims", None))
    assert str(failed.value).startswith("icims [detection]:")


# --- the field contract (#19): over a small sample, each rule's share above its threshold -------------------------

from datetime import datetime, timedelta, timezone  # noqa: E402

from live_utils import assert_contract  # noqa: E402

_NOW = datetime.now(timezone.utc)


def _posting(i, **kw):
    base = {"id": f"jobindex.{i}", "title": f"Data Scientist {i}", "company": f"Firm {i} A/S", "location": "København",
            "url": f"https://www.jobindex.dk/vis-job/{i}", "description": f"Ad {i}: " + "we do things with data. " * 20,
            "posted_at": (_NOW - timedelta(days=i)).isoformat(), "source": "jobindex",
            "scraped_at": _NOW.isoformat()}
    return base | kw


_CONFIG = {"location": "Copenhagen"}


def test_a_sample_that_keeps_every_rule_passes():
    assert_contract("jobindex", [_posting(i) for i in range(8)], "listing", config=_CONFIG, descriptions=True)


@pytest.mark.parametrize("change, rule", [
    ({"title": ""}, "title"),
    ({"url": ""}, "url"),
    ({"company": ""}, "company"),
    ({"company": "Jobindex"}, "company"),
    ({"location": ""}, "location"),
    ({"location": "Berlin, Germany"}, "local"),
    ({"posted_at": None}, "posted_at"),
    ({"posted_at": (_NOW + timedelta(days=40)).isoformat()}, "posted_at"),
    ({"posted_at": "1999-01-01T00:00:00+00:00"}, "posted_at"),
    ({"description": "Apply now"}, "description"),
])
def test_a_rule_most_of_the_sample_breaks_fails_naming_the_site_the_mode_and_the_rule(change, rule):
    sample = [_posting(i, **change) for i in range(8)]
    with pytest.raises(AssertionError) as failed:
        assert_contract("jobindex", sample, "listing", config=_CONFIG, descriptions=True)
    assert str(failed.value).startswith(f"jobindex [listing]: {rule}")


def test_one_odd_posting_in_the_sample_is_tolerated():
    sample = [_posting(i) for i in range(9)] + [_posting(9, location="", company="")]
    assert_contract("jobindex", sample, "listing", config=_CONFIG, descriptions=True)


def test_the_same_description_on_every_posting_is_boilerplate():
    sample = [_posting(i, description="Read more about us and apply. " * 20) for i in range(6)]
    with pytest.raises(AssertionError) as failed:
        assert_contract("jobindex", sample, "details", config=_CONFIG, descriptions=True)
    assert str(failed.value).startswith("jobindex [details]: description")


def test_rules_a_site_does_not_keep_are_left_out():
    """A feed with no dates, a site that names no place, a listing without descriptions."""
    sample = [_posting(i, posted_at=None, location="", description="") for i in range(5)]
    assert_contract("greenhouse", sample, "listing", config=_CONFIG, dates=False, locations=False)


def test_a_listing_that_names_no_employer_leaves_the_company_rule_out():
    """A board whose list names only itself as the employer; its ad pages name the employer."""
    sample = [_posting(i, company="Globalnyt") for i in range(5)]
    with pytest.raises(AssertionError, match=r"^globalnyt \[listing\]: company"):
        assert_contract("globalnyt", sample, "listing", config=_CONFIG)
    assert_contract("globalnyt", sample, "listing", config=_CONFIG, companies=False)


def test_a_feed_without_a_country_skips_the_local_rule():
    sample = [_posting(i, location="Berlin, Germany") for i in range(5)]
    assert_contract("greenhouse", sample, "listing", config={})


def test_no_postings_is_a_change_and_an_invalid_posting_too():
    with pytest.raises(AssertionError, match=r"^reed \[listing\]: no postings"):
        assert_contract("reed", [], "listing", config=_CONFIG)
    with pytest.raises(AssertionError, match=r"^reed \[listing\]: not a JobPosting"):
        assert_contract("reed", [_posting(1, posted_at="soon")], "listing", config=_CONFIG)


# --- probe-sized (#19): a mode makes no more requests than it needs ---------------------------------------------------

import requests  # noqa: E402
import responses  # noqa: E402

from live_utils import REQUESTS, probe_sized  # noqa: E402


@responses.activate
def test_a_mode_within_its_requests_passes_and_robots_does_not_count():
    responses.add(responses.GET, "https://x.example/robots.txt", body="")
    responses.add(responses.GET, "https://x.example/jobs", body="ok")
    with probe_sized("reed", "listing") as made:
        requests.get("https://x.example/robots.txt")
        requests.get("https://x.example/jobs")
    assert made == ["https://x.example/jobs"]


@responses.activate
def test_a_mode_past_its_requests_fails_naming_the_site_and_the_mode():
    responses.add(responses.GET, "https://x.example/jobs", body="ok")
    with pytest.raises(AssertionError, match=r"^reed \[listing\]: 3 requests"):
        with probe_sized("reed", "listing"):
            for _ in range(REQUESTS["listing"] + 1):
                requests.get("https://x.example/jobs")


def test_each_mode_has_a_ceiling():
    assert REQUESTS["listing"] < REQUESTS["page2"] < REQUESTS["details"]


def test_a_refused_request_inside_a_mode_is_not_reached_and_another_failure_a_change():
    with pytest.raises(pytest.skip.Exception, match="not reached: reed: 403"):
        with probe_sized("reed", "page2"):
            raise requests.HTTPError("403 Client Error: Forbidden for url: https://x")
    with pytest.raises(AssertionError, match=r"^reed \[page2\]: request failed: 404"):
        with probe_sized("reed", "page2"):
            raise requests.HTTPError("404 Client Error: Not Found for url: https://x")


# --- listing and page 2 ---------------------------------------------------------------------------------------------

from types import SimpleNamespace  # noqa: E402

from live_utils import assert_listing, assert_page2  # noqa: E402


def _module(result):
    return SimpleNamespace(probe=lambda config: result)


def test_a_listing_probe_that_parses_passes_its_contract_and_returns_its_postings():
    sample = [_posting(i) for i in range(5)]
    got = assert_listing("jobindex", _module({"postings": sample, "structure_ok": True, "raw": "x"}), _CONFIG)
    assert got == sample


@pytest.mark.parametrize("result", [
    {"postings": [], "structure_ok": False, "wall": True, "reason": "HTTPError: 403"},
    {"postings": [], "structure_ok": False, "unreachable": True, "reason": "Timeout"},
])
def test_a_listing_probe_that_was_refused_is_not_reached(result):
    with pytest.raises(pytest.skip.Exception, match="not reached: jobindex"):
        assert_listing("jobindex", _module(result), _CONFIG)


@pytest.mark.parametrize("result, message", [
    ({"postings": [], "structure_ok": False, "reason": "no search results block"}, "no search results block"),
    ({"postings": [], "structure_ok": False, "robots": "disallowed", "reason": "RobotsBlocked"}, "robots"),
    ({"postings": [], "structure_ok": True}, "no postings"),
    (None, "no probe"),
    ({"postings": [], "structure_ok": False, "unreachable": True,
      "reason": "HTTPError: 404 Client Error: Not Found for url: https://x/sitemal.xml"}, "404"),
])
def test_a_listing_probe_that_no_longer_parses_is_a_change(result, message):
    with pytest.raises(AssertionError, match=rf"^jobindex \[listing\]: .*{message}"):
        assert_listing("jobindex", _module(result), _CONFIG)


def test_page_two_with_new_postings_passes():
    assert_page2("jobindex", [_posting(i) for i in range(5)], [_posting(i) for i in range(5, 10)], _CONFIG)


@pytest.mark.parametrize("page2, message", [
    ([], "no postings"),
    ([_posting(i) for i in range(5)], "page 1 again"),
])
def test_page_two_empty_or_page_one_again_is_a_change(page2, message):
    with pytest.raises(AssertionError, match=rf"^jobindex \[page2\]: {message}"):
        assert_page2("jobindex", [_posting(i) for i in range(5)], page2, _CONFIG)


def test_a_feeds_foreign_jobs_are_not_a_change():
    assert_contract("greenhouse", [_posting(i, location="Berlin, Germany") for i in range(5)], "listing", config=_CONFIG)


# --- zero hits: a failure names the site and the mode ---------------------------------------------------------------

from live_utils import assert_zero_hits, drain_zero_hit_state  # noqa: E402


def test_a_zero_hit_answer_not_recognised_fails_naming_the_mode():
    drain_zero_hit_state("reed")
    with pytest.raises(AssertionError, match=r"^reed \[zero_hits\]: the zero-hit page was not recognised"):
        assert_zero_hits("reed", [])


def test_a_nonsense_keyword_with_postings_fails_naming_the_mode():
    from door.scrapers import record_answered

    drain_zero_hit_state("reed")
    record_answered("reed")
    with pytest.raises(AssertionError, match=r"^reed \[zero_hits\]: a nonsense keyword found 1 postings"):
        assert_zero_hits("reed", [{"id": "reed.1"}])


def test_a_probes_timeout_is_not_reached():
    assert refused(["ReadTimeout: HTTPSConnectionPool(host='x', port=443): Read timed out."])
    assert refused(["ConnectTimeout: x"])
