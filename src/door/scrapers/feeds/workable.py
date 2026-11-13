#!/usr/bin/env python3
"""Scraper for Workable: its cross-company job search, plus any companies listed.

The search (jobs.workable.com) covers every company hiring through Workable by
keyword and location — no company list needed. It reads ``search_keywords``
(falling back to ``role_targets``) and ``location`` from the profile config.

``workable_companies`` (optional) lists accounts to read whole, every open job
with its full description, from the jobs widget Workable's careers pages embed:
  GET https://apply.workable.com/api/v1/widget/accounts/<account>?details=true
      → ``{"name": ..., "jobs": [{title, shortcode, url, published_on,
      city, country, description, ...}]}``
An entry is the account slug or its careers URL (``apply.workable.com/<account>/``).
(The v3 ``POST /api/v3/accounts/<account>/jobs`` listing has no descriptions, so
it would cost one more request per job; the widget answers in one.)

API endpoint used (public, unauthenticated, not disallowed by robots.txt):
  GET https://jobs.workable.com/api/v1/jobs?query=<kw>&location=<loc>[&pageToken=<t>]
      → ``{"totalSize": N, "jobs": [...20 per page], "nextPageToken": "..."}``
      (``nextPageToken`` is absent on the last page)

Results are ordered by relevance rather than date, so every page up to
``max_pages_per_keyword`` (default ``_MAX_PAGES``) is read and postings older
than ``since`` are dropped here.

Terms: https://www.workable.com/terms — nothing on scraping. jobs.workable.com's
robots.txt allows the API (`ai-input=yes`); apply.workable.com's is read at run time.
"""

import json
from datetime import datetime, timezone
from urllib.parse import urlparse

from door.scrapers.sdk import (
    FEED_DELAY, JobPosting, PoliteSession, PROBE_TIMEOUT_S, ProbeResult, log_keyword_results, make_job_id,
    parse_iso_date, record_answered, record_entry_error, record_error, report, run_probe, strip_html, tracked, followed_name,
)
from door.scrapers.sdk import keep_local
from door.scrapers.sdk import Detection, Probe, first, parts

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("workable.com",)

_SITE = "workable"
_SEARCH_URL = "https://jobs.workable.com/api/v1/jobs"
_WIDGET_URL = "https://apply.workable.com/api/v1/widget/accounts/{account}"
_MAX_PAGES = 3

_HEADERS = {
    "Accept": "application/json",
}


def _description_text(job: dict) -> str:
    """The description, requirements and benefits sections as plain text."""
    sections = (job.get(k) for k in ("description", "requirementsSection", "benefitsSection"))
    return "\n\n".join(t for t in (strip_html(s) for s in sections if isinstance(s, str)) if t)


def _location_text(job: dict) -> str:
    """``"{city}, {country}"`` (or whichever is set), prefixed ``Remote`` for remote jobs."""
    loc = job.get("location") or {}
    parts = [(loc.get(k) or "").strip() for k in ("city", "countryName")]
    text = ", ".join(p for p in parts if p)
    if job.get("workplace") == "remote":
        return f"Remote, {text}" if text else "Remote"
    return text


def _search_params(keyword: str, location: str, page_token: str | None) -> dict[str, str]:
    """Query parameters for one search page; empty location and token are left out."""
    params = {"query": keyword}
    if location:
        params["location"] = location
    if page_token:
        params["pageToken"] = page_token
    return params


def _keywords(config: dict) -> list[str]:
    # search_keywords broadens retrieval; fall back to role_targets when absent or empty.
    return list(config.get("search_keywords") or config.get("role_targets") or [])


def _to_posting(job: dict, scraped_at: datetime) -> dict:
    """Map one search result to a JobPosting dict."""
    platform_id = str(job.get("id") or "")
    title = (job.get("title") or "").strip()
    company = ((job.get("company") or {}).get("title") or "").strip() or "Unknown"
    posted = parse_iso_date(job.get("created"))
    url = job.get("url") or ""
    posting = JobPosting(
        id=make_job_id(_SITE, platform_id),
        title=title,
        company=company,
        location=_location_text(job),
        url=url,
        description=_description_text(job),
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=posted.isoformat() if posted else None,
        apply_type="external",
        apply_url=url,
    )
    return posting.model_dump(mode="json")


def _account(entry: str) -> str:
    """The account slug in a ``workable_companies`` entry: a slug or a careers URL. Pure."""
    entry = entry.strip()
    if "/" not in entry:
        return entry.lower()
    parts = [p for p in urlparse(entry if "://" in entry else f"https://{entry}").path.split("/") if p]
    return parts[0].lower() if parts else ""


def _widget_location(job: dict) -> str:
    """``"{city}, {country}"`` of a widget job, prefixed ``Remote`` when it is remote."""
    text = ", ".join(p for p in ((job.get("city") or "").strip(), (job.get("country") or "").strip()) if p)
    if job.get("telecommuting"):
        return f"Remote, {text}" if text else "Remote"
    return text


def _widget_posting(job: dict, company: str, scraped_at: datetime) -> dict:
    """Map one widget job to a JobPosting dict."""
    platform_id = str(job.get("shortcode") or "")
    title = (job.get("title") or "").strip()
    url = job.get("url") or job.get("shortlink") or ""
    posting = JobPosting(
        id=make_job_id(_SITE, platform_id),
        title=title,
        company=company,
        location=_widget_location(job),
        url=url,
        description=strip_html(job.get("description") or ""),
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=parse_iso_date(job.get("published_on") or job.get("created_at")),
        apply_type="external",
        apply_url=job.get("application_url") or url,
    )
    return posting.model_dump(mode="json")


