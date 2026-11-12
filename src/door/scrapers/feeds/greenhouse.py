#!/usr/bin/env python3
"""Scraper for Greenhouse ATS public boards API.

Uses the Greenhouse public boards JSON API (unauthenticated).
Configured by ``greenhouse_boards`` in the profile config — a list of board
tokens (slugs), e.g. ``["acme", "contoso"]``, or the boards' URLs
(``job-boards.greenhouse.io/<token>``, its ``.eu.`` twin, the older
``boards.greenhouse.io/<token>`` or an embed link ``?for=<token>``). The API
host serves EU-hosted boards too; Greenhouse documents it as public
("authentication is not required for any GET endpoints").

API endpoint used:
  GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
      → jobs list (``{"jobs": [...], "meta": {"total": N}}``)
      Each job includes ``company_name`` — no separate board-info call needed.

Terms: https://www.greenhouse.com/legal — the API is documented as public.
robots.txt disallows only its embed paths.
"""

import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from door.scrapers.sdk import (
    JobPosting, PoliteSession, PROBE_TIMEOUT_S, ProbeResult, make_job_id, parse_iso_date, run_probe,
    scrape_feeds, strip_html, followed_name,
)
from door.scrapers.sdk import keep_local
from door.scrapers.sdk import Detection, Probe, first, parts

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("greenhouse.io", "greenhouse.com")

_API_BASE = "https://boards-api.greenhouse.io/v1/boards"

_HEADERS = {
    "Accept": "application/json",
}


def _location_text(job: dict) -> str:
    """Return the location string from a Greenhouse job dict."""
    loc = job.get("location") or {}
    return (loc.get("name") or "").strip()


def _board_token(entry: str) -> str:
    """The board token in a ``greenhouse_boards`` entry: a token, or a board URL. Pure."""
    entry = entry.strip()
    if "/" not in entry:
        return entry.lower()
    parsed = urlparse(entry if "://" in entry else f"https://{entry}")
    embedded = parse_qs(parsed.query).get("for")
    if embedded:
        return embedded[0].strip().lower()
    parts = [p for p in parsed.path.split("/") if p]
    return parts[0].lower() if parts else ""


def _fetch_board(session: PoliteSession, token: str, scraped_at: datetime, name: str = "") -> list[dict]:
    """The postings of board *token* (each job carries its ``company_name``; the followed *name*
    wins over it). Raises on HTTP errors."""
    resp = session.get(f"{_API_BASE}/{token}/jobs", headers=_HEADERS, params={"content": "true"})
    return [_to_posting(job, token, scraped_at, name) for job in resp.json().get("jobs") or [] if job.get("id")]


def _to_posting(job: dict, token: str, scraped_at: datetime, name: str = "") -> dict:
    """Map one Greenhouse job dict to a JobPosting dict."""
    platform_id = str(job.get("id") or "")
    title = (job.get("title") or "").strip()
    company_name = (name or job.get("company_name") or token).strip()
    posting = JobPosting(
        id=make_job_id("greenhouse", platform_id),
        title=title,
        company=company_name,
        location=_location_text(job),
        url=job.get("absolute_url") or "",
        description=strip_html(job.get("content") or "", encoded=True),
        source="greenhouse",
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=parse_iso_date(job.get("updated_at")),
        apply_type="external",
        apply_url=job.get("absolute_url") or "",
    )
    return posting.model_dump(mode="json")


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Return a list of JobPosting-compatible dicts from configured Greenhouse boards."""
    names = {_board_token(b): followed_name(config, "greenhouse_boards", b) for b in config.get("greenhouse_boards") or []}

    def fetch(session, token, scraped_at):
        return _fetch_board(session, token, scraped_at, names.get(token, ""))

    return keep_local(scrape_feeds("greenhouse", list(names), fetch, headers=_HEADERS), config, "greenhouse")


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the first configured board. ``None`` when none is set."""
    boards: list[str] = config.get("greenhouse_boards", [])
    if not boards:
        return None
    token = _board_token(boards[0])
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

    def fetch() -> str:
        return session.get(f"{_API_BASE}/{token}/jobs", headers=_HEADERS,
                           params={"content": "true"}).text

    def parse(text: str):
        data = json.loads(text)
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, list):
            return [], False, "no `jobs` list in the boards API response"
        scraped_at = datetime.now(timezone.utc)
        return [_to_posting(j, token, scraped_at) for j in jobs if isinstance(j, dict) and j.get("id")], True, ""

    return run_probe(fetch, parse, "json")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

# The vendor's own site: it carries job markup, but is nobody's career site.
JOB_BOARD_EXACT = ("www.greenhouse.com", "greenhouse.com")
_BOARD_HOSTS = ("boards.greenhouse.io", "job-boards.greenhouse.io", "job-boards.eu.greenhouse.io", "boards.eu.greenhouse.io")


def detect_url(url: str) -> Detection | None:
    """A Greenhouse board link (``boards.greenhouse.io/<token>``, ``?for=<token>``) and the board it names."""
    host, path, query = parts(url.strip())
    if host not in _BOARD_HOSTS:
        return None
    token = query.get("for") or first(path)
    return Detection("greenhouse", token, f"Greenhouse board link {url}") if token else None

def feed_url(entry: str) -> str | None:
    """None: a link to the board names the account, no feed check is needed."""
    return None


def name_probes(slug: str) -> list[Probe]:
    """The public board API to try for a company name's *slug*."""
    return [Probe(f"{_API_BASE}/{slug}/jobs", "jobs", f"Greenhouse board {slug}")]
