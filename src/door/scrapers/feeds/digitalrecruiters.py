#!/usr/bin/env python3
"""Scraper for employers on Cegid Digitalrecruiters, a French applicant-tracking system (issue #561).

Kind of site: an ATS (Paris, 2015, Cegid since 2022) whose customers, mostly French multi-site employers
(Monoprix, Franprix, Afflelou, ...), publish a career site, ``recrutement.<company>.fr`` or the like, on their
own domain. Every one is the same Nuxt app (``dr-cs-frontend``) that reads ``api.digitalrecruiters.com``. The
platform's wildcard host ``<x>.digitalrecruiters.com`` answers 404 for every name tried, so a tenant is its
own host.

Configured by ``digitalrecruiters_sites`` (filled from ``profile/companies.json``): the career site's host
(``recrutement.monoprix.fr``) or any link on it. Endpoints used, logged out, no key or cookie:
  GET https://<host>/sitemap.xml
      → every open ad as ``/fr/annonce/<id>-<slug>`` with its ``lastmod`` (a ``sitemapindex`` is followed too).
        The slug is the title, the place and the postal code, so ads on topic can be read first.
  GET https://<host>/fr/annonce/<id>-<slug>
      → the server-rendered ad, with its schema.org ``JobPosting`` JSON-LD (title, text, date posted, place,
        ``hiringOrganization``); read only for ads not in ``known_ids``.
The frontend's own list API (``api.digitalrecruiters.com/careers/v1/careers-site/job-ads``, a POST) answered 404
to a plain request and is not used. A tenant asks ``Crawl-delay: 10`` in its robots.txt, which `PoliteSession`
always honours, so a run reads at most ``_MAX_PAGES`` ads of a site, those on topic and the newest first; the
rest wait for the next run (an ad read once is in ``known_ids``).

Finding a tenant: ``detect_html`` recognises the platform on the page itself (the Nuxt payload names
``api.digitalrecruiters.com/careers`` and the tenant's ``domain_name``), so ``follow`` finds it on an employer's
career page, whatever domain it is on. ``detect_url`` takes only a ``<x>.digitalrecruiters.com`` link. There is
no JSON endpoint to confirm an entry with, so ``feed_url`` is None and ``alive_url`` is the sitemap.

Terms: Digitalrecruiters publishes no terms for a tenant's visitors. Cegid's legal notice
(https://www.cegid.com/fr/mentions-legales/) covers cegid.com and its brands, and its CGU/CGV are contracts with
customers. The two tenant pages that state anything (Monoprix's ``/fr/legal``, a candidate data-protection
charter) say nothing about reading the ads. Nothing bans scraping, bots or text-and-data mining. robots.txt of
Monoprix, Franprix and Afflelou: ``User-agent: *``, ``Allow: /``, ``Crawl-delay: 10``. Checked 2026-11-01.
"""

import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
from xml.etree import ElementTree

import requests

from door.scrapers.sdk import (
    Detection, JobPosting, NOT_ACCOUNTS, PROBE_TIMEOUT_S, PoliteSession, ProbeResult, followed_name, host_of,
    keep_local, make_job_id, on_topic, parse_iso_date, parts, record_error, record_pushback, report, run_probe,
    scrape_feeds, strip_html, tenant_platform_id, topic_terms, workers,
)

# The platform's own domain: a host on it is a customer's, never the employer's name.
PLATFORM_DOMAINS = ("digitalrecruiters.com",)

_SITE = "digitalrecruiters"
_KEY = "digitalrecruiters_sites"
_SUFFIX = ".digitalrecruiters.com"
_MAX_PAGES = 100        # ad pages read per site per run (the site asks a 10 s Crawl-delay)
_MAX_SITEMAPS = 5       # sitemap files read per site per run
_HEADERS = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
# Hosts of the platform's own that are no employer's career site.
_NOT_TENANTS = NOT_ACCOUNTS | {"app", "matomo", "status", "help", "docs", "cdn", "mail", "support"}
_AD_PATH = re.compile(r"/annonce/(\d+)(?:-([^/?#]*))?", re.IGNORECASE)
_LD_JSON = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.IGNORECASE | re.DOTALL)
_NUXT_API = re.compile(r"api\.digitalrecruiters\.com(?:/|\\u002F)careers", re.IGNORECASE)
_NUXT_DOMAIN = re.compile(r"""domain_name\s*:\s*["']([^"']+)["']""")


# --- tenants ---

def _host(entry: str) -> str:
    """The career-site host of a ``digitalrecruiters_sites`` entry: a host or any link on it. Pure."""
    entry = entry.strip()
    return parts(entry if "://" in entry else f"https://{entry}")[0]


