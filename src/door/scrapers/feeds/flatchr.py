#!/usr/bin/env python3
"""Scraper for employers on Flatchr, a French applicant-tracking system (issue #557).

Kind of site: an ATS whose customers publish their ads on a Flatchr career site,
``careers.flatchr.io/fr/company/<slug>`` (also served as ``<slug>.flatchr.io``). The page is drawn by script
(Next.js) from a public JSON list that needs no key and no login:

  GET https://careers.flatchr.io/company/<slug>.json
      → ``{"items": [{"vacancy": {vacancy_id, slug, title, description, mission, profile (HTML), contract_type,
        remote, language (``fr_FR``), created_at, start_date, salary, address {locality, postal_code, country},
        company {name}}, ...}]}`` for every open ad of the company, in one answer: ``page``, ``limit`` and
        ``per_page`` are echoed back and change nothing, so there is no paging. An unknown slug is a 404.
  The ad's page, ``https://careers.flatchr.io/fr/company/<slug>/vacancy/<vacancy slug>``, is the link; the text
  is already in the list, so no ad page is fetched.

Configured by ``flatchr_companies`` (filled from ``profile/companies.json``): the company slug (``flatchr``), its
``<slug>.flatchr.io`` host or a career-site link. The payload carries no ad language the pipeline uses; the
language pass decides after scraping (the ``language`` field is not read).

Terms: https://www.flatchr.io/cgu — the general terms of the service: an intellectual-property clause, nothing about
reading public job lists, bots or text-and-data mining. robots.txt of ``careers.flatchr.io`` bars a few named bots
(FacebookBot, bingbot, MJ12bot, SemrushBot, ...); ``*`` is allowed. Checked 2026-11-01.
"""

import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from door.scrapers.sdk import (
    NOT_ACCOUNTS, Detection, JobPosting, PROBE_TIMEOUT_S, PoliteSession, Probe, ProbeResult, RobotsBlocked,
    followed_name, keep_local, make_job_id, parse_iso_date, parts, record_pushback, run_probe, scrape_feeds,
    strip_html,
)

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("flatchr.io",)

_SITE = "flatchr"
_KEY = "flatchr_companies"
_HEADERS = {"Accept": "application/json"}
_CAREERS = "careers.flatchr.io"
_NOT_COMPANIES = NOT_ACCOUNTS | {"candidat", "candidate", "api", "help", "support", "status", "blog", "fr", "en"}
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_PUSHBACK = (401, 403, 429)


# --- pure helpers ---

def _slug(entry: str) -> str | None:
    """The company slug of a ``flatchr_companies`` entry: the slug, ``<slug>.flatchr.io`` or a career-site link."""
    entry = (entry or "").strip().lower()
    if not entry:
        return None
    if "." not in entry and "/" not in entry:
        return entry if _SLUG.match(entry) else None
    host, path, _query = parts(entry)
    if host == _CAREERS:
        for i, segment in enumerate(path[:-1]):
            if segment == "company":
                name = path[i + 1].removesuffix(".json")
                return name if _SLUG.match(name) else None
        return None
    if host.endswith(".flatchr.io"):
        label = host[: -len(".flatchr.io")]
        return label if "." not in label and label not in _NOT_COMPANIES and _SLUG.match(label) else None
    return None


def _location_text(vacancy: dict) -> str:
    """"City, Country" from the vacancy's address (either part alone when the other is missing)."""
    address = vacancy.get("address")
    if not isinstance(address, dict):
        return ""
    return ", ".join(p for p in (str(address.get("locality") or "").strip(), str(address.get("country") or "").strip()) if p)


def _description(vacancy: dict) -> str:
    """The company pitch, the mission and the profile of an ad as plain text."""
    return "\n\n".join(t for t in (strip_html(vacancy.get(f) or "") for f in ("description", "mission", "profile")) if t)


def _items(data) -> list[dict] | None:
    """The ``items`` that hold a vacancy with an id and a title; ``None`` when *data* has no ``items`` list."""
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return None
    return [i for i in items if isinstance(i, dict) and isinstance(i.get("vacancy"), dict)
            and i["vacancy"].get("vacancy_id") and str(i["vacancy"].get("title") or "").strip()]


