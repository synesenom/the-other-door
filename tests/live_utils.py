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
