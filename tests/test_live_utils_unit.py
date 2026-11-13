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
