#!/usr/bin/env python3
"""Scraper for Taleez career sites (issue #556): a French recruitment system (taleez.com) with some 1,100 French employers.

Kind: a per-company feed (a JSON job list plus one JSON-LD ad page per job), no login, no key.
Every Taleez customer has a career site on ``<slug>.taleez.com``, drawn by script from a public JSON list; the ads
themselves are on the vendor's host:

  GET https://<slug>.taleez.com/api/careez
      → the employer (``name``, ``slug``) and every open job as ``jobs[]``: ``id``, ``label`` (the title), ``slug``,
        ``contract`` (CDI, CDD, INTERNSHIP, ...), ``location`` (``city``, ``postalCode``, ``region``, ``country``),
        ``publishDate`` and ``creationDate`` (milliseconds since the epoch), ``lang``, ``remote``. No paging, no text.
  GET https://taleez.com/apply/<job slug>
      → HTML whose ``<script id="jobPostingSnippet" type="application/ld+json">`` is a schema.org ``JobPosting``:
        ``description`` and ``qualifications`` (HTML), ``datePosted``, ``hiringOrganization``, ``jobLocation``

Answers are gzipped even when not asked for (``requests`` unpacks them). A job in ``known_ids`` is not fetched;
an ad that cannot be read is recorded and skipped. A job link names no tenant (its slug ends with the employer's
name, which is no safe key), so an apply link is not followed; the spontaneous-application link
``taleez.com/apply/sp/<slug>`` and the career host are.

Configured by ``taleez_companies`` in the employer list: the tenant slug (``donecle``, read as
``donecle.taleez.com``), or any link on its career host.

Terms: https://taleez.com/mentions-legales (the vendor's legal notice) carries only a generic intellectual-property
clause and no ban on reading public job pages or on bots. robots.txt of taleez.com disallows ``/api/``, ``/files/``,
``/feeds/``, ``/widgets/`` and a few more paths and names the job sitemaps; the tenant hosts' robots.txt names only
a sitemap. The list is the endpoint the career site itself calls. Checked 2026-11-01.
"""

import json
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from door.scrapers.sdk import (
    Detection, JobPosting, NOT_ACCOUNTS, PROBE_TIMEOUT_S, PoliteSession, Probe, ProbeResult, RobotsBlocked,
    followed_name, host_of, keep_local, make_job_id, parts, record_entry_error, record_error, record_pushback, report,
    run_probe, scrape_feeds, strip_html, workers,
)

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("taleez.com",)

_SITE = "taleez"
_KEY = "taleez_companies"
_SUFFIX = ".taleez.com"
_AD = "https://taleez.com/apply/"
_HEADERS = {"Accept": "application/json, text/html"}
_NOT_TENANTS = NOT_ACCOUNTS | {"files", "cdn", "help", "support", "blog", "pro", "status", "mail", "assets", "static"}
_PUSHBACK = (401, 403, 429)

FEED_KEY = "jobs"


# --- pure helpers ---

def _slug(entry: str) -> str:
    """The tenant slug of a ``taleez_companies`` entry: a slug, a ``<slug>.taleez.com`` host or a link on it, or a
    ``taleez.com/apply/sp/<slug>`` link. Pure."""
    entry = entry.strip().lower()
    if "." not in entry and "/" not in entry:
        return entry
    det = detect_url(entry if "://" in entry else f"https://{entry}")
    return det.entry if det is not None and det.entry else entry


def feed_url(entry: str) -> str | None:
    """The job list of *entry*; a detection is kept only when it lists jobs (under `FEED_KEY`)."""
    return f"https://{_slug(entry)}{_SUFFIX}/api/careez"


def _location_text(location, remote: bool = False) -> str:
    """"City, CC" from a job's ``location`` (the region stands in for a missing city); ``Remote`` for a remote job
    with no place at all. Pure."""
    place = location if isinstance(location, dict) else {}
    where = str(place.get("city") or place.get("region") or "").strip()
    text = ", ".join(p for p in (where, str(place.get("country") or "").strip()) if p)
    return text or ("Remote" if remote else "")


def _date(job: dict) -> datetime | None:
    """The day a job was published (else created), from milliseconds since the epoch. Pure."""
    for key in ("publishDate", "creationDate"):
        value = job.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    return None


