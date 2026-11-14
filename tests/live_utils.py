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
from datetime import datetime, timedelta, timezone

import pytest

NOT_REACHED = "not reached:"

# How a scraper's recorded error says the site refused or was unreachable (requests' and the scrapers' wording).
_REFUSAL = re.compile(
    r"\b(?:401|403|429|503)\b|Too Many Requests|Forbidden|Unauthorized|Service Unavailable|pushback"
    r"|timed out|Timeout\b|Max retries exceeded|NameResolution|Connection (?:aborted|refused|reset)",
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
    assert not errors, fail(site, "zero_hits", f"errors on a zero-hit search: {errors[:3]}")
    assert postings == [], fail(site, "zero_hits", f"a nonsense keyword found {len(postings)} postings")
    assert answered, fail(site, "zero_hits", "the zero-hit page was not recognised as an answer (the page may have changed)")


# --- The field contract (#19): what a live scrape's postings must carry, per site, beyond "at least one" ---

# A line of an ad's text that says the page was a wall, not the ad (a JS, cookie, consent or bot-check page).
_WALL = re.compile(
    r"enable javascript|javascript (?:is )?(?:required|disabled)|cookies? (?:are|must)|accept (?:all )?cookies"
    r"|cookie consent|access denied|verify (?:that )?you are (?:a )?human|are you a robot|captcha|just a moment"
    r"|activez javascript|aktivér javascript|aktivera javascript",
    re.IGNORECASE,
)
_WALL_MAX = 600          # a wall is short; a real ad that mentions cookies is longer
_MAX_PAST_DAYS = {"search": 365, "collect": 3 * 365}   # a live test passes no `since`, so a board lists older ads too; a feed keeps long-open jobs
_GRACE_DAYS = 1          # a posting dated tomorrow is a time zone, not a fault

# Defaults of the rules (a site's `FIELD_EXCEPTIONS` row overrides `company_share`, `description_share`).
_COMPANY_SHARE = 0.9
_DESCRIPTION_SHARE = 0.9
_DESCRIPTION_MIN = 80
_LOCATION_SHARE = 0.9
_POSTED_AT_SHARE = 0.9


def _text(value) -> str:
    return str(value or "").strip()


def _squash(text: str) -> str:
    return re.sub(r"\W+", " ", text.casefold()).strip()


def _when(value) -> datetime | None:
    """A posting's `posted_at` as an aware datetime (a naive one is taken as UTC); None when missing or unreadable."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _own_names(site: str) -> set[str]:
    from door.core import sites

    names = {site.casefold()}
    if site in sites.SITES:
        names.add(sites.SITES[site].label.casefold())
    return names


def failing_title(postings: list[dict]) -> list[dict]:
    return [p for p in postings if not _text(p.get("title"))]


def failing_url(postings: list[dict]) -> list[dict]:
    return [p for p in postings if not _text(p.get("url")).lower().startswith(("http://", "https://"))]


def failing_company(postings: list[dict], site: str, *, own_name: bool = True) -> list[dict]:
    """Postings with no company, or (a board's search) the site's own name where the employer should stand."""
    own = _own_names(site) if own_name else set()
    return [p for p in postings if not _text(p.get("company")) or _text(p.get("company")).casefold() in own]


def failing_location(postings: list[dict], config: dict) -> list[dict]:
    """Postings whose location names another country than the profile's (empty and remote are fine)."""
    from door.matching import locality

    return [p for p in postings if locality.location_is_non_local(p.get("location"), config)]


def failing_posted_at(postings: list[dict], mode: str, *, future_days: float = _GRACE_DAYS,
                      now: datetime | None = None) -> list[dict]:
    """Postings dated in the future or older than the mode allows. A missing date is no fault here."""
    now = now or datetime.now(timezone.utc)
    latest = now + timedelta(days=future_days)
    earliest = now - timedelta(days=_MAX_PAST_DAYS[mode])
    out = []
    for p in postings:
        if p.get("posted_at") in (None, ""):
            continue
        when = _when(p["posted_at"])
        if when is None or when > latest or when < earliest:
            out.append(p)
    return out


def failing_description(postings: list[dict], minimum: int = _DESCRIPTION_MIN) -> list[dict]:
    """Postings whose description is shorter than *minimum* characters."""
    return [p for p in postings if len(_text(p.get("description"))) < minimum]


def failing_boilerplate(postings: list[dict]) -> list[dict]:
    """Postings whose description is not the ad: a wall page, a copy of the title or company (or a fallback built
    from them), or the same whole text under several different titles. An employer's ads may all open with the same
    "about us", and one job posted in several places may repeat its text under the same title: neither is boilerplate."""
    bad = []
    texts: dict[str, list[dict]] = {}
    for p in postings:
        text = _text(p.get("description"))
        if not text:
            continue
        flat = _squash(text)
        title, company = _squash(_text(p.get("title"))), _squash(_text(p.get("company")))
        fallbacks = {title, company, f"{title} {company}".strip(), f"{company} {title}".strip()}
        if (len(text) < _WALL_MAX and _WALL.search(text)) or flat in fallbacks or (
                title and company and flat.startswith(title) and flat.endswith(company) and len(flat) < len(title) + len(company) + 40):
            bad.append(p)
            continue
        texts.setdefault(flat, []).append(p)
    for group in texts.values():
        if len({_squash(_text(p.get("title"))) for p in group}) >= 3:
            bad.extend(group)
    return bad


def _example(p: dict, field: str) -> str:
    value = _text(p.get(field))[:40]
    return f"{_text(p.get('title'))[:30]!r} ({field}={value!r})"


def _held(failures: list[dict], total: int, share: float) -> bool:
    """Whether a rule held: with fewer than three postings a share means all, else at least *share* passed."""
    if total < 3:
        return not failures
    return (total - len(failures)) / total >= share


_PRESENT_SHARE = 0.6     # a place or a date most postings lack is a change; a few without one are not


def assert_field_contract(site: str, postings: list[dict], config: dict | None = None, *, mode: str = "search",
                          check: str | None = None, sample: int = 10, descriptions: bool = True, dates: bool = False,
                          locations: bool = False, companies: bool = True) -> None:
    """The first *sample* of a live scrape's postings carry the fields a run relies on (#19).

    Rules: every posting validates as a `JobPosting` and has a title and an http(s) url; the company is not empty
    and (a board's search) not the site's own name; a country board's locations are not another country's (when
    *config* has a location; not in `collect` mode); `posted_at`, when present, is not in the future nor older
    than the mode allows; the description is long enough and no wall page, no copy of the title or company, and
    not the same opening text on several ads. A rule holds when 90% of the sample passes (all of it for fewer than
    three postings); `live_matrix.FIELD_EXCEPTIONS[site]` loosens it.

    The live mode tests switch rules: without *descriptions* (a listing page carries no ad text, its teaser is often
    built from the title) neither the description's length nor the boilerplate rule is read; with *dates* and *locations* a
    `posted_at` and a `location` must be there on `_PRESENT_SHARE` of the sample; without *companies* (a list that
    names no employer, its ad pages do) the company is not read. The message names the site, *check* (the live
    mode, ``listing``) or else *mode*, and the rule: ``reed [listing]: rule 'location' held for 2/10 ...``.
    """
    from pydantic import ValidationError

    from door.core.models import JobPosting
    from live_matrix import FIELD_EXCEPTIONS

    assert mode in _MAX_PAST_DAYS, f"unknown mode {mode!r}"
    label = check or mode
    assert postings, fail(site, label, "rule 'no postings': the scrape returned nothing")
    config = config or {}
    exc = FIELD_EXCEPTIONS.get(site, {})
    rows = list(postings[:sample])
    n = len(rows)
    for p in rows:
        try:
            JobPosting.model_validate(p)
        except ValidationError as err:
            raise AssertionError(fail(site, label, f"rule 'model': not a JobPosting: {err.errors()[:2]}")) from err

    def rule(name: str, failures: list[dict], share: float, field: str) -> None:
        if _held(failures, n, share):
            return
        seen = [_example(p, field) for p in failures[:3]]
        raise AssertionError(fail(site, label, f"rule '{name}' held for {n - len(failures)}/{n} postings "
                                               f"(needs {round(share * 100)}%); e.g. {'; '.join(seen)}"))

    rule("title", failing_title(rows), 1.0, "title")
    rule("url", failing_url(rows), 1.0, "url")
    if companies:
        rule("company", failing_company(rows, site, own_name=mode == "search"), exc.get("company_share", _COMPANY_SHARE),
             "company")
    if locations:
        rule("location", [p for p in rows if not _text(p.get("location"))], _PRESENT_SHARE, "location")
    if mode == "search" and exc.get("location", True) and config.get("location"):
        from door.core import sites

        if site in sites.SITES and sites.SITES[site].countries:
            rule("location", failing_location(rows, config), exc.get("location_share", _LOCATION_SHARE), "location")
    if dates:
        rule("posted_at", [p for p in rows if p.get("posted_at") in (None, "")], _PRESENT_SHARE, "posted_at")
    rule("posted_at", failing_posted_at(rows, mode, future_days=exc.get("posted_at_future_days", _GRACE_DAYS)),
         _POSTED_AT_SHARE, "posted_at")
    described = exc.get("description_share", _DESCRIPTION_SHARE)
    if descriptions and described:
        rule("description", failing_description(rows, exc.get("description_min", _DESCRIPTION_MIN)), described,
             "description")
    if descriptions:
        rule("boilerplate", failing_boilerplate(rows), 1.0 if n < 3 else 0.9, "description")


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


# --- the field contract of a live mode (#19) ------------------------------------------------------------------------

def assert_contract(site: str, postings: list, mode: str, *, config: dict, descriptions: bool | None = None,
                    dates: bool | None = None, locations: bool | None = None, companies: bool = True) -> None:
    """`assert_field_contract` for a live mode test (*mode*: ``listing``, ``page2``, ``details``): a board's postings
    are a search's, a feed's a collect's, and the failure names the site and the mode.

    Left as None, a listing or page 2 needs a date and a place on most postings and no description (a listing page
    carries no ad text); ``details`` needs the description and leaves the date and the place to the listing (two
    ads are no sample for a share). *companies* off: the list names no employer (its ad pages do).
    """
    from door.core import sites

    details = mode == "details"
    entry = sites.SITES.get(site)
    assert_field_contract(
        site, postings, config, mode="search" if entry is not None and entry.board else "collect", check=mode,
        descriptions=details if descriptions is None else descriptions,
        dates=not details if dates is None else dates,
        locations=not details if locations is None else locations,
        companies=companies,
    )


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
    # A probe calls any failed fetch unreachable; a 404 or another answer that is no refusal is a change.
    if result.get("wall") or (result.get("unreachable") and refused([result.get("reason") or "unreachable"])):
        not_reached(site, result.get("reason") or "refused")
    assert not result.get("unreachable"), fail(site, "listing", f"the page is gone: {result.get('reason')}")
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
