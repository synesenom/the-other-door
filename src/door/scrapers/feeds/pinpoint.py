#!/usr/bin/env python3
"""Scraper for Pinpoint's public career-site feed.

Every Pinpoint career site answers, without a key, with all its published
postings in one response:

  GET https://<company>.pinpointhq.com/postings.json
      → ``{"data": [{id, title, url, path, location: {city, name, ...},
      workplace_type, employment_type, description, key_responsibilities,
      skills_knowledge_expertise, benefits, ...}]}`` (no pagination)

The payload names no company and carries no publish date, so the company is the
slug and ``posted_at`` stays empty. Configured by ``pinpoint_companies``: each
company's subdomain slug, or its own careers host when that points at Pinpoint.

Terms: https://www.pinpointhq.com/terms-of-use — nothing on scraping; the feed is
the one the career site itself loads. robots.txt disallows only its account, admin
and company-management paths.
"""

import json
from datetime import datetime, timezone
from urllib.parse import urlparse

from door.scrapers.sdk import (
    JobPosting, PoliteSession, PROBE_TIMEOUT_S, ProbeResult, make_job_id, tenant_platform_id, run_probe, scrape_feeds, strip_html,
    followed_name,
)
from door.scrapers.sdk import keep_local
from door.scrapers.sdk import Detection, NOT_ACCOUNTS, Probe, parts

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("pinpointhq.com",)

_SITE = "pinpoint"
_HEADERS = {"Accept": "application/json"}
_BODY_FIELDS = ("description", "key_responsibilities", "skills_knowledge_expertise", "benefits")


def _careers_base(entry: str) -> str:
    """``https://<host>`` for a ``pinpoint_companies`` entry: a slug or a careers host. Pure."""
    entry = entry.strip()
    if "." not in entry and "/" not in entry:
        return f"https://{entry.lower()}.pinpointhq.com"
    return f"https://{urlparse(entry if '://' in entry else f'https://{entry}').netloc.lower()}"


def _location_text(posting: dict) -> str:
    """The posting's place, prefixed ``Remote`` or ``Hybrid`` for that workplace type. Pure."""
    loc = posting.get("location") or {}
    text = (loc.get("name") or "").strip() or (loc.get("city") or "").strip()
    kind = (posting.get("workplace_type") or "").lower()
    prefix = {"remote": "Remote", "hybrid": "Hybrid"}.get(kind, "")
    if prefix and text and text.lower() != prefix.lower():
        return f"{prefix}, {text}"
    return prefix or text


def _company_name(slug: str) -> str:
    return slug.split(".")[0].replace("-", " ").strip().title()


def _to_posting(item: dict, company: str, base: str, scraped_at: datetime) -> dict:
    title = (item.get("title") or "").strip()
    url = item.get("url") or (f"{base}{item['path']}" if item.get("path") else "")
    platform_id = tenant_platform_id(url or base, str(item.get("id") or ""))  # ids repeat across tenants
    description = "\n\n".join(t for t in (strip_html(item.get(f) or "") for f in _BODY_FIELDS) if t)
    posting = JobPosting(
        id=make_job_id(_SITE, platform_id),
        title=title,
        company=company,
        location=_location_text(item),
        url=url,
        description=description,
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=platform_id,
        apply_type="external",
        apply_url=url,
    )
    return posting.model_dump(mode="json")


def _items(data) -> list[dict]:
    return [o for o in data if isinstance(o, dict) and o.get("id")]


def _company_postings(session: PoliteSession, entry: str, scraped_at: datetime, name: str = "") -> list[dict]:
    """The published postings of one ``pinpoint_companies`` entry, labelled with the followed *name*
    when given. Raises on HTTP errors."""
    base = _careers_base(entry)
    company = name or _company_name(entry if "." not in entry else urlparse(base).netloc)
    data = session.get(f"{base}/postings.json", headers=_HEADERS).json().get("data") or []
    return [_to_posting(item, company, base, scraped_at) for item in _items(data)]


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Every published posting of each configured Pinpoint career site."""
    entries = [e.strip() for e in config.get("pinpoint_companies") or [] if e.strip()]
    def fetch(session, entry, scraped_at):
        return _company_postings(session, entry, scraped_at, followed_name(config, "pinpoint_companies", entry))

    return keep_local(scrape_feeds(_SITE, entries, fetch, key=lambda p: (p["company"], p["platform_id"]),
                                   headers=_HEADERS), config, _SITE)


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the first configured company. ``None`` when none is set."""
    entries = [e for e in config.get("pinpoint_companies") or [] if e.strip()]
    if not entries:
        return None
    base = _careers_base(entries[0])
    company = _company_name(entries[0].strip() if "." not in entries[0] else urlparse(base).netloc)
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

    def fetch() -> str:
        return session.get(f"{base}/postings.json", headers=_HEADERS).text

    def parse(text: str):
        data = json.loads(text)
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return [], False, "no `data` list in the Pinpoint postings feed"
        scraped_at = datetime.now(timezone.utc)
        return [_to_posting(o, company, base, scraped_at) for o in _items(items)], True, ""

    return run_probe(fetch, parse, "json")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

FEED_KEY = "data"


def _host(entry: str) -> str:
    return entry if "." in entry else f"{entry}.pinpointhq.com"


def detect_url(url: str) -> Detection | None:
    """A Pinpoint career site (``<account>.pinpointhq.com``) and the account it names."""
    host, _path, _query = parts(url.strip())
    sub = host.split(".")[0]
    if host.endswith(".pinpointhq.com") and host.count(".") == 2 and sub not in NOT_ACCOUNTS:
        return Detection("pinpoint", sub, f"Pinpoint career site {host}")
    return None


def feed_url(entry: str) -> str | None:
    """The feed that lists the jobs of *entry* (an account, or a career site on the employer's own host);
    a detection from page signatures is kept only when it lists jobs (under `FEED_KEY`)."""
    return "https://" + _host(entry) + "/postings.json"


def name_probes(slug: str) -> list[Probe]:
    """The public feed to try for a company name's *slug*."""
    return [Probe(feed_url(slug), FEED_KEY, f"Pinpoint site {slug}")]
