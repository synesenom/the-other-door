#!/usr/bin/env python3
"""Scraper for Recman career sites (issue #529): a Nordic recruitment system used by staffing agencies and employers.

Kind: a per-company feed (an HTML sitemap plus one JSON-LD ad page per job), no login, no key.
Every Recman customer has a public career site, on ``<tenant>.recman.page`` (older ones ``<tenant>.recman.io``)
or on the employer's own host (``stillinger.signo.no``, a CNAME for ``signo.recman.page``):

  GET https://<host>/sitemap.xml
      → every open job as ``<loc>https://<host>/job/<id></loc>`` (with the page's other, fixed links)
  GET https://<host>/job/<id>
      → HTML whose ``<script type="application/ld+json">`` is a schema.org ``JobPosting``: title,
        description (HTML), ``datePosted``, ``hiringOrganization`` (the agency, for a staffing customer) and
        ``jobLocation`` (often blank)

The career page itself (``/jobs``) is drawn by script from a private API, so the sitemap is the list. The API
(developers.recman.io) needs a key created in a customer's own system settings, so it is not used. A job that is
in ``known_ids`` is not fetched. The ad is only read when it parses; one that fails is recorded and skipped.

Configured by ``recman_companies`` in the employer list: a tenant slug (``pn``, read as
``pn.recman.page``) or a career host (``yourstaff.recman.io``, ``stillinger.signo.no``). An apply link from a
job board (``apply.recman.page/job_post.php?id=…&sub_id=…``) names no tenant; `resolve` follows its redirect
to the career host the ad lives on.

Terms: https://pn.recman.page/user-agreement — the candidate agreement of a career site; it says nothing about
reading the public job pages (the vendor's own site, recman.io, offers no public terms page). robots.txt of a
career site disallows only ``/profile/``, ``/employee/``, ``/sys/`` and ``/drive/`` and names the sitemap.
Checked 2026-10-31.
"""

import json
import re
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from door.scrapers.sdk import (
    NOT_ACCOUNTS, Detection, JobPosting, PROBE_TIMEOUT_S, PoliteSession, ProbeResult, RobotsBlocked, followed_name,
    host_of, keep_local, make_job_id, parse_iso_date, parts, record_entry_error, record_error, record_pushback, report,
    run_probe, scrape_feeds, strip_html, unfollowable, workers,
)

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("recman.page", "recman.io")

_SITE = "recman"
_KEY = "recman_companies"
_HEADERS = {"Accept": "text/html,application/xml"}
_NOT_TENANTS = NOT_ACCOUNTS | {"apply", "help", "developers", "cdn", "cp-analytics", "support", "status", "mail"}
_JOB_LOC = re.compile(r"<loc>\s*(https?://[^<\s]+/job/(\d+))[^<]*</loc>")
_PUSHBACK = (401, 403, 429)


# --- pure helpers ---

def _base(entry: str) -> str:
    """``https://<host>`` for a ``recman_companies`` entry: a tenant slug (``pn``) or a career host or link. Pure."""
    entry = entry.strip().lower()
    if "." not in entry and "/" not in entry:
        return f"https://{entry}.recman.page"
    return f"https://{urlparse(entry if '://' in entry else f'https://{entry}').netloc.split(':')[0]}"


def _is_sitemap(xml: str) -> bool:
    return "<urlset" in (xml or "")


def _job_links(xml: str) -> list[dict]:
    """``[{id, url}]`` for the job pages a sitemap lists, in its order. Pure."""
    seen: set[str] = set()
    out = []
    for url, jid in _JOB_LOC.findall(xml or ""):
        if jid not in seen:
            seen.add(jid)
            out.append({"id": jid, "url": url})
    return out


