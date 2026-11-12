#!/usr/bin/env python3
"""Scraper for employers on Jobylon, a Swedish applicant-tracking system.

Kind of site: an ATS whose customers publish their ads on ``emp.jobylon.com`` (Jobbsafari and Platsbanken
apply links point there). Jobylon has no per-employer board page and no open API; the feed it documents
(``developer.jobylon.com/feed-api``) is set up per customer on request, behind a secret hash. What every
employer can embed on its career page, and what needs no account, is Jobylon's *company widget*, so that is
the route, and an employer is followed by its Jobylon company number.

Configured by ``jobylon_companies`` (filled from ``profile/companies.json``): a list of company numbers,
e.g. ``["2420"]`` (or a widget link). Endpoints used:
  GET https://cdn.jobylon.com/jobs/companies/<id>/embed/v2/
      → the widget page. The server fills ``JBL.embed_v2['jobs']`` with every open ad of the company (id,
        ad path, title, locations); no paging, ``page_size`` only changes what the page shows.
  GET https://emp.jobylon.com/jobs/<id>-<slug>/
      → one ad: the schema.org ``JobPosting`` JSON-LD (description, date posted, place), fetched only for ads
        not in ``known_ids``.

Finding the company of a link: an ad link (``emp.jobylon.com/jobs/<id>-...``, or its ``/applications/jobs/<id>/``
apply form) names the ad, not the company; ``resolve`` reads the ad page, whose analytics script holds the
company number. A career page that embeds the widget (``jbl_company_id = <n>``) names it directly. There is no
JSON endpoint to confirm an entry with, so ``feed_url`` is None and no company name is probed.

Terms: Jobylon publishes no general terms of use for visitors (``https://www.jobylon.com/terms`` is a 404);
the only legal page found is its privacy policy, https://www.jobylon.com/privacy-policy, which says nothing
about reading ads. Nothing bans scraping, bots or text-and-data mining. robots.txt of ``emp.jobylon.com`` and
``cdn.jobylon.com`` bars named job aggregators (Jobrapido, Jooble, CareerJet, Adzuna, ...) and ``/jobs/*/preview/``;
``*`` is allowed and the sitemap (``/sitemap-jobs.xml``) is published. Checked 2026-10-31.
"""

import html as _html
import json
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests

from door.scrapers.sdk import (
    Detection, JobPosting, PoliteSession, PROBE_TIMEOUT_S, ProbeResult, followed_name, keep_local, make_job_id,
    parse_iso_date, parts, record_error, record_pushback, report, run_probe, scrape_feeds, strip_html, unfollowable,
)

_SITE = "jobylon"
_BASE = "https://emp.jobylon.com"
_WIDGET = "https://cdn.jobylon.com/jobs/companies/{}/embed/v2/"
_WIDGET_PATH = re.compile(r"/jobs/companies/(\d+)/embed")
_HEADERS = {"Accept": "text/html"}

_JOBS_MARKER = "JBL.embed_v2['jobs'] = ["
_JOB_START = re.compile(r"\{\s*id:\s*'(\d+)'")
_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")
_LD_JSON = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
_AD_COMPANY = re.compile(r"company_id\s*=\s*(\d+)")
_AD_PATH = re.compile(r"^(\d+)(?:-|$)")


# --- the company widget ---

def _js_string(block: str, key: str) -> str:
    """The single-quoted JavaScript string after ``key:`` in a widget job block, its ``\\uXXXX`` escapes decoded."""
    match = re.search(rf"\b{key}:\s*'((?:[^'\\]|\\.)*)'", block)
    return _ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), match.group(1)) if match else ""


def parse_widget(page: str) -> list[dict] | None:
    """The ads listed in a company widget page: ``{id, url, title, company, company_id, location}`` each.
    None when the page holds no job list (not a widget); an empty list for a company with no open ads. Pure."""
    start = page.find(_JOBS_MARKER)
    if start < 0:
        return None
    body = page[start + len(_JOBS_MARKER):]
    body = body[: body.find("];")] if "];" in body else body
    starts = [m.start() for m in _JOB_START.finditer(body)]
    items = []
    for begin, end in zip(starts, [*starts[1:], len(body)]):
        block = body[begin:end]
        items.append({
            "id": _JOB_START.match(block).group(1),
            "url": _js_string(block, "url"),
            "title": _js_string(block, "title").strip(),
            "company": _js_string(block, "company").strip(),
            "company_id": _js_string(block, "company_id"),
            "location": _js_string(block, "locations_text").strip(),
        })
    return items


