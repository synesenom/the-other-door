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
