"""Helpers for the live smoke tests: their verdicts (#19).

A live test ends one of three ways, which `scripts/smoke_report.py` reads from the JUnit report:

- **pass**: the site answered and its format still parses;
- **changed**: the test failed, the site answered but no longer as the scraper reads it (the failure issue);
- **not reached**: the site refused the request or could not be reached (a 401, 403, 429 or 503, a timeout, a
  connection error): `not_reached_if_refused` skips the test with a message starting `NOT_REACHED`, here and
  in CI alike. Some sites refuse GitHub's runners, so a local run reaches them; the status page counts how
  many runs in a row a site was not reached.

A site that came back empty with no recorded errors, or with any error that is not a refusal, has changed.
"""

import re

import pytest

NOT_REACHED = "not reached:"

# How a scraper's recorded error says the site refused or was unreachable (requests' and the scrapers' wording).
_REFUSAL = re.compile(
    r"\b(?:401|403|429|503)\b|Too Many Requests|Forbidden|Unauthorized|Service Unavailable|pushback"
    r"|timed out|Max retries exceeded|NameResolution|Connection (?:aborted|refused|reset)",
    re.IGNORECASE,
)


def refused(errors: list) -> bool:
    """Whether every recorded error says the site refused or was unreachable (none: it answered)."""
    return bool(errors) and all(_REFUSAL.search(str(e)) for e in errors)


def not_reached(site: str, why: str) -> None:
    """Skip the test as not reached: *site* refused or could not be reached (*why*)."""
    pytest.skip(f"{NOT_REACHED} {site}: {why}")


def not_reached_if_refused(site: str, errors: list) -> None:
    """Skip the test as not reached when *site*'s errors are all refusals; otherwise let it fail as changed."""
    if refused(errors):
        not_reached(site, "; ".join(map(str, errors[:3])))


# A keyword no ad contains: a board must answer it with a recognised page that has no hits.
NONSENSE_KEYWORD = "zqxwvplmk"


def drain_zero_hit_state(site: str) -> None:
    """Clear what an earlier scrape left for *site*, before a zero-hit search."""
    from door.scrapers import drain_answered, drain_errors

    drain_errors(site)
    drain_answered(site)


def assert_zero_hits(site: str, postings: list) -> None:
    """After a search for `NONSENSE_KEYWORD`: *site* answered with a page it recognises and no hits.

    A refusal is not reached (skipped); any other error, a posting, or an answer the scraper did not record as
    one (`record_answered`) is a change: the site moved and a quiet day would now warn "the site may have changed".
    """
    from door.scrapers import drain_answered, drain_errors

    errors = drain_errors(site).get(site, [])
    answered = drain_answered(site)
    if errors:
        not_reached_if_refused(site, errors)
    assert not errors, f"{site}: errors on a zero-hit search: {errors[:3]}"
    assert postings == [], f"{site}: a nonsense keyword found {len(postings)} postings"
    assert answered, f"{site}: the zero-hit page was not recognised as an answer (the page may have changed)"


def fail(site: str, mode: str, message: str) -> str:
    """A live test's failure message: the site and the mode that changed come first (``reed [details]: ...``)."""
    return f"{site} [{mode}]: {message}"


def assert_discovery(source: str, result: dict, errors: list, *, link_prefix: str = "http") -> None:
    """One paced search of a discovery source (`run(config, budget=1, ...)`) still yields employers.

    A refusal (a 403 or 429, a redirect to a login page, a wall page where the results should be: the source's
    ``pushback``) is not reached; any other stop, no employers, or an employer without a name or a title, or
    with a link that is not one, is a change (mode ``employers``).
    """
    detail = f"{result.get('stopped')}; errors: {errors[:3]}"
    if result.get("pushback") or result.get("outcome") == "refused":
        not_reached(source, str(result.get("stopped") or errors[:3]))
    assert not result.get("stopped"), fail(source, "employers", f"the search stopped: {detail}")
    assert result.get("employers"), fail(source, "employers", f"no employers on a page of results: {detail}")
    for emp in result["employers"]:
        assert emp.get("company"), fail(source, "employers", f"an employer without a name: {emp}")
        assert emp.get("titles"), fail(source, "employers", f"{emp['company']}: an employer without a title")
        for link in emp.get("links") or []:
            assert link.startswith(link_prefix), fail(source, "employers", f"{emp['company']}: not a link: {link!r}")


def _page_refusal(url: str) -> str | None:
    """Why *url* refused one plain request (a refusal or an unreachable host), or None when it answered."""
    import requests

    from door.scrapers.http_client import PoliteSession

    try:
        PoliteSession(min_delay=0.0, max_delay=0.0, timeout=30, max_retries=0).get(url)
    except requests.RequestException as exc:
        return str(exc) if refused([str(exc)]) else None
    return None


def assert_detects(platform: str, careers=None) -> None:
    """A real employer's careers page (`live_employers.DETECTION`) still resolves to its platform and feed entry, by
    the detection `companies add` runs (`companies._resolve_core`: the page, the pages it links to, the feed's check).

    When it does not, the page is fetched once more (never a host whose terms bar reading it): a refusal is not
    reached, an answer is a change (mode ``detection``): the page or the platform's markers moved.
    """
    from door.commands import companies
    from door.core import ats_detect
    from live_employers import DETECTION

    row = careers or DETECTION[platform]
    found = companies._resolve_core([row.page], location=row.location)["results"][0]
    if (found.get("platform"), found.get("entry")) == (row.platform, row.entry):
        return
    shape = ats_detect.from_url(row.page)
    if not (shape is not None and shape.refusal == "must_not") and (why := _page_refusal(row.page)) is not None:
        not_reached(platform, why)   # a host whose terms bar reading it is never fetched
    got = f"{found['platform']} {found.get('entry')!r}" if found.get("platform") else "found no feed"
    notes = "; ".join(found.get("notes") or []) or found.get("evidence") or ""
    raise AssertionError(fail(platform, "detection", f"{row.page} {got}, expected {row.platform} {row.entry!r}. {notes}".strip()))