# --- one ad page ---

def _ld_job(page: str) -> dict:
    """The schema.org JobPosting object of an ad page, ``{}`` when it has none."""
    for raw in _LD_JSON.findall(page):
        try:
            data = json.loads(raw, strict=False)
        except ValueError:
            continue
        for node in data if isinstance(data, list) else [data]:
            if isinstance(node, dict) and node.get("@type") == "JobPosting":
                return node
    return {}


def _ld_location(job: dict) -> str:
    places = job.get("jobLocation") or []
    names = []
    for place in places if isinstance(places, list) else [places]:
        address = (place or {}).get("address") or {}
        name = (address.get("addressLocality") or "").strip() if isinstance(address, dict) else ""
        if name and name not in names:
            names.append(name)
    return "; ".join(names)


def parse_ad(page: str) -> dict | None:
    """What an ad page holds: ``company_id``, ``title``, ``company``, ``posted_at`` (ISO text), ``location`` and
    the plain-text ``description``. None for a page with neither the JSON-LD nor the company number. Pure."""
    job = _ld_job(page)
    company = _AD_COMPANY.search(page)
    if not job and not company:
        return None
    hiring = job.get("hiringOrganization")
    return {
        "company_id": company.group(1) if company else "",
        "title": _html.unescape(job.get("title") or "").strip(),
        "company": (hiring.get("name") or "").strip() if isinstance(hiring, dict) else "",
        "posted_at": job.get("datePosted") or "",
        "location": _ld_location(job),
        "description": strip_html(job.get("description") or ""),
    }


# --- mapping ---

def _to_posting(item: dict, ad: dict | None, name: str, scraped_at: datetime) -> dict:
    """One widget item (and its ad page, when read) as a JobPosting dict; the followed *name* wins."""
    ad = ad or {}
    url = urljoin(_BASE + "/", item["url"]).split("?")[0]
    posting = JobPosting(
        id=make_job_id(_SITE, item["id"]),
        title=item["title"] or ad.get("title") or "",
        company=name or item["company"] or ad.get("company") or "",
        location=item["location"] or ad.get("location") or "",
        url=url,
        description=ad.get("description") or "",
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=item["id"],
        posted_at=parse_iso_date(ad.get("posted_at")),
        apply_type="external",
        apply_url=url,
    )
    return posting.model_dump(mode="json")


# --- entries ---

def _company_id(entry: str) -> str | None:
    """The company number of a ``jobylon_companies`` entry: the number itself or a widget link. Pure."""
    entry = entry.strip()
    if entry.isdigit():
        return entry
    match = _WIDGET_PATH.search(entry)
    return match.group(1) if match and "jobylon.com" in entry else None


def _widget_url(entry: str) -> str:
    return _WIDGET.format(_company_id(entry) or entry.strip())


def _fetch_widget(session: PoliteSession, entry: str) -> list[dict]:
    """The ads of an employer's widget. Raises on a bad entry, an HTTP error (a 429/403 is recorded as
    pushback first) or a page without a job list."""
    if _company_id(entry) is None:
        raise ValueError("not a Jobylon company number")
    try:
        page = session.get(_widget_url(entry), headers=_HEADERS).text
    except requests.HTTPError as exc:
        if getattr(exc.response, "status_code", None) in (403, 429):
            record_pushback(_SITE)
        raise
    items = parse_widget(page)
    if items is None:
        raise ValueError("the page has no Jobylon job list")
    return items


