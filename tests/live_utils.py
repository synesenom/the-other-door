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

import contextlib
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


# --- the field contract (#19) ---------------------------------------------------------------------------------------

SAMPLE = 10              # postings a contract reads, the first ones
DESCRIPTION_FLOOR = 200  # characters a detail page's description has at least
MAX_AGE_DAYS = 730       # a posting older than this is not a plausible date
# The share of the sample that must keep each rule: one odd posting in ten is tolerated, a place or a date that most
# postings lack is not.
SHARES = {"title": 0.9, "url": 0.9, "company": 0.8, "location": 0.6, "local": 0.8, "posted_at": 0.6,
          "description": 0.8}
BOILERPLATE_SHARE = 0.5  # more than this share of one description is boilerplate, not ads


def _site_names(site: str) -> set[str]:
    from door.core import sites

    entry = sites.SITES.get(site)
    return {site.lower(), *((entry.label.lower(),) if entry is not None and entry.label else ())}


def _country_board(site: str) -> bool:
    from door.core import sites

    entry = sites.SITES.get(site)
    return entry is not None and entry.board and bool(entry.countries)


def _plausible(posted_at, now) -> bool:
    from datetime import timedelta

    from door.scrapers import parse_iso_date

    when = posted_at if hasattr(posted_at, "tzinfo") else parse_iso_date(posted_at)
    if when is None:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=now.tzinfo)
    return now - timedelta(days=MAX_AGE_DAYS) <= when <= now + timedelta(days=2)


def assert_contract(site: str, postings: list, mode: str, *, config: dict, descriptions: bool | None = None,
                    dates: bool | None = None, locations: bool | None = None) -> None:
    """The fields of *site*'s postings still parse, over the first `SAMPLE` (mode *mode*: ``listing``, ``page2``,
    ``details``). Each rule must hold for its `SHARES` of the sample; the first that does not fails, naming the site,
    the mode and the rule (``reed [listing]: location: 2/10 ...``):

    - every posting is a `JobPosting`; ``title``, ``url`` and ``company`` are not empty, the company is not the
      site's own name;
    - with *locations*: ``location`` is not empty, and for a country board with a ``location`` in *config* whose
      country The other door knows, local (`locality.location_is_non_local`; a feed lists an employer's jobs
      everywhere, and the engine drops the foreign ones);
    - with *dates*: ``posted_at`` is plausible: within `MAX_AGE_DAYS` and not more than two days ahead;
    - with *descriptions* (a detail page was read): ``description`` has `DESCRIPTION_FLOOR` characters, and no one
      text is most of them (boilerplate).

    Left as None, *descriptions* is on for ``details`` only, and *locations* and *dates* off for it (two ads are no
    sample for a share; the listing checked them).
    """
    details = mode == "details"
    descriptions = details if descriptions is None else descriptions
    locations = not details if locations is None else locations
    dates = not details if dates is None else dates
    from datetime import datetime, timezone

    from pydantic import ValidationError

    from door.core.models import JobPosting
    from door.matching import locality

    sample = list(postings)[:SAMPLE]
    assert sample, fail(site, mode, "no postings")
    for p in sample:
        try:
            JobPosting.model_validate(p)
        except ValidationError as exc:
            raise AssertionError(fail(site, mode, f"not a JobPosting: {exc.errors()[:2]} in {p.get('url') or p.get('id')}"))

    own = _site_names(site)
    now = datetime.now(timezone.utc)
    rules = [
        ("title", lambda p: bool((p.get("title") or "").strip()), sample),
        ("url", lambda p: (p.get("url") or "").startswith("http"), sample),
        ("company", lambda p: bool((p.get("company") or "").strip()) and p["company"].strip().lower() not in own, sample),
    ]
    if locations:
        rules.append(("location", lambda p: bool((p.get("location") or "").strip()), sample))
        if _country_board(site) and config.get("location") and locality.enabled(config):
            placed = [p for p in sample if (p.get("location") or "").strip()]
            rules.append(("local", lambda p: not locality.location_is_non_local(p["location"], config), placed))
    if dates:
        rules.append(("posted_at", lambda p: _plausible(p.get("posted_at"), now), sample))
    if descriptions:
        rules.append(("description", lambda p: len((p.get("description") or "").strip()) >= DESCRIPTION_FLOOR, sample))

    for rule, keeps, among in rules:
        if not among:
            continue
        broken = [p for p in among if not keeps(p)]
        if len(among) - len(broken) < SHARES[rule] * len(among):
            shown = [{k: p.get(k) for k in ("title", "company", "location", "posted_at", "url")} for p in broken[:2]]
            if rule == "description":
                shown = [{"url": p.get("url"), "description": (p.get("description") or "")[:80]} for p in broken[:2]]
            raise AssertionError(fail(site, mode, f"{rule}: {len(broken)}/{len(among)} break it, e.g. {shown}"))

    if descriptions:
        texts = [(p.get("description") or "").strip() for p in sample]
        if len(texts) >= 3:
            top = max(texts.count(t) for t in set(texts))
            assert top <= BOILERPLATE_SHARE * len(texts), \
                fail(site, mode, f"description: {top}/{len(texts)} postings share one text (boilerplate): {texts[0][:80]!r}")


