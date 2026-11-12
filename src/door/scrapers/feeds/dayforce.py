#!/usr/bin/env python3
"""Scraper for the Dayforce candidate portal's public job search.

Every Dayforce career site (``jobs.dayforcehcm.com/<culture>/<client>/<portal>``) loads
its jobs from the portal's own JSON API, which needs no login and no key but a CSRF
token the site hands out itself:

  GET  https://jobs.dayforcehcm.com/api/auth/csrf
      → ``{"csrfToken": ...}`` (and the cookie that goes with it)
  POST https://jobs.dayforcehcm.com/api/geo/<client>/jobposting/search
      header ``X-CSRF-TOKEN``; JSON body ``{clientNamespace, jobBoardCode: <portal>,
      cultureCode, distanceUnit, paginationStart}``
      → ``{"jobPostings": [{jobPostingId, jobTitle, jobDescription (full text),
      postingStartTimestampUTC, postingLocations, hasVirtualLocation, ...}],
      "maxCount": n}``, 25 per page, paged by ``paginationStart``

The search already carries each job's description, so there is no detail request.
The employer's name is not in the answer; the client namespace stands in for it.

Configured by ``dayforce_companies``: ``<client>/<portal>`` (``natus/CANDIDATEPORTALSENSORY``),
or any ``jobs.dayforcehcm.com`` link into the portal.

Terms: https://www.dayforce.com/terms — nothing on scraping or bots. robots.txt on
jobs.dayforcehcm.com holds only content-signal comments, no Disallow rule.
"""

import json
import re
from datetime import datetime, timezone

from door.scrapers.sdk import (
    FEED_DELAY, JobPosting, PoliteSession, PROBE_TIMEOUT_S, ProbeResult, log_keyword_results, make_job_id,
    map_by_group, parse_iso_date, record_entry_error, record_error, report, run_probe, strip_html, workers, followed_name,
)
from door.scrapers.sdk import keep_local
from door.scrapers.sdk import Detection, NOT_ACCOUNTS, parts

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("dayforcehcm.com", "dayforce.com")

_SITE = "dayforce"
_HOST = "jobs.dayforcehcm.com"
_BASE = f"https://{_HOST}"
_HEADERS = {"Accept": "application/json"}
_CULTURE = "en-US"
_MAX_POSTINGS = 3000  # a safety stop for a runaway listing


def _portal(entry: str) -> tuple[str, str] | None:
    """``(client namespace, portal code)`` of a ``dayforce_companies`` entry: ``client/portal`` or a
    portal link (with or without its culture segment); ``None`` when it names no portal. Pure."""
    entry = entry.strip()
    if "://" in entry or "." in entry.split("/")[0]:
        det = detect_url(entry)
        entry = det.entry if det is not None and det.entry else ""
    path = [p for p in entry.split("/") if p]
    return (path[0].lower(), path[1]) if len(path) >= 2 else None


def _location_text(posting: dict) -> str:
    """The posting's locations joined by ``;``, led by ``Remote`` for a virtual location. Pure."""
    places = list(dict.fromkeys(
        (loc.get("formattedAddress") or "").strip() for loc in posting.get("postingLocations") or [] if isinstance(loc, dict)
    ))
    places = [p for p in places if p]
    if posting.get("hasVirtualLocation"):
        places.insert(0, "Remote")
    return "; ".join(places)


def _job_url(client: str, portal: str, posting_id) -> str:
    return f"{_BASE}/{_CULTURE}/{client}/{portal}/jobs/{posting_id}"


def _to_posting(item: dict, client: str, portal: str, scraped_at: datetime, name: str = "") -> dict:
    posting_id = item.get("jobPostingId")
    platform_id = f"{client}-{posting_id}"
    title = (item.get("jobTitle") or "").strip()
    company = name or client.replace("-", " ").title()
    url = _job_url(client, portal, posting_id)
    posting = JobPosting(
        id=make_job_id(_SITE, platform_id),
        title=title,
        company=company,
        location=_location_text(item),
        url=url,
        description=strip_html(item.get("jobDescription") or ""),
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=parse_iso_date(item.get("postingStartTimestampUTC")),
        apply_type="external",
        apply_url=url,
    )
    return posting.model_dump(mode="json")


def _items(data) -> list[dict]:
    jobs = data.get("jobPostings") if isinstance(data, dict) else None
    return [j for j in jobs or [] if isinstance(j, dict) and j.get("jobPostingId") is not None]