def _base(entry: str) -> str:
    return f"https://{_host(entry)}"


# --- the sitemap ---

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_sitemap(xml_text: str) -> tuple[list[str], list[dict]]:
    """``(child sitemaps, ads)`` of a sitemap; each ad ``{id, url, title, lastmod}`` (the title is the slug's words,
    the ad's number the id). Pages that are no ad (``/annonce/<n>``) are skipped, an ad listed twice counts once.
    Raises ``ValueError`` for text that is no sitemap (an HTML error page, a block page). Pure."""
    try:
        root = ElementTree.fromstring((xml_text or "").strip().encode("utf-8"))
    except ElementTree.ParseError as exc:
        raise ValueError(f"not a sitemap: {exc}") from exc
    kind = _local(root.tag)
    if kind not in ("urlset", "sitemapindex"):
        raise ValueError(f"not a sitemap: <{kind}>")
    children, ads, seen = [], [], set()
    for node in root:
        loc = lastmod = ""
        for child in node:
            name = _local(child.tag)
            if name == "loc":
                loc = (child.text or "").strip()
            elif name == "lastmod":
                lastmod = (child.text or "").strip()
        if not loc:
            continue
        if kind == "sitemapindex":
            children.append(loc)
            continue
        match = _AD_PATH.search(urlparse(loc).path)
        if match is None or match.group(1) in seen:
            continue
        seen.add(match.group(1))
        ads.append({"id": match.group(1), "url": loc, "title": (match.group(2) or "").replace("-", " ").strip(),
                    "lastmod": lastmod})
    return children, ads


def _rank(items: list[dict], config: dict) -> list[dict]:
    """*items* with the ads whose slug is on topic for the profile first, the newest ``lastmod`` first within
    each of the two groups. Pure."""
    terms = topic_terms(config)
    newest = sorted(items, key=lambda i: i.get("lastmod") or "", reverse=True)
    if not terms:
        return newest
    return ([i for i in newest if on_topic(i["title"], terms)]
            + [i for i in newest if not on_topic(i["title"], terms)])


# --- one ad page ---

def _ld_job(page: str) -> dict:
    """The schema.org JobPosting object of an ad page, ``{}`` when it has none."""
    for raw in _LD_JSON.findall(page or ""):
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
        address = (place or {}).get("address") if isinstance(place, dict) else None
        name = (address.get("addressLocality") or "").strip() if isinstance(address, dict) else ""
        if name and name not in names:
            names.append(name)
    return "; ".join(names)


def parse_ad(page: str) -> dict | None:
    """What an ad page holds: ``title``, ``company``, ``posted_at`` (ISO text), ``location`` and the plain-text
    ``description``. None for a page without the JSON-LD JobPosting. Pure."""
    job = _ld_job(page)
    if not job:
        return None
    hiring = job.get("hiringOrganization")
    return {
        "title": (job.get("title") or "").strip(),
        "company": (hiring.get("name") or "").strip() if isinstance(hiring, dict) else "",
        "posted_at": job.get("datePosted") or "",
        "location": _ld_location(job),
        "description": strip_html(job.get("description") or ""),
    }


# --- mapping ---

def _to_posting(item: dict, ad: dict | None, entry: str, name: str, scraped_at: datetime) -> dict:
    """One sitemap item (and its ad page, when read) as a JobPosting dict; the followed *name* wins."""
    ad = ad or {}
    platform_id = tenant_platform_id(_base(entry), item["id"])
    posting = JobPosting(
        id=make_job_id(_SITE, platform_id),
        title=ad.get("title") or item["title"],
        company=name or ad.get("company") or _host(entry),
        location=ad.get("location") or "",
        url=item["url"],
        description=ad.get("description") or "",
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=parse_iso_date(ad.get("posted_at")),
        apply_type="external",
        apply_url=item["url"],
    )
    return posting.model_dump(mode="json")


# --- reading a site ---

def _status(exc: Exception) -> int | None:
    return getattr(getattr(exc, "response", None), "status_code", None)


def _site_ads(session: PoliteSession, entry: str) -> list[dict]:
    """Every ad the site's sitemap lists. Raises when the sitemap cannot be read (a 403/429 is recorded as
    pushback first) or is none."""
    base = _base(entry)
    queue, seen, ads, ids = [f"{base}/sitemap.xml"], set(), [], set()
    while queue and len(seen) < _MAX_SITEMAPS:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            text = session.get(url, headers=_HEADERS).text
        except requests.HTTPError as exc:
            if _status(exc) in (403, 429):
                record_pushback(_SITE)
            raise
        children, found = parse_sitemap(text)
        queue += [c for c in children if _host(c) == _host(entry)]
        for ad in found:
            if ad["id"] not in ids:
                ids.add(ad["id"])
                ads.append(ad)
    return ads


