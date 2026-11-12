#!/usr/bin/env python3
"""Scraper for Beetween career sites (issue #560): the French recruitment software behind ~180 employer career sites.

Kind: a per-company feed (WordPress' REST job list plus one JSON-LD ad page per job), no login, no key.
Every Beetween customer has a public WordPress career site, on ``<tenant>.nous-recrutons.fr`` or on the
employer's own host (``recrutement.clermontmetropole.eu``, ``recrutement.beetween.fr``); jobs are a WordPress
post type named ``job``:

  GET https://<host>/wp-json/wp/v2/job?per_page=50&page=<n>&_fields=id,date,link,title
      → JSON list of the open jobs: ``id`` (the post number), ``date`` (local time), ``link``
        (``/poste/<key>-<slug>/``) and ``title.rendered`` (HTML-escaped). ``X-WP-TotalPages`` says how many pages
        there are. ``content`` is empty: the text lives on the ad page.
  GET https://<host>/poste/<key>-<slug>/
      → HTML whose ``<script type="application/ld+json">`` is a schema.org ``JobPosting``: ``description`` and
        ``qualifications`` (both HTML, escaped), ``datePosted``, ``jobLocation`` (locality, and a region that is
        often just "France") and ``hiringOrganization`` (a brand or subsidiary of the employer).

An ad in ``known_ids`` is not fetched. The ad is only kept when it parses; one that fails is recorded and
skipped, so the next run reads it again.

Configured by ``beetween_companies`` in the employer list: a tenant slug (``giboire``, read as
``giboire.nous-recrutons.fr``) or the employer's own career host. Post numbers repeat across sites, so the host
is folded into the platform id.

Terms: the vendor's terms (https://beetween.com/terms-conditions/) forbid extracting the databases of *its own*
website (beetween.com). The career sites are the employers' own: their legal pages (mentions légales / RGPD:
https://recrutement.beetween.fr/rgpd/, https://giboire.nous-recrutons.fr/rgpd/,
https://cyu.nous-recrutons.fr/rgpd/, https://freelance.nous-recrutons.fr/mentions-legales/,
https://recrutement.clermontmetropole.eu/rgpd/) hold the same notice: the content belongs to the employer and
"toute utilisation, reproduction ou représentation ... n'est pas autorisée sans le consentement exprès", plus the
data-protection policy for applicants. None mentions robots, scraping, extraction or text-and-data mining, and
the job list is the public REST route the sites' own pages are drawn from. robots.txt disallows only
``/wp-admin/``. Checked 2026-11-01.
"""

import html as _html
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from door.scrapers.sdk import (
    NOT_ACCOUNTS, Detection, JobPosting, PROBE_TIMEOUT_S, PoliteSession, ProbeResult, RobotsBlocked, followed_name,
    host_of, keep_local, make_job_id, parse_iso_date, parts, record_entry_error, record_error, record_pushback, report,
    run_probe, scrape_feeds, strip_html, tenant_platform_id, workers,
)

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("nous-recrutons.fr",)

_SITE = "beetween"
_KEY = "beetween_companies"
_SUFFIX = ".nous-recrutons.fr"
_HEADERS = {"Accept": "application/json,text/html"}
_NOT_TENANTS = NOT_ACCOUNTS | {"mail", "support", "status", "cdn"}
_PER_PAGE = 50
_MAX_PAGES = 20
_PUSHBACK = (401, 403, 429)
# A Beetween ad link: ten letters and digits, then the title's slug.
_AD_LINK = re.compile(r"/poste/[a-z0-9]{10}-[a-z0-9-]+", re.IGNORECASE)


# --- pure helpers ---

def _base(entry: str) -> str:
    """``https://<host>`` for a ``beetween_companies`` entry: a tenant slug (``giboire``) or a career host or link. Pure."""
    entry = entry.strip().lower()
    if "." not in entry and "/" not in entry:
        return f"https://{entry}{_SUFFIX}"
    return f"https://{urlparse(entry if '://' in entry else f'https://{entry}').netloc.split(':')[0]}"


def _list_url(base: str, page: int) -> str:
    return f"{base}/wp-json/wp/v2/job?per_page={_PER_PAGE}&page={page}&_fields=id,date,link,title"