def _company_postings(session: PoliteSession, entry: str, scraped_at: datetime, known_ids: frozenset[str],
                      name: str) -> list[dict]:
    """One employer's new postings: its widget lists them, each unknown ad's page gives the text. An ad page
    that fails is recorded and left out (so the next run reads it again)."""
    items = _fetch_widget(session, entry)
    fresh = [i for i in items if i["id"] not in known_ids]
    postings = []
    for n, item in enumerate(fresh, 1):
        report("detail", n, len(fresh))
        try:
            ad = parse_ad(session.get(urljoin(_BASE + "/", item["url"]), headers=_HEADERS).text)
            if ad is None:
                raise ValueError("no JobPosting on the ad page")
        except Exception as exc:  # noqa: BLE001 - one ad never stops the employer
            message = f"error fetching ad {item['id']} of {entry!r}: {exc}"
            report(message)
            record_error(_SITE, message)
            continue
        postings.append(_to_posting(item, ad, name, scraped_at))
    return postings


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Return JobPosting dicts from the followed employers' Jobylon widgets (``jobylon_companies``)."""
    def fetch(session, entry, scraped_at):
        return _company_postings(session, entry, scraped_at, known_ids,
                                 followed_name(config, "jobylon_companies", entry))

    postings = scrape_feeds(_SITE, config.get("jobylon_companies") or [], fetch, headers=_HEADERS)
    return keep_local(postings, config, _SITE)


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the first employer's widget page. ``None`` when none is set."""
    entries: list[str] = config.get("jobylon_companies") or []
    if not entries:
        return None
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

    def fetch() -> str:
        return session.get(_widget_url(entries[0]), headers=_HEADERS).text

    def parse(page: str):
        items = parse_widget(page)
        if items is None:
            return [], False, "no `JBL.embed_v2['jobs']` list in the widget page"
        now = datetime.now(timezone.utc)
        return [_to_posting(i, None, "", now) for i in items], True, ""

    return run_probe(fetch, parse, "html")


# --- feed detection (issue #282) ---

def _ad_id(url: str) -> str | None:
    """The ad number of an ``emp.jobylon.com`` ad link (``/jobs/<id>-<slug>/`` or ``/applications/jobs/<id>/...``)."""
    host, path, _query = parts(url.strip())
    if host != "emp.jobylon.com":
        return None
    if len(path) >= 2 and path[0] == "jobs" and _AD_PATH.match(path[1]):
        return _AD_PATH.match(path[1]).group(1)
    if len(path) >= 3 and path[:2] == ["applications", "jobs"] and path[2].isdigit():
        return path[2]
    return None


def detect_url(url: str) -> Detection | None:
    """A company widget link names its company; an ad link names only the ad (its company is read from the
    ad page by `resolve`, so without a session it is "can't yet")."""
    host, path, _query = parts(url.strip())
    if host == "cdn.jobylon.com":
        match = _WIDGET_PATH.search("/" + "/".join(path))
        return Detection(_SITE, match.group(1), f"Jobylon company widget {match.group(1)}") if match else None
    ad = _ad_id(url)
    if ad:
        return unfollowable(_SITE, host, f"Jobylon ad {ad}: its company is read from the ad page", "cant_yet")
    return None


def resolve(session: PoliteSession, det: Detection, url: str) -> Detection:
    """*det* for an ad link, with the company read from the ad page; *det* itself when it already names a
    company or the page cannot be read."""
    ad_id = None if det.entry else _ad_id(url)
    if ad_id is None:
        return det
    try:
        ad = parse_ad(session.get(f"{_BASE}/jobs/{ad_id}/", headers=_HEADERS).text)
    except Exception:  # noqa: BLE001 - an ad that is gone names no company
        return det
    if not ad or not ad["company_id"]:
        return det
    who = f" ({ad['company']})" if ad["company"] else ""
    return Detection(_SITE, ad["company_id"], f"Jobylon ad {ad_id} belongs to company {ad['company_id']}{who}")


def feed_url(entry: str) -> str | None:
    """None: the widget is HTML, so an entry is not confirmed by a JSON job list."""
    return None


def name_probes(slug: str) -> list:
    """None to try: a Jobylon company is a number, not a name."""
    return []


def detect_html(html: str, url: str) -> Detection | None:
    """A career page that embeds the Jobylon widget (``jbl_company_id = <n>`` with Jobylon's embedder script)."""
    if "jobylon.com" not in html:
        return None
    match = re.search(r"jbl_company_id\s*=\s*['\"]?(\d+)", html)
    return Detection(_SITE, match.group(1), f"{url} embeds the Jobylon widget of company {match.group(1)}") if match else None