def _site_postings(session: PoliteSession, entry: str, scraped_at: datetime, known_ids: frozenset[str],
                   name: str, config: dict) -> list[dict]:
    """One site's new postings: the sitemap lists the ads, each unknown one's page gives the text. An ad that fails
    is recorded and left out (the next run reads it again), a closed one (404/410) is just skipped, and a refusal
    ends the site with what was read."""
    ads = _site_ads(session, entry)
    base = _base(entry)
    fresh = [a for a in _rank(ads, config) if tenant_platform_id(base, a["id"]) not in known_ids]
    cut = max(len(fresh) - _MAX_PAGES, 0)
    report(f"{_host(entry)}: {len(ads)} ads, {len(fresh)} new, {cut} left for the next run by the {_MAX_PAGES}-page cap")
    fresh = fresh[:_MAX_PAGES]
    postings = []
    for n, item in enumerate(fresh, 1):
        report("detail", n, len(fresh))
        try:
            ad = parse_ad(session.get(item["url"], headers=_HEADERS).text)
            if ad is None:
                raise ValueError("no JobPosting on the ad page")
        except requests.HTTPError as exc:
            status = _status(exc)
            if status in (404, 410):
                report(f"ad {item['id']} of {_host(entry)!r} is gone")
                continue
            message = f"error fetching ad {item['id']} of {_host(entry)!r}: {exc}"
            report(message)
            record_error(_SITE, message)
            if status in (403, 429):
                record_pushback(_SITE)
                break
            continue
        except Exception as exc:  # noqa: BLE001 - one ad never stops the site
            message = f"error fetching ad {item['id']} of {_host(entry)!r}: {exc}"
            report(message)
            record_error(_SITE, message)
            continue
        postings.append(_to_posting(item, ad, entry, name, scraped_at))
    return postings


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Return JobPosting dicts from the followed employers' Digitalrecruiters career sites (``digitalrecruiters_sites``)."""
    entries, hosts = [], set()
    for entry in config.get(_KEY) or []:
        if entry.strip() and _host(entry) not in hosts:
            hosts.add(_host(entry))
            entries.append(entry.strip())

    def fetch(session, entry, scraped_at):
        return _site_postings(session, entry, scraped_at, known_ids, followed_name(config, _KEY, entry), config)

    postings = scrape_feeds(_SITE, entries, fetch, group=lambda e: host_of(_base(e)), max_workers=workers(config),
                            headers=_HEADERS)
    return keep_local(postings, config, _SITE)


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the first site's sitemap (one request). ``None`` when none is set."""
    entries = [e for e in config.get(_KEY) or [] if e.strip()]
    if not entries:
        return None
    entry = entries[0]
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

    def fetch() -> str:
        return session.get(f"{_base(entry)}/sitemap.xml", headers=_HEADERS).text

    def parse(text: str):
        try:
            _children, ads = parse_sitemap(text)
        except ValueError as exc:
            return [], False, str(exc)
        now = datetime.now(timezone.utc)
        return [_to_posting(ad, None, entry, "", now) for ad in ads], True, ""

    return run_probe(fetch, parse, "xml")


# --- feed detection (issue #282) ---

def detect_url(url: str) -> Detection | None:
    """A link on the platform's wildcard host (``<x>.digitalrecruiters.com``) and the career site it names."""
    host, _path, _query = parts(url.strip())
    name = host[: -len(_SUFFIX)] if host.endswith(_SUFFIX) else ""
    if name and "." not in name and name not in _NOT_TENANTS:
        return Detection(_SITE, host, f"Digitalrecruiters career site {host}")
    return None


def detect_html(html: str, url: str) -> Detection | None:
    """A career site on the employer's own domain: its page carries the frontend's config, which names the
    platform's careers API and the site's ``domain_name``."""
    if not _NUXT_API.search(html or ""):
        return None
    match = _NUXT_DOMAIN.search(html)
    host = match.group(1).strip().lower() if match else parts(url.strip())[0]
    return Detection(_SITE, host, f"{url} is a Digitalrecruiters career site ({host})") if host else None


def feed_url(entry: str) -> str | None:
    """None: the sitemap is XML, not the JSON list the confirmation reads; `alive_url` drops a site that is gone."""
    return None


def alive_url(entry: str) -> str:
    """The first read of a site's feed: the sitemap, which a site that is gone answers with a 4xx."""
    return f"{_base(entry)}/sitemap.xml"


def name_probes(slug: str) -> list:
    """None to try: a tenant is a career-site host, not a company name."""
    return []