def parse_list(text: str) -> list[dict]:
    """The jobs of one page of the WordPress job list: ``{id, title, url, posted_at}`` each, in order. Raises
    ``ValueError`` when the text is no list (an HTML page, a WordPress error object). Pure."""
    try:
        data = json.loads(text or "")
    except ValueError as exc:
        raise ValueError(f"not a WordPress job list: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("not a WordPress job list (the career site has no `job` posts route)")
    jobs = []
    for item in data:
        if not isinstance(item, dict) or not item.get("link"):
            continue
        title = item.get("title")
        jobs.append({
            "id": str(item.get("id") or ""),
            "title": _html.unescape((title.get("rendered") if isinstance(title, dict) else title) or "").strip(),
            "url": str(item["link"]).split("?")[0],
            "posted_at": item.get("date") or "",
        })
    return [j for j in jobs if j["id"]]


def _ld_job(page: str) -> dict:
    """The schema.org JobPosting object of an ad page, ``{}`` when it has none."""
    for tag in BeautifulSoup(page or "", "html.parser").find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text(), strict=False)
        except ValueError:
            continue
        for node in data if isinstance(data, list) else [data]:
            if isinstance(node, dict) and node.get("@type") == "JobPosting":
                return node
    return {}


def _location_text(place) -> str:
    """A "; "-joined "City, Region" string from a schema.org ``jobLocation`` (a place or a list of them). Pure."""
    texts: list[str] = []
    for one in place if isinstance(place, list) else [place]:
        address = one.get("address") if isinstance(one, dict) else None
        if not isinstance(address, dict):
            continue
        city = str(address.get("addressLocality") or "").strip()
        region = str(address.get("addressRegion") or "").strip()
        text = ", ".join(p for p in (city, region if region.lower() != city.lower() else "") if p)
        if text and text not in texts:
            texts.append(text)
    return "; ".join(texts)


def _text(markup) -> str:
    """Plain text of a JSON-LD field that holds escaped HTML (``&lt;p&gt;...``, and entities inside it)."""
    return strip_html(_html.unescape(str(markup or "")))


def parse_ad(page: str) -> dict | None:
    """``{title, description, location, posted_at, organization}`` from an ad page; ``None`` when it has no ad. Pure."""
    job = _ld_job(page)
    title = " ".join(_html.unescape(str(job.get("title") or "")).split())
    if not job or not title:
        return None
    org = job.get("hiringOrganization")
    return {
        "title": title,
        "description": "\n\n".join(t for t in (_text(job.get("description")), _text(job.get("qualifications"))) if t),
        "location": _location_text(job.get("jobLocation")),
        "posted_at": job.get("datePosted") or None,
        "organization": str(org.get("name") or "").strip() if isinstance(org, dict) else "",
    }


def _to_posting(job: dict, ad: dict | None, base: str, name: str, scraped_at: datetime) -> dict:
    """One listed job (and its ad page, when read) as a JobPosting dict; the followed *name* wins."""
    ad = ad or {}
    platform_id = tenant_platform_id(base, job["id"])  # post numbers repeat across sites
    posting = JobPosting(
        id=make_job_id(_SITE, platform_id),
        title=job["title"] or ad.get("title") or "",
        company=name or ad.get("organization") or host_of(base),
        location=ad.get("location") or "",
        url=job["url"],
        description=ad.get("description") or "",
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=parse_iso_date(ad.get("posted_at") or job.get("posted_at")),
        apply_type="external",
        apply_url=job["url"],
    )
    return posting.model_dump(mode="json")


def _status(exc: Exception) -> int | None:
    return getattr(getattr(exc, "response", None), "status_code", None)


# --- network ---

