#!/usr/bin/env python3
"""Scraper for Recruitee's public careers-site API (issue #231).

Every Recruitee careers site answers, without a key, with all its published
offers in one response:

  GET https://<company>.recruitee.com/api/offers/
      → ``{"offers": [{id, title, company_name, careers_url, careers_apply_url,
      location, city, country, remote, description, requirements,
      published_at, ...}]}`` (no pagination)

Configured by ``recruitee_companies``: each company's subdomain slug, or its own
careers host when that points at Recruitee (``careers.trackman.com``).

Terms: https://recruitee.com/terms — nothing on scraping. robots.txt disallows a
single path, not the careers API.
"""

import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from door.scrapers.sdk import (
    JobPosting, PoliteSession, PROBE_TIMEOUT_S, ProbeResult, host_of, make_job_id, parse_iso_date, run_probe,
    scrape_feeds, strip_html, workers, followed_name,
)
from door.scrapers.sdk import keep_local
from door.scrapers.sdk import Detection, NOT_ACCOUNTS, Probe, parts

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("recruitee.com",)

_SITE = "recruitee"
_HEADERS = {"Accept": "application/json"}


def _careers_base(entry: str) -> str:
    """``https://<host>`` for a ``recruitee_companies`` entry: a slug or a careers host. Pure."""
    entry = entry.strip()
    if "." not in entry and "/" not in entry:
        return f"https://{entry.lower()}.recruitee.com"
    return f"https://{urlparse(entry if '://' in entry else f'https://{entry}').netloc.lower()}"


def _parse_date(raw) -> datetime | None:
    """Recruitee's ``2026-09-11 13:08:03 UTC`` (or an ISO 8601 date) as an aware datetime. Pure."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith(" UTC"):
        text = text[:-4].replace(" ", "T") + "+00:00"
    return parse_iso_date(text)


def _location_text(offer: dict) -> str:
    """The offer's location, prefixed ``Remote`` for a remote offer. Pure."""
    text = (offer.get("location") or "").strip() or ", ".join(
        p for p in ((offer.get("city") or "").strip(), (offer.get("country") or "").strip()) if p
    )
    if offer.get("remote"):
        return f"Remote, {text}" if text else "Remote"
    return text


def _to_posting(offer: dict, fallback_company: str, scraped_at: datetime, name: str = "") -> dict:
    platform_id = str(offer.get("id") or "")
    title = (offer.get("title") or "").strip()
    company = (name or offer.get("company_name") or fallback_company).strip()
    url = offer.get("careers_url") or ""
    description = "\n\n".join(t for t in (strip_html(offer.get("description") or ""),
                                          strip_html(offer.get("requirements") or "")) if t)
    posting = JobPosting(
        id=make_job_id(_SITE, platform_id),
        title=title,
        company=company,
        location=_location_text(offer),
        url=url,
        description=description,
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=_parse_date(offer.get("published_at") or offer.get("created_at")),
        apply_type="external",
        apply_url=offer.get("careers_apply_url") or url,
    )
    return posting.model_dump(mode="json")


def _published(offers) -> list[dict]:
    return [o for o in offers if isinstance(o, dict) and o.get("id") and o.get("status", "published") == "published"]


def _company_postings(session: PoliteSession, entry: str, scraped_at: datetime, name: str = "") -> list[dict]:
    """The published offers of one ``recruitee_companies`` entry, labelled with the followed *name*
    when given. Raises on HTTP errors."""
    offers = session.get(f"{_careers_base(entry)}/api/offers/", headers=_HEADERS).json().get("offers") or []
    return [_to_posting(offer, entry, scraped_at, name) for offer in _published(offers)]


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Every published offer of each configured Recruitee careers site."""
    entries = [e.strip() for e in config.get("recruitee_companies") or [] if e.strip()]
    # Companies on different hosts are fetched side by side.
    def fetch(session, entry, scraped_at):
        return _company_postings(session, entry, scraped_at, followed_name(config, "recruitee_companies", entry))

    return keep_local(scrape_feeds(_SITE, entries, fetch, group=lambda e: host_of(_careers_base(e)),
                                   max_workers=workers(config), headers=_HEADERS), config, _SITE)


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the first configured company. ``None`` when none is set."""
    entries = [e for e in config.get("recruitee_companies") or [] if e.strip()]
    if not entries:
        return None
    base = _careers_base(entries[0])
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

    def fetch() -> str:
        return session.get(f"{base}/api/offers/", headers=_HEADERS).text

    def parse(text: str):
        data = json.loads(text)
        offers = data.get("offers") if isinstance(data, dict) else None
        if not isinstance(offers, list):
            return [], False, "no `offers` list in the Recruitee careers API response"
        scraped_at = datetime.now(timezone.utc)
        return [_to_posting(o, entries[0].strip(), scraped_at) for o in _published(offers)], True, ""

    return run_probe(fetch, parse, "json")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

FEED_KEY = "offers"


def _host(entry: str) -> str:
    return entry if "." in entry else f"{entry}.recruitee.com"


def detect_url(url: str) -> Detection | None:
    """A Recruitee career site (``<account>.recruitee.com``) and the account it names."""
    host, _path, _query = parts(url.strip())
    sub = host.split(".")[0]
    if host.endswith(".recruitee.com") and host.count(".") == 2 and sub not in NOT_ACCOUNTS:
        return Detection("recruitee", sub, f"Recruitee career site {host}")
    return None


def feed_url(entry: str) -> str | None:
    """The feed that lists the jobs of *entry* (an account, or a career site on the employer's own host);
    a detection from page signatures is kept only when it lists jobs (under `FEED_KEY`)."""
    return "https://" + _host(entry) + "/api/offers/"


def name_probes(slug: str) -> list[Probe]:
    """The public feed to try for a company name's *slug*."""
    return [Probe(feed_url(slug), FEED_KEY, f"Recruitee site {slug}")]


_SITE_MARKERS = re.compile(r"recruiteecdn\.com|[a-z0-9-]+\.recruitee\.com", re.IGNORECASE)


def detect_cname(host: str, target: str, where: str) -> Detection | None:
    """A career host that is a CNAME for Recruitee's."""
    return Detection("recruitee", host, where) if target == "secure.recruitee.com" else None


def detect_html(html: str, url: str) -> Detection | None:
    """A career site on the employer's own host whose page loads Recruitee's assets or names its
    ``<slug>.recruitee.com``."""
    if _SITE_MARKERS.search(html):
        return Detection("recruitee", urlparse(url).netloc.lower(), f"{url} is a Recruitee careers site")
    return None