def _to_posting(item: dict, slug: str, name: str, scraped_at: datetime) -> dict:
    vacancy = item["vacancy"]
    company = vacancy.get("company")
    url = f"https://{_CAREERS}/fr/company/{slug}/vacancy/{vacancy.get('slug') or vacancy['vacancy_id']}"
    posting = JobPosting(
        id=make_job_id(_SITE, str(vacancy["vacancy_id"])),
        title=str(vacancy["title"]).strip(),
        company=name or (str(company.get("name") or "").strip() if isinstance(company, dict) else "") or slug,
        location=_location_text(vacancy),
        url=url,
        description=_description(vacancy),
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=str(vacancy["vacancy_id"]),
        posted_at=parse_iso_date(vacancy.get("created_at")),
        apply_type="external",
        apply_url=url,
    )
    return posting.model_dump(mode="json")


def _status(exc: Exception) -> int | None:
    return getattr(getattr(exc, "response", None), "status_code", None)


# --- network ---

def _company_postings(session: PoliteSession, entry: str, scraped_at: datetime, name: str) -> list[dict]:
    """The open ads of one company. Raises on a bad entry, an HTTP error (a refusal is recorded as pushback
    first) or an answer without an ``items`` list."""
    slug = _slug(entry)
    if slug is None:
        raise ValueError("not a Flatchr company")
    try:
        data = session.get(feed_url(slug), headers=_HEADERS).json()
    except (requests.RequestException, RobotsBlocked) as exc:
        if _status(exc) in _PUSHBACK:
            record_pushback(_SITE)
        raise
    items = _items(data)
    if items is None:
        raise ValueError(f"no `items` list in the Flatchr feed of {slug!r}")
    return [_to_posting(i, slug, name, scraped_at) for i in items]


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Every open ad of each followed Flatchr career site (``flatchr_companies``)."""
    entries = [e for e in config.get(_KEY) or [] if e.strip()]
    seen: set[str] = set()
    unique = [e for e in entries if (_slug(e) or e) not in seen and not seen.add(_slug(e) or e)]

    def fetch(session, entry, scraped_at):
        return _company_postings(session, entry, scraped_at, followed_name(config, _KEY, entry))

    return keep_local(scrape_feeds(_SITE, unique, fetch, headers=_HEADERS), config, _SITE)


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the first company's list. ``None`` when none is set."""
    entries = [e for e in config.get(_KEY) or [] if e.strip()]
    if not entries:
        return None
    slug = _slug(entries[0])
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

    def fetch() -> str:
        return session.get(feed_url(slug or entries[0]), headers=_HEADERS).text

    def parse(text: str):
        items = _items(json.loads(text))
        if items is None:
            return [], False, "no `items` list in the Flatchr company feed"
        now = datetime.now(timezone.utc)
        return [_to_posting(i, slug or "", "", now) for i in items], True, ""

    return run_probe(fetch, parse, "json")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

FEED_KEY = "items"


def detect_url(url: str) -> Detection | None:
    """A Flatchr career-site link (``careers.flatchr.io/<lang>/company/<slug>/...`` or ``<slug>.flatchr.io``)."""
    host, _path, _query = parts(url.strip())
    if host != _CAREERS and not host.endswith(".flatchr.io"):
        return None
    slug = _slug(url)
    return Detection(_SITE, slug, f"Flatchr career site {slug}") if slug else None


def feed_url(entry: str) -> str | None:
    """The JSON list of *entry*'s open ads (a slug, a ``<slug>.flatchr.io`` host or a career-site link)."""
    slug = _slug(entry)
    return f"https://{_CAREERS}/company/{slug}.json" if slug else None


def name_probes(slug: str) -> list[Probe]:
    """The public list to try for a company name's *slug*."""
    url = feed_url(slug)
    return [Probe(url, FEED_KEY, f"Flatchr career site {slug}")] if url else []


def detect_cname(host: str, target: str, where: str) -> Detection | None:
    """A career host that is a CNAME for a ``<slug>.flatchr.io`` site."""
    slug = _slug(target.rstrip(".")) if target.rstrip(".").lower().endswith(".flatchr.io") else None
    return Detection(_SITE, slug, where) if slug else None


_HTML_LINK = re.compile(r"careers\.flatchr\.io/(?:[a-z]{2}/)?company/([a-z0-9][a-z0-9_-]*)", re.I)


def detect_html(html: str, url: str) -> Detection | None:
    """A career page that links to, or embeds, a Flatchr career site."""
    match = _HTML_LINK.search(html or "")
    return Detection(_SITE, match.group(1).lower(), f"{url} links to the Flatchr career site {match.group(1).lower()}") if match else None