def _location_text(place) -> str:
    """A "; "-joined "City, CC" string from a schema.org ``jobLocation`` (a place or a list of them). Pure."""
    texts: list[str] = []
    for one in place if isinstance(place, list) else [place]:
        address = one.get("address") if isinstance(one, dict) else None
        if not isinstance(address, dict):
            continue
        city = str(address.get("addressLocality") or "").strip()
        country = str(address.get("addressCountry") or "").strip()
        text = ", ".join(p for p in (city, country) if p)
        if text and text not in texts:
            texts.append(text)
    return "; ".join(texts)


def _json_ld(html: str) -> list:
    """The JSON-LD objects of a page (``@graph`` and lists flattened); unreadable blocks are skipped."""
    found: list = []

    def add(node) -> None:
        if isinstance(node, list):
            for item in node:
                add(item)
        elif isinstance(node, dict):
            found.append(node)
            add(node.get("@graph"))

    for tag in BeautifulSoup(html or "", "html.parser").find_all("script", type="application/ld+json"):
        try:
            add(json.loads(tag.string or tag.get_text(), strict=False))
        except ValueError:
            continue
    return found


def _is_job_posting(node: dict) -> bool:
    kind = node.get("@type")
    return kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind)


def _parse_detail(html: str) -> dict | None:
    """``{title, description, location, posted_at, organization}`` from a job page; ``None`` when it has no ad. Pure."""
    for node in _json_ld(html):
        title = re.sub(r"\s+", " ", str(node.get("title") or "").replace("\xa0", " ")).strip()
        if _is_job_posting(node) and title:
            org = node.get("hiringOrganization")
            return {
                "title": title,
                "description": strip_html(str(node.get("description") or "")),
                "location": _location_text(node.get("jobLocation")),
                "posted_at": node.get("datePosted") or None,
                "organization": str(org.get("name") or "").strip() if isinstance(org, dict) else "",
            }
    return None


def _to_posting(job: dict, ad: dict, company: str, scraped_at: datetime) -> dict:
    posting = JobPosting(
        id=make_job_id(_SITE, job["id"]),
        title=ad["title"],
        company=company,
        location=ad["location"],
        url=job["url"],
        description=ad["description"],
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=job["id"],
        posted_at=parse_iso_date(ad["posted_at"]),
        apply_type="external",
        apply_url=job["url"],
    )
    return posting.model_dump(mode="json")


def _status(exc: Exception) -> int | None:
    return getattr(getattr(exc, "response", None), "status_code", None)


# --- network ---

def _board_postings(session: PoliteSession, entry: str, scraped_at: datetime, known_ids: frozenset[str],
                    name: str) -> list[dict]:
    """One career site's postings. Raises when its sitemap cannot be read (or is not one: a tenant that is gone
    is served Recman's own "not found" page); a refusal is recorded as pushback and ends the board."""
    base = _base(entry)
    try:
        xml = session.get(f"{base}/sitemap.xml").text
    except (requests.RequestException, RobotsBlocked) as exc:
        if _status(exc) in _PUSHBACK:
            record_pushback(_SITE)
        raise
    if not _is_sitemap(xml):
        raise ValueError(f"{base}/sitemap.xml is not a sitemap (is the career site gone?)")
    jobs = [j for j in _job_links(xml) if j["id"] not in known_ids]
    out: list[dict] = []
    for n, job in enumerate(jobs, 1):
        report("detail", n, len(jobs))
        try:
            ad = _parse_detail(session.get(job["url"]).text)
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
        out.append(_to_posting(job, ad, name or ad["organization"] or entry, scraped_at))
    return out


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Every open job of each configured Recman career site."""
    entries = [e for e in config.get(_KEY) or [] if e.strip()]

    def fetch(session, entry, scraped_at):
        return _board_postings(session, entry, scraped_at, known_ids, followed_name(config, _KEY, entry, ""))

    return keep_local(scrape_feeds(_SITE, entries, fetch, group=lambda e: host_of(_base(e)),
                                   max_workers=workers(config), headers=_HEADERS), config, _SITE)


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the first career site's sitemap. ``None`` when none is configured.
    The sitemap carries no titles, so a posting here is its link alone (the count is what the check reads)."""
    entries = [e for e in config.get(_KEY) or [] if e.strip()]
    if not entries:
        return None
    entry = entries[0]
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

    def fetch() -> str:
        return session.get(f"{_base(entry)}/sitemap.xml").text

    def parse(text: str):
        if not _is_sitemap(text):
            return [], False, "not a sitemap: the career site is gone or has changed"
        now = datetime.now().astimezone()
        ad = {"title": "(not read)", "description": "", "location": "", "posted_at": None, "organization": ""}
        return [_to_posting(j, ad, entry, now) for j in _job_links(text)], True, ""

    return run_probe(fetch, parse, "xml")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

