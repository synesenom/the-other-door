#!/usr/bin/env python3
"""Scraper for Lever ATS public job boards API.

Uses the Lever public postings JSON API (unauthenticated).
Configured by ``lever_companies`` in the profile config — a list of company
slugs, e.g. ``["acme", "contoso"]``, or their board URLs
(``jobs.lever.co/<slug>``, ``jobs.eu.lever.co/<slug>``).

API endpoint used:
  GET https://api.lever.co/v0/postings/{slug}?mode=json
      → array of postings (no pagination)

EU-hosted accounts live on ``api.eu.lever.co`` and answer 404 on the US host,
so a bare slug that 404s there is tried on the EU host (one extra request; the
scraper keeps no state). A ``jobs.eu.lever.co`` URL goes straight to the EU
host. Lever's robots.txt asks ``Crawl-delay: 1``, which ``PoliteSession`` honours.

Terms: https://www.lever.co/legal/terms-of-service — the postings API is
documented as public. robots.txt allows everything, `Crawl-delay: 1`.
"""

import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from door.scrapers.sdk import (
    JobPosting, PoliteSession, PROBE_TIMEOUT_S, ProbeResult, make_job_id, run_probe, scrape_feeds, followed_name,
)
from door.scrapers.sdk import keep_local
from door.scrapers.sdk import Detection, Probe, first, parts

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("lever.co",)

_API_BASE = "https://api.lever.co/v0/postings"
_EU_API_BASE = "https://api.eu.lever.co/v0/postings"

_HEADERS = {
    "Accept": "application/json",
}


def _html_text(html: str) -> str:
    """*html* as plain text, one line per block element. Pure."""
    return BeautifulSoup(html, "html.parser").get_text(separator="\n", strip=True)


def _description_text(job: dict) -> str:
    """The whole ad as plain text. Pure.

    ``descriptionPlain`` is only the opening: the duties and requirements are in
    ``lists`` (``{"text": heading, "content": "<li>…"}``) and the closing text in
    ``additionalPlain``, so all three are joined.
    """
    parts = [(job.get("descriptionPlain") or "").strip() or _html_text(job.get("description") or "")]
    for section in job.get("lists") or []:
        body = _html_text(section.get("content") or "")
        parts.append("\n".join(p for p in ((section.get("text") or "").strip(), body) if p))
    parts.append((job.get("additionalPlain") or "").strip() or _html_text(job.get("additional") or ""))
    return "\n\n".join(p for p in parts if p)


def _location_text(job: dict) -> str:
    """Return the location string from a Lever job dict."""
    categories = job.get("categories") or {}
    return (categories.get("location") or "").strip()


def _parse_date(s: Any) -> str | None:
    """Parse a millisecond Unix timestamp to an ISO 8601 string.

    Lever's ``createdAt`` field is an integer in milliseconds.
    Returns None when *s* is missing, not an int, or otherwise unparseable.
    """
    if not isinstance(s, int):
        return None
    try:
        return datetime.fromtimestamp(s / 1000, tz=timezone.utc).replace(tzinfo=None).isoformat()
    except (ValueError, OSError, OverflowError):
        return None


def _company(entry: str) -> tuple[str, str | None]:
    """``(slug, API base or None)`` for a ``lever_companies`` entry; None means try
    the US host, then the EU one. Pure."""
    entry = entry.strip()
    if "/" not in entry:
        return entry.lower(), None
    parsed = urlparse(entry if "://" in entry else f"https://{entry}")
    parts = [p for p in parsed.path.split("/") if p]
    base = _EU_API_BASE if ".eu." in f".{parsed.netloc.lower()}" else _API_BASE
    return (parts[0].lower() if parts else ""), base


def _fetch_postings(session: PoliteSession, entry: str):
    """``(slug, response)`` for one company, from its host (US, then EU on a 404).

    Raises on HTTP errors (the EU host's, when both were tried) or robots.txt.
    """
    import requests

    slug, base = _company(entry)
    for candidate in ([base] if base else [_API_BASE, _EU_API_BASE]):
        try:
            resp = session.get(f"{candidate}/{slug}", headers=_HEADERS, params={"mode": "json"})
        except requests.HTTPError as exc:
            if base is None and candidate == _API_BASE and getattr(exc.response, "status_code", None) == 404:
                continue
            raise
        return slug, resp
    raise RuntimeError("unreachable")  # pragma: no cover - the loop returns or raises


def _company_postings(session: PoliteSession, entry: str, scraped_at: datetime, name: str = "") -> list[dict]:
    """The postings of one ``lever_companies`` entry, labelled with the followed *name* when given.
    Raises on HTTP errors."""
    slug, resp = _fetch_postings(session, entry)
    return [_to_posting(job, slug, scraped_at, name) for job in resp.json() or []]


def _to_posting(job: dict, slug: str, scraped_at: datetime, name: str = "") -> dict:
    """Map one Lever posting dict to a JobPosting dict."""
    platform_id = str(job.get("id") or "")
    title = (job.get("text") or "").strip()
    posting = JobPosting(
        id=make_job_id("lever", platform_id),
        title=title,
        company=name or slug,
        location=_location_text(job),
        url=job.get("hostedUrl") or "",
        description=_description_text(job),
        source="lever",
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=_parse_date(job.get("createdAt")),
        apply_type="external",
        apply_url=job.get("hostedUrl") or "",
    )
    return posting.model_dump(mode="json")


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Return a list of JobPosting-compatible dicts from configured Lever boards."""
    def fetch(session, entry, scraped_at):
        return _company_postings(session, entry, scraped_at, followed_name(config, "lever_companies", entry))

    return keep_local(scrape_feeds("lever", config.get("lever_companies") or [], fetch, headers=_HEADERS), config, "lever")


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the first configured company. ``None`` when none is set."""
    companies: list[str] = config.get("lever_companies", [])
    if not companies:
        return None
    entry = companies[0]
    slug = _company(entry)[0]
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

    def fetch() -> str:
        return _fetch_postings(session, entry)[1].text

    def parse(text: str):
        jobs = json.loads(text)
        if not isinstance(jobs, list):
            return [], False, "the postings API did not return a JSON array"
        scraped_at = datetime.now(timezone.utc)
        return [_to_posting(j, slug, scraped_at) for j in jobs if isinstance(j, dict) and j.get("id")], True, ""

    return run_probe(fetch, parse, "json")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

def detect_url(url: str) -> Detection | None:
    """A Lever board link (``jobs.lever.co/<slug>``, the EU host too) and the account it names."""
    host, path, _query = parts(url.strip())
    if host not in ("jobs.lever.co", "jobs.eu.lever.co"):
        return None
    slug = first(path)
    return Detection("lever", slug, f"Lever board link {url}") if slug else None

def feed_url(entry: str) -> str | None:
    """None: a link to the board names the account, no feed check is needed."""
    return None


def name_probes(slug: str) -> list[Probe]:
    """The public postings API to try for a company name's *slug*: the US host, then the EU one."""
    return [Probe(f"{_API_BASE}/{slug}", None, f"Lever account {slug}", {"mode": "json"}),
            Probe(f"{_EU_API_BASE}/{slug}", None, f"Lever account {slug} (EU host)", {"mode": "json"})]