def parse_list(text: str) -> tuple[str, list[dict]]:
    """``(employer name, jobs)`` of a tenant's job list; each job ``{id, title, slug, url, location, posted_at}``.
    Raises ``ValueError`` when the text is no job list (an HTML error page, a block page). Pure."""
    try:
        data = json.loads(text or "")
    except ValueError as exc:
        raise ValueError(f"not a Taleez job list: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get(FEED_KEY), list):
        raise ValueError("no jobs list in Taleez's answer")
    jobs = []
    for raw in data[FEED_KEY]:
        if not isinstance(raw, dict):
            continue
        job_id, slug, title = str(raw.get("id") or "").strip(), str(raw.get("slug") or "").strip(), str(raw.get("label") or "").strip()
        if not (job_id and slug and title):
            continue
        jobs.append({
            "id": job_id,
            "title": re.sub(r"\s+", " ", title),
            "slug": slug,
            "url": _AD + slug,
            "location": _location_text(raw.get("location"), bool(raw.get("remote"))),
            "posted_at": _date(raw),
        })
    return str(data.get("name") or "").strip(), jobs


def parse_ad(html: str) -> dict | None:
    """``{description, organization}`` from an ad page's JSON-LD; ``None`` when it has none. Pure."""
    tag = BeautifulSoup(html or "", "html.parser").find("script", id="jobPostingSnippet")
    if tag is None:
        return None
    try:
        node = json.loads(tag.string or tag.get_text(), strict=False)
    except ValueError:
        return None
    if not isinstance(node, dict):
        return None
    text = "\n\n".join(t for t in (strip_html(str(node.get(k) or "")) for k in ("description", "qualifications")) if t)
    org = node.get("hiringOrganization")
    return {"description": text, "organization": str(org.get("name") or "").strip() if isinstance(org, dict) else ""}


def _to_posting(job: dict, description: str, company: str, scraped_at: datetime) -> dict:
    posting = JobPosting(
        id=make_job_id(_SITE, job["id"]),
        title=job["title"],
        company=company,
        location=job["location"],
        url=job["url"],
        description=description,
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=job["id"],
        posted_at=job["posted_at"],
        apply_type="external",
        apply_url=job["url"],
    )
    return posting.model_dump(mode="json")


def _status(exc: Exception) -> int | None:
    return getattr(getattr(exc, "response", None), "status_code", None)


# --- network ---

def _tenant_postings(session: PoliteSession, entry: str, scraped_at: datetime, known_ids: frozenset[str],
                     name: str) -> list[dict]:
    """One tenant's postings. Raises when its list cannot be read (or is not one: a tenant that is gone is served
    an HTML error page); a refusal is recorded as pushback and ends the board."""
    try:
        channel, jobs = parse_list(session.get(feed_url(entry)).text)
    except (requests.RequestException, RobotsBlocked) as exc:
        if _status(exc) in _PUSHBACK:
            record_pushback(_SITE)
        raise
    jobs = [j for j in jobs if j["id"] not in known_ids]
    out: list[dict] = []
    for n, job in enumerate(jobs, 1):
        report("detail", n, len(jobs))
        try:
            ad = parse_ad(session.get(job["url"]).text)
        except (requests.RequestException, RobotsBlocked) as exc:
            if _status(exc) in _PUSHBACK:
                record_pushback(_SITE)
                record_entry_error(_SITE, entry, f"{entry!r} refused job {job['id']} ({_status(exc)}); stopped", blocked=True)
                break
            record_error(_SITE, f"error fetching job {job['id']} of {entry!r}: {exc}")
            continue
        if ad is None:
            record_error(_SITE, f"job {job['id']} of {entry!r} has no ad data")
            continue
        out.append(_to_posting(job, ad["description"], name or channel or ad["organization"] or _slug(entry), scraped_at))
    return out


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Every open job of each configured Taleez career site."""
    entries = [e for e in config.get(_KEY) or [] if e.strip()]

    def fetch(session, entry, scraped_at):
        return _tenant_postings(session, entry, scraped_at, known_ids, followed_name(config, _KEY, entry, ""))

    return keep_local(scrape_feeds(_SITE, entries, fetch, group=lambda e: host_of(feed_url(e)),
                                   max_workers=workers(config), headers=_HEADERS), config, _SITE)


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the first tenant's job list (one request). ``None`` when none is set.
    The list has no text, so a posting here carries the title and link only."""
    entries = [e for e in config.get(_KEY) or [] if e.strip()]
    if not entries:
        return None
    entry = entries[0]
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

    def fetch() -> str:
        return session.get(feed_url(entry)).text

    def parse(text: str):
        try:
            channel, jobs = parse_list(text)
        except ValueError as exc:
            return [], False, str(exc)
        now = datetime.now(timezone.utc)
        return [_to_posting(j, "", channel or _slug(entry), now) for j in jobs], True, ""

    return run_probe(fetch, parse, "json")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

def _tenant_of(host: str) -> str | None:
    """The slug a ``<slug>.taleez.com`` host names; ``None`` for the vendor's shared hosts."""
    if not host.endswith(_SUFFIX):
        return None
    label = host[: -len(_SUFFIX)]
    return None if not label or "." in label or label in _NOT_TENANTS else label


def detect_url(url: str) -> Detection | None:
    """A link on a Taleez career site (``<slug>.taleez.com``) or the spontaneous-application link
    ``taleez.com/apply/sp/<slug>``, and the tenant it names. A job link (``taleez.com/apply/<job>``) names none."""
    host, path, _query = parts(url.strip())
    if host in ("taleez.com", "www.taleez.com"):
        if len(path) >= 3 and path[0].lower() == "apply" and path[1].lower() == "sp" and path[2]:
            return Detection(_SITE, path[2].lower(), f"Taleez spontaneous-application link {host}/apply/sp/{path[2].lower()}")
        return None
    tenant = _tenant_of(host)
    return Detection(_SITE, tenant, f"Taleez career site {host}") if tenant else None


def name_probes(slug: str) -> list[Probe]:
    """The public job list to try for a company name's *slug*."""
    return [Probe(feed_url(slug), FEED_KEY, f"Taleez site {slug}")]


def detect_cname(host: str, target: str, where: str) -> Detection | None:
    """A career host that is a CNAME for a tenant of Taleez's."""
    tenant = _tenant_of(target)
    return Detection(_SITE, tenant, where) if tenant else None