FEED_KEY = None  # (no JSON feed to confirm an entry with: `feed_url` is None)


def _entry_for_host(host: str) -> str | None:
    """The entry a career host is followed under: the slug on ``recman.page``, else the host itself (a
    ``recman.io`` tenant or an employer's own domain). ``None`` for the platform's shared hosts."""
    host = host.lower()
    if host.endswith(".recman.page"):
        label = host[: -len(".recman.page")]
        return None if "." in label or label in _NOT_TENANTS else label
    if host.endswith(".recman.io"):
        label = host[: -len(".recman.io")]
        return None if "." in label or label in _NOT_TENANTS else host
    return host or None


def detect_url(url: str) -> Detection | None:
    """A link on a Recman career site (``<tenant>.recman.page``, ``<tenant>.recman.io``) and the tenant it names;
    a job-board apply link on the shared ``apply`` host names none (`resolve` follows it to the career host)."""
    host, path, _query = parts(url.strip())
    for domain in PLATFORM_DOMAINS:
        if not host.endswith("." + domain):
            continue
        label = host[: -len(domain) - 1]
        if label == "apply":
            if path and path[0].lower() == "job_post.php":
                return unfollowable(_SITE, host, "a Recman apply link names no career site until it is followed", "cant_yet")
            return None
        entry = _entry_for_host(host)
        return Detection(_SITE, entry, f"Recman career site {host}") if entry else None
    return None


def feed_url(entry: str) -> str | None:
    """None: a link to the career site names the tenant, no feed check is needed."""
    return None


def name_probes(slug: str) -> list:
    """None: a company's name does not tell its tenant."""
    return []


def detect_cname(host: str, target: str, where: str) -> Detection | None:
    """A career host that is a CNAME for a tenant of Recman's."""
    entry = _entry_for_host(target) if target.endswith((".recman.page", ".recman.io")) else None
    return Detection(_SITE, entry, where) if entry else None


def detect_html(html: str, url: str) -> Detection | None:
    """A career site on the employer's own host that loads Recman's analytics script."""
    host = urlparse(url if "://" in url else f"https://{url}").netloc.lower().split(":")[0]
    if "cp-analytics.recman.io" in (html or "") and host and not host.endswith(".recman.io"):
        return Detection(_SITE, _entry_for_host(host), f"{url} is a Recman career site")
    return None


def resolve(session: PoliteSession, det: Detection, url: str) -> Detection:
    """*det* for an apply link (``apply.recman.page/job_post.php?id=…&sub_id=…``) followed to the career host it
    redirects to: that host's detection; *det* itself when the link is unreadable, lands on a shared host or
    already names a tenant."""
    if det.entry is not None:
        return det
    try:
        landed = session.get(url if "://" in url else f"https://{url}", headers=_HEADERS).url
    except (requests.RequestException, RobotsBlocked):
        return det
    host = urlparse(landed).netloc.lower().split(":")[0]
    entry = _entry_for_host(host)
    if entry is None or host.startswith("apply.") or urlparse(landed).path.rstrip("/") == "/unknown":
        return det
    return Detection(_SITE, entry, f"Recman apply link, redirected to the career site {host}")