def _fetch_jobs(session: PoliteSession, base: str, entry: str) -> list[dict]:
    """Every listed job of a career site, page by page. Raises when a page cannot be read (a refusal is recorded as
    pushback first) or is no job list."""
    jobs: list[dict] = []
    total = 1
    page = 1
    while page <= min(total, _MAX_PAGES):
        try:
            response = session.get(_list_url(base, page), headers=_HEADERS)
        except (requests.RequestException, RobotsBlocked) as exc:
            if _status(exc) in _PUSHBACK:
                record_pushback(_SITE)
            raise
        found = parse_list(response.text)
        jobs.extend(found)
        header = response.headers.get("X-WP-TotalPages") if response.headers else None
        if header and header.isdigit():
            total = int(header)
        elif len(found) >= _PER_PAGE:
            total = page + 1
        report(f"{entry}: page {page}/{total}")
        page += 1
    return jobs


def _site_postings(session: PoliteSession, entry: str, scraped_at: datetime, known_ids: frozenset[str],
                   name: str) -> list[dict]:
    """One career site's new postings: the list gives the jobs, each unknown ad's page the text."""
    base = _base(entry)
    jobs = [j for j in _fetch_jobs(session, base, entry) if tenant_platform_id(base, j["id"]) not in known_ids]
    out: list[dict] = []
    for n, job in enumerate(jobs, 1):
        report("detail", n, len(jobs))
        try:
            ad = parse_ad(session.get(job["url"], headers=_HEADERS).text)
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
        out.append(_to_posting(job, ad, base, name, scraped_at))
    return out


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Every open job of each configured Beetween career site."""
    entries = [e for e in config.get(_KEY) or [] if e.strip()]

    def fetch(session, entry, scraped_at):
        return _site_postings(session, entry, scraped_at, known_ids, followed_name(config, _KEY, entry, ""))

    return keep_local(scrape_feeds(_SITE, entries, fetch, group=lambda e: host_of(_base(e)),
                                   max_workers=workers(config), headers=_HEADERS), config, _SITE)


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the first page of the first career site's job list (one request).
    ``None`` when none is configured. The list holds no text, so a posting here is its title and link."""
    entries = [e for e in config.get(_KEY) or [] if e.strip()]
    if not entries:
        return None
    base = _base(entries[0])
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

    def fetch() -> str:
        return session.get(_list_url(base, 1), headers=_HEADERS).text

    def parse(text: str):
        try:
            jobs = parse_list(text)
        except ValueError as exc:
            return [], False, str(exc)
        now = datetime.now(timezone.utc)
        return [_to_posting(j, None, base, "", now) for j in jobs], True, ""

    return run_probe(fetch, parse, "json")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

FEED_KEY = None  # (no feed check by name: `feed_url` is None)


def _entry_for_host(host: str) -> str | None:
    """The entry a career host is followed under: the slug on ``nous-recrutons.fr``, else the host itself (an
    employer's own domain). ``None`` for the platform's shared hosts."""
    host = host.lower().split(":")[0]
    if host.endswith(_SUFFIX):
        label = host[: -len(_SUFFIX)]
        return None if "." in label or label in _NOT_TENANTS else label
    return host or None


def detect_url(url: str) -> Detection | None:
    """A link on a Beetween career site (``<tenant>.nous-recrutons.fr``) and the tenant it names."""
    host, _path, _query = parts(url.strip())
    if not host.endswith(_SUFFIX):
        return None
    entry = _entry_for_host(host)
    return Detection(_SITE, entry, f"Beetween career site {host}") if entry else None


def feed_url(entry: str) -> str | None:
    """None: a link to the career site names the tenant, no feed check is needed."""
    return None


def name_probes(slug: str) -> list:
    """None: a company's name does not tell its tenant."""
    return []


def detect_cname(host: str, target: str, where: str) -> Detection | None:
    """A career host that is a CNAME for a tenant of Beetween's."""
    entry = _entry_for_host(target) if target.lower().rstrip(".").endswith(_SUFFIX) else None
    return Detection(_SITE, entry, where) if entry else None


def detect_html(html: str, url: str) -> Detection | None:
    """A WordPress career site on the employer's own host whose pages link Beetween-style ads
    (``/poste/<ten letters and digits>-<slug>/``)."""
    host = urlparse(url if "://" in url else f"https://{url}").netloc.lower().split(":")[0]
    if host and "/wp-content/" in (html or "") and _AD_LINK.search(html or ""):
        return Detection(_SITE, _entry_for_host(host), f"{url} is a Beetween career site")
    return None