# --- probe-sized (#19) --------------------------------------------------------------------------------------------

# The requests a mode makes at most, robots.txt aside: the listing is one page (and a token or session page some
# sites need first); page 2 one more listing page; details the listing and two detail pages.
REQUESTS = {"listing": 2, "page2": 3, "details": 5}


@contextlib.contextmanager
def probe_sized(site: str, mode: str, most: int | None = None):
    """Count the requests made inside (robots.txt aside; yields their URLs) and fail when they are more than *mode*'s
    ceiling (`REQUESTS`) or *most*: a live test reads one page and a few ads, never a site's whole list. A request
    that raises inside is not reached when it was refused, else a change."""
    from unittest import mock

    import requests

    made: list[str] = []
    real = requests.Session.request

    def request(self, method, url, *args, **kwargs):
        if not str(url).split("?", 1)[0].endswith("/robots.txt"):
            made.append(str(url))
        return real(self, method, url, *args, **kwargs)

    with mock.patch.object(requests.Session, "request", request):
        try:
            yield made
        except requests.RequestException as exc:
            not_reached_if_refused(site, [str(exc)])
            raise AssertionError(fail(site, mode, f"request failed: {exc}")) from exc
    ceiling = REQUESTS[mode] if most is None else most
    assert len(made) <= ceiling, fail(site, mode, f"{len(made)} requests, more than {ceiling}: {made[:6]}")


def assert_listing(site: str, module, config: dict, **contract) -> list[dict]:
    """Page 1 of *site* through its scraper's ``probe(config)`` (one request): the page still parses and its postings
    keep the field contract (*contract*: `assert_contract`'s switches). Returns the postings.

    A wall or an unreachable host is not reached; a page that no longer parses, robots.txt now disallowing it, or
    no postings is a change (mode ``listing``)."""
    with probe_sized(site, "listing"):
        result = module.probe(config)
    assert result is not None, fail(site, "listing", f"no probe for {config}")
    if result.get("wall") or result.get("unreachable"):
        not_reached(site, result.get("reason") or "refused")
    assert result.get("robots") != "disallowed", fail(site, "listing", f"robots.txt disallows it: {result.get('reason')}")
    assert result.get("structure_ok"), fail(site, "listing", f"the page no longer parses: {result.get('reason')}")
    assert_contract(site, result["postings"], "listing", config=config, **contract)
    return result["postings"]


PAGE2_NEW_SHARE = 0.5  # page 2 lists mostly postings page 1 did not


def assert_page2(site: str, page1: list[dict], page2: list[dict], config: dict, **contract) -> None:
    """Page 2 of a listing still parses: it has postings, mostly ones page 1 did not list (a page parameter the site
    ignores serves page 1 again), and they keep the field contract (mode ``page2``)."""
    assert page2, fail(site, "page2", "no postings on page 2")
    first = {p.get("id") or p.get("url") for p in page1}
    new = [p for p in page2 if (p.get("id") or p.get("url")) not in first]
    assert len(new) >= PAGE2_NEW_SHARE * len(page2), \
        fail(site, "page2", f"page 1 again: {len(page2) - len(new)}/{len(page2)} postings were on page 1")
    assert_contract(site, page2, "page2", config=config, **contract)