def _scrape_companies(session: PoliteSession, entries: list[str], seen_ids: set[str], scraped_at: datetime,
                      config: dict | None = None) -> list[dict]:
    """Every open job of each listed account, through the jobs widget; the followed employer's name
    (``config["_names"]``) wins over the account's own."""
    postings: list[dict] = []
    for entry in tracked(entries):
        account = _account(entry)
        try:
            data = session.get(_WIDGET_URL.format(account=account), headers=_HEADERS, params={"details": "true"}).json()
        except Exception as exc:
            report(f"error fetching account {account!r}: {exc}")
            record_entry_error(_SITE, entry, f"error fetching account {account!r}: {exc}")
            continue
        company = followed_name(config or {}, "workable_companies", entry, (data.get("name") or account).strip())
        account_postings = []
        for job in data.get("jobs") or []:
            platform_id = str(job.get("shortcode") or "")
            if not platform_id or platform_id in seen_ids:
                continue
            seen_ids.add(platform_id)
            account_postings.append(_widget_posting(job, company, scraped_at))
        account_postings = keep_local(account_postings, config or {}, _SITE)
        log_keyword_results(_SITE, account, account_postings)
        postings.extend(account_postings)
    return postings


def _fetch_page(session: PoliteSession, keyword: str, location: str, page_token: str | None) -> dict:
    resp = session.get(_SEARCH_URL, headers=_HEADERS, params=_search_params(keyword, location, page_token))
    return resp.json()


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Return JobPosting dicts from the listed Workable accounts, then Workable's
    job search, one query per keyword.

    ``config["_mode"]`` (set by the engine) narrows it: ``"search"`` is the keyword search only
    (a board), ``"collect"`` the followed accounts only (a feed); absent, both.
    """
    mode = config.get("_mode")
    keywords = [] if mode == "collect" else _keywords(config)
    companies: list[str] = [] if mode == "search" else config.get("workable_companies") or []
    if not keywords and not companies:
        return []
    location = (config.get("location") or "").strip()
    max_pages = config.get("max_pages_per_keyword") or _MAX_PAGES
    since: datetime | None = kwargs.get("since")

    scraped_at = datetime.now(timezone.utc)
    session = PoliteSession(min_delay=FEED_DELAY[0], max_delay=FEED_DELAY[1], timeout=30, headers=_HEADERS)
    seen_ids: set[str] = set()
    postings: list[dict] = _scrape_companies(session, companies, seen_ids, scraped_at, config)

    for keyword in keywords:
        keyword_postings: list[dict] = []
        page_token: str | None = None
        for page in range(1, max_pages + 1):
            try:
                data = _fetch_page(session, keyword, location, page_token)
            except Exception as exc:
                report(f"search error (keyword={keyword!r}, page={page}): {exc}")
                record_error(_SITE, f"search error (keyword={keyword!r}, page={page}): {exc}")
                break
            if page == 1 and isinstance(data, dict) and data.get("jobs") == []:
                record_answered(_SITE)
            for job in data.get("jobs") or []:
                platform_id = str(job.get("id") or "")
                if not platform_id or platform_id in seen_ids:
                    continue
                seen_ids.add(platform_id)
                posted = parse_iso_date(job.get("created"))
                if since is not None and posted is not None and posted < since:
                    continue
                keyword_postings.append(_to_posting(job, scraped_at))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        log_keyword_results(_SITE, keyword, keyword_postings)
        postings.extend(keyword_postings)

    return postings


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: page 1 of the first keyword, or without
    keywords the first listed account. ``None`` when neither is set."""
    keywords = _keywords(config)
    companies = config.get("workable_companies") or []
    if not keywords and companies:
        account = _account(companies[0])
        session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

        def fetch_account() -> str:
            return session.get(_WIDGET_URL.format(account=account), headers=_HEADERS, params={"details": "true"}).text

        def parse_account(text: str):
            data = json.loads(text)
            jobs = data.get("jobs") if isinstance(data, dict) else None
            if not isinstance(jobs, list):
                return [], False, "no `jobs` list in the Workable widget response"
            company = (data.get("name") or account).strip()
            scraped_at = datetime.now(timezone.utc)
            return [_widget_posting(j, company, scraped_at) for j in jobs if isinstance(j, dict) and j.get("shortcode")], True, ""

        return run_probe(fetch_account, parse_account, "json")
    if not keywords:
        return None
    location = (config.get("location") or "").strip()
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

    def fetch() -> str:
        return session.get(_SEARCH_URL, headers=_HEADERS, params=_search_params(keywords[0], location, None)).text

    def parse(text: str):
        data = json.loads(text)
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, list):
            return [], False, "no `jobs` list in the Workable search response"
        scraped_at = datetime.now(timezone.utc)
        return [_to_posting(j, scraped_at) for j in jobs if isinstance(j, dict) and j.get("id")], True, ""

    return run_probe(fetch, parse, "json")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

# Workable's own cross-company board: an aggregator, not an employer's page.
JOB_BOARD_HOSTS = ("jobs.workable.com",)


def detect_url(url: str) -> Detection | None:
    """A Workable careers link (``apply.workable.com/<account>``) and the account it names."""
    host, path, _query = parts(url.strip())
    if host != "apply.workable.com":
        return None
    account = first(path)
    return Detection("workable", account, f"Workable careers link {url}") if account else None

def feed_url(entry: str) -> str | None:
    """None: a link to the board names the account, no feed check is needed."""
    return None


def name_probes(slug: str) -> list[Probe]:
    """The public widget API to try for a company name's *slug*."""
    return [Probe(f"https://apply.workable.com/api/v1/widget/accounts/{slug}", "jobs", f"Workable account {slug}")]