def _search(session: PoliteSession, client: str, portal: str, start: int) -> dict:
    """One page of the portal's search (the CSRF token is fetched with the session's cookie first)."""
    token = session.get(f"{_BASE}/api/auth/csrf", headers=_HEADERS).json()["csrfToken"]
    body = {"clientNamespace": client, "jobBoardCode": portal, "cultureCode": _CULTURE,
            "distanceUnit": 0, "paginationStart": start}
    return session.post(f"{_BASE}/api/geo/{client}/jobposting/search", json=body,
                        headers={**_HEADERS, "X-CSRF-TOKEN": token}).json()


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Every open posting of each configured Dayforce candidate portal."""
    entries = [e for e in config.get("dayforce_companies") or [] if e.strip()]
    if not entries:
        return []
    scraped_at = datetime.now(timezone.utc)
    session = PoliteSession(min_delay=FEED_DELAY[0], max_delay=FEED_DELAY[1], timeout=30, headers=_HEADERS)

    def fetch(entry: str) -> list[dict] | None:
        """One portal's postings; ``None`` after a recorded error."""
        portal = _portal(entry)
        if portal is None:
            record_error(_SITE, f"not a Dayforce portal (expected <client>/<portal>): {entry!r}")
            return None
        client, code = portal
        items: list[dict] = []
        start = 0
        try:
            while start < _MAX_POSTINGS:
                page = _search(session, client, code, start)
                items.extend(_items(page))
                start += len(page.get("jobPostings") or [])
                if not page.get("jobPostings") or start >= int(page.get("maxCount") or 0):
                    break
        except Exception as exc:
            report(f"error fetching postings for {entry!r}: {exc}")
            record_entry_error(_SITE, entry, f"error fetching postings for {entry!r}: {exc}")
            return None
        name = followed_name(config, "dayforce_companies", entry)
        return keep_local([_to_posting(i, client, code, scraped_at, name) for i in items
                           if f"{client}-{i['jobPostingId']}" not in known_ids], config, _SITE)

    fetched = map_by_group(entries, lambda e: _HOST, fetch, workers(config))
    seen: set[str] = set()
    postings: list[dict] = []
    for entry, company_postings in zip(entries, fetched):
        if company_postings is None:
            continue
        fresh = [p for p in company_postings if p["platform_id"] not in seen]
        seen.update(p["platform_id"] for p in fresh)
        log_keyword_results(_SITE, entry.strip(), fresh)
        postings.extend(fresh)
    return postings


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: page 1 of the first configured portal. ``None`` when none is set."""
    entries = [e for e in config.get("dayforce_companies") or [] if e.strip()]
    portal = _portal(entries[0]) if entries else None
    if portal is None:
        return None
    client, code = portal
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

    def fetch() -> str:
        return json.dumps(_search(session, client, code, 0))

    def parse(text: str):
        data = json.loads(text)
        if not isinstance(data, dict) or not isinstance(data.get("jobPostings"), list):
            return [], False, "no `jobPostings` list in the Dayforce search response"
        scraped_at = datetime.now(timezone.utc)
        return [_to_posting(j, client, code, scraped_at) for j in _items(data)], True, ""

    return run_probe(fetch, parse, "json")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

_LOCALE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]+)*$")


def _dayforce_entry(path: list[str]) -> str | None:
    """``client/portal`` from a Dayforce portal path ``[culture/]client/portal[/jobs/id]``; the culture
    segment (``en-US``) is told from the client by the ``jobs`` word that follows a portal."""
    if path and _LOCALE.match(path[0]) and not (len(path) >= 3 and path[2].lower() == "jobs"):
        path = path[1:]
    return f"{path[0].lower()}/{path[1]}" if len(path) >= 2 and path[0].lower() not in NOT_ACCOUNTS else None


def detect_url(url: str) -> Detection | None:
    """A Dayforce candidate-portal link and the ``client/portal`` it names."""
    host, path, _query = parts(url.strip())
    if host != "jobs.dayforcehcm.com":
        return None
    entry = _dayforce_entry(path)
    return Detection("dayforce", entry, f"Dayforce candidate portal link {url}") if entry else None

def feed_url(entry: str) -> str | None:
    """None: a link to the board names the account, no feed check is needed."""
    return None
