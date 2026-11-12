#!/usr/bin/env python3
"""Scraper for Ashby's public job-board API (issue #230).

Ashby documents the API as the way to build your own job board from a company's
postings, without a key:

  GET https://api.ashbyhq.com/posting-api/job-board/<board>
      → ``{"jobs": [{id, title, location, secondaryLocations, isRemote,
      workplaceType, isListed, publishedAt, jobUrl, applyUrl, descriptionHtml,
      descriptionPlain, ...}]}`` (no pagination)

Configured by ``ashby_companies``: each board's name, the slug in
``jobs.ashbyhq.com/<board>``, or that URL. Unlisted jobs are skipped.

Terms: https://www.ashbyhq.com/resources/terms — the API is documented for
building your own job board. robots.txt answers 401 (allowed).
"""

import html as _html
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from door.scrapers.sdk import (
    JobPosting, PoliteSession, PROBE_TIMEOUT_S, ProbeResult, make_job_id, parse_iso_date, run_probe,
    scrape_feeds, followed_name,
)
from door.scrapers.sdk import keep_local
from door.scrapers.sdk import Detection, Probe, first, parts

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("ashbyhq.com",)

_SITE = "ashby"
_BOARD_URL = "https://api.ashbyhq.com/posting-api/job-board/{board}"
_HEADERS = {"Accept": "application/json"}


def _board_name(entry: str) -> str:
    """The board name in an ``ashby_companies`` entry: a slug or a board URL. Pure."""
    entry = entry.strip()
    if "/" not in entry:
        return entry.lower()
    parts = [p for p in urlparse(entry if "://" in entry else f"https://{entry}").path.split("/") if p]
    return parts[0].lower() if parts else ""


def _location_text(job: dict) -> str:
    """The job's locations, "; "-joined, prefixed ``Remote`` for a remote job. Pure."""
    places = [(job.get("location") or "").strip()]
    places += [((s or {}).get("location") or "").strip() for s in job.get("secondaryLocations") or []]
    text = "; ".join(p for p in places if p)
    workplace = (job.get("workplaceType") or "").lower()
    if workplace == "remote" or (job.get("isRemote") and not workplace):
        return f"Remote, {text}" if text else "Remote"
    return text


def _description(job: dict) -> str:
    plain = (job.get("descriptionPlain") or "").strip()
    if plain:
        return plain
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", job.get("descriptionHtml") or ""))).strip()


def _to_posting(job: dict, board: str, scraped_at: datetime, name: str = "") -> dict:
    platform_id = str(job.get("id") or "")
    title = (job.get("title") or "").strip()
    url = job.get("jobUrl") or ""
    posting = JobPosting(
        id=make_job_id(_SITE, platform_id),
        title=title,
        company=name or board,
        location=_location_text(job),
        url=url,
        description=_description(job),
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=parse_iso_date(job.get("publishedAt")),
        apply_type="external",
        apply_url=job.get("applyUrl") or url,
    )
    return posting.model_dump(mode="json")


def _listed(jobs) -> list[dict]:
    return [j for j in jobs if isinstance(j, dict) and j.get("id") and j.get("isListed", True) is not False]


def _board_postings(session: PoliteSession, board: str, scraped_at: datetime, name: str = "") -> list[dict]:
    """Every listed job on Ashby board *board*, labelled with the followed *name* when given.
    Raises on HTTP errors."""
    jobs = session.get(_BOARD_URL.format(board=board), headers=_HEADERS).json().get("jobs") or []
    return [_to_posting(job, board, scraped_at, name) for job in _listed(jobs)]


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Every listed job on each configured Ashby board."""
    names = {_board_name(e): followed_name(config, "ashby_companies", e) for e in config.get("ashby_companies") or []
             if e.strip()}

    def fetch(session, board, scraped_at):
        return _board_postings(session, board, scraped_at, names.get(board, ""))

    return keep_local(scrape_feeds(_SITE, list(names), fetch, headers=_HEADERS), config, _SITE)


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the first configured board. ``None`` when none is set."""
    boards = [_board_name(e) for e in config.get("ashby_companies") or [] if e.strip()]
    if not boards:
        return None
    board = boards[0]
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

    def fetch() -> str:
        return session.get(_BOARD_URL.format(board=board), headers=_HEADERS).text

    def parse(text: str):
        data = json.loads(text)
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, list):
            return [], False, "no `jobs` list in the Ashby job-board response"
        scraped_at = datetime.now(timezone.utc)
        return [_to_posting(j, board, scraped_at) for j in _listed(jobs)], True, ""

    return run_probe(fetch, parse, "json")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

def detect_url(url: str) -> Detection | None:
    """An Ashby board link (``jobs.ashbyhq.com/<board>``) and the board it names."""
    host, path, _query = parts(url.strip())
    if host != "jobs.ashbyhq.com":
        return None
    board = first(path)
    return Detection("ashby", board, f"Ashby board link {url}") if board else None

def feed_url(entry: str) -> str | None:
    """None: a link to the board names the account, no feed check is needed."""
    return None


def name_probes(slug: str) -> list[Probe]:
    """The public job-board API to try for a company name's *slug*."""
    return [Probe(_BOARD_URL.format(board=slug), "jobs", f"Ashby board {slug}")]
