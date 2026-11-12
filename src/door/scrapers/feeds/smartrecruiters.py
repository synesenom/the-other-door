#!/usr/bin/env python3
"""Scraper for SmartRecruiters' public postings API.

Every SmartRecruiters customer's open postings are public, without a key:

  GET https://api.smartrecruiters.com/v1/companies/<id>/postings?limit=100&offset=N
      → ``{"totalFound": n, "content": [{id, name, releasedDate, location,
      company: {identifier, name}, ...}]}`` (no description; paged by ``offset``)
  GET https://api.smartrecruiters.com/v1/companies/<id>/postings/<posting id>
      → the posting with ``jobAd.sections`` (company description, job description,
      qualifications, additional information; HTML), ``postingUrl`` and ``applyUrl``

The detail is fetched once per posting that is not in ``known_ids``; a failed
detail keeps the posting from the listing, without a description.

Configured by ``smartrecruiters_companies``: each customer's company identifier
(``interikeagroup``, ``NCS3`` — the first path segment of its
``jobs.smartrecruiters.com/<id>/…`` links; the API ignores case).

Terms: https://www.smartrecruiters.com/legal/terms-of-use/ — nothing on scraping or bots; the
postings API is public and documented for developers.
"""

import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from door.scrapers.sdk import (
    country_is_non_local, JobPosting, PoliteSession, PROBE_TIMEOUT_S, ProbeResult, make_job_id, parse_iso_date, record_error,
    record_non_local, report, run_probe, scrape_feeds, strip_html,
    followed_name,
)
from door.scrapers.sdk import Detection, Probe, first, parts

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("smartrecruiters.com", "smrtr.io")

_SITE = "smartrecruiters"
_API = "https://api.smartrecruiters.com/v1/companies"
_HEADERS = {"Accept": "application/json"}
_PAGE = 100
_MAX_POSTINGS = 3000  # a safety stop for a runaway listing
_SECTIONS = ("companyDescription", "jobDescription", "qualifications", "additionalInformation")


def _company_id(entry: str) -> str:
    """The company identifier of a ``smartrecruiters_companies`` entry: an id or a careers link. Pure."""
    entry = entry.strip()
    if "/" in entry or "." in entry:
        path = [p for p in urlparse(entry if "://" in entry else f"https://{entry}").path.split("/") if p]
        return path[0] if path else entry
    return entry


def _location_text(location) -> str:
    """``City, Country`` from the posting's location, prefixed ``Remote`` for remote work. Pure."""
    if not isinstance(location, dict):
        return ""
    full = ", ".join(p.strip() for p in (location.get("fullLocation") or "").split(",") if p.strip())
    text = full or ", ".join(p for p in ((location.get("city") or "").strip(), (location.get("country") or "").strip().upper()) if p)
    if location.get("remote"):
        return f"Remote, {text}" if text else "Remote"
    return text


def _description(sections) -> str:
    """The posting's sections as plain text, in reading order. Pure."""
    if not isinstance(sections, dict):
        return ""
    return "\n\n".join(t for t in (strip_html((sections.get(k) or {}).get("text") or "") for k in _SECTIONS) if t)


def _to_posting(item: dict, detail: dict | None, entry_id: str, scraped_at: datetime, name: str = "") -> dict:
    """A `JobPosting` dict from a listing item and (when it could be fetched) its detail. Pure."""
    detail = detail or {}
    platform_id = str(item.get("id") or "")
    title = (item.get("name") or detail.get("name") or "").strip()
    company_info = item.get("company") or detail.get("company") or {}
    company = (name or company_info.get("name") or entry_id).strip()
    identifier = company_info.get("identifier") or entry_id
    url = detail.get("postingUrl") or f"https://jobs.smartrecruiters.com/{identifier}/{platform_id}"
    posting = JobPosting(
        id=make_job_id(_SITE, platform_id),
        title=title,
        company=company,
        location=_location_text(item.get("location") or detail.get("location")),
        url=url,
        description=_description((detail.get("jobAd") or {}).get("sections")),
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=parse_iso_date(item.get("releasedDate") or detail.get("releasedDate")),
        apply_type="external",
        apply_url=detail.get("applyUrl") or url,
    )
    return posting.model_dump(mode="json")


def _non_local(item: dict, config: dict) -> bool:
    """Whether a listing *item* states a country other than the profile's (remote work stays). Pure."""
    location = item.get("location") if isinstance(item.get("location"), dict) else {}
    return country_is_non_local(location.get("country"), config, remote=bool(location.get("remote")))


def _items(content) -> list[dict]:
    return [o for o in content or [] if isinstance(o, dict) and o.get("id")]


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Every open posting of each configured SmartRecruiters company."""
    entries = [e.strip() for e in config.get("smartrecruiters_companies") or [] if e.strip()]

    def fetch(session: PoliteSession, entry: str, scraped_at: datetime) -> list[dict]:
        """One company's postings. Raises when its listing fails; a failed detail is recorded."""
        company_id = _company_id(entry)
        items: list[dict] = []
        offset = 0
        while offset < _MAX_POSTINGS:
            page = session.get(f"{_API}/{company_id}/postings", params={"limit": _PAGE, "offset": offset}, headers=_HEADERS).json()
            raw = page.get("content") or []
            items.extend(_items(raw))
            offset += len(raw)
            if not raw or offset >= int(page.get("totalFound") or 0):
                break
        fresh = [i for i in items if str(i["id"]) not in known_ids]
        local = [i for i in fresh if not _non_local(i, config)]  # no detail request for a job in another country
        if len(local) < len(fresh):
            record_non_local(_SITE, len(fresh) - len(local))
        fresh = local
        out: list[dict] = []
        for n, item in enumerate(fresh, 1):
            report("detail", n, len(fresh))
            try:
                detail = session.get(f"{_API}/{company_id}/postings/{item['id']}", headers=_HEADERS).json()
            except Exception as exc:
                record_error(_SITE, f"error fetching posting {item['id']} of {entry!r}: {exc}")
                detail = None
            out.append(_to_posting(item, detail, company_id, scraped_at, followed_name(config, "smartrecruiters_companies", entry)))
        return out

    # One host serves every company, so they are read one after the other.
    return scrape_feeds(_SITE, entries, fetch, headers=_HEADERS)


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: page 1 of the first configured company's listing. ``None`` when none is set."""
    entries = [e for e in config.get("smartrecruiters_companies") or [] if e.strip()]
    if not entries:
        return None
    company_id = _company_id(entries[0])
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

    def fetch() -> str:
        return session.get(f"{_API}/{company_id}/postings", params={"limit": 20}, headers=_HEADERS).text

    def parse(text: str):
        data = json.loads(text)
        content = data.get("content") if isinstance(data, dict) else None
        if not isinstance(content, list):
            return [], False, "no `content` list in the SmartRecruiters postings response"
        scraped_at = datetime.now(timezone.utc)
        return [_to_posting(o, None, company_id, scraped_at) for o in _items(content)], True, ""

    return run_probe(fetch, parse, "json")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

# An aggregator's own id for a SmartRecruiters ad: smartrecruiters:<company>:<posting>.
_SR_STRING = re.compile(r"smartrecruiters:([A-Za-z0-9_.-]+):\d+", re.IGNORECASE)


def detect_url(url: str) -> Detection | None:
    """A SmartRecruiters careers link, the string form an aggregator uses, or a short link (no company)."""
    string_form = _SR_STRING.search(url)
    if string_form:
        return Detection("smartrecruiters", string_form.group(1).lower(), f"SmartRecruiters company named in {url}")
    host, path, _query = parts(url.strip())
    if host in ("jobs.smartrecruiters.com", "careers.smartrecruiters.com"):
        company = first(path)
        return Detection("smartrecruiters", company, f"SmartRecruiters careers link {url}") if company else None
    if host in ("www.smartrecruiters.com", "smartrecruiters.com") and len(path) >= 3 \
            and [p.lower() for p in path[:2]] == ["web-sso", "saml"]:
        # the staff sign-in an employer's own careers site links to names its company (H&M's career.hm.com, #566)
        return Detection("smartrecruiters", path[2].lower(), f"SmartRecruiters company {path[2]} named by the sign-in link {url}")
    if host == "join.smartrecruiters.com":
        company = first(path)   # the employer's talent community
        return Detection("smartrecruiters", company, f"SmartRecruiters company {path[0]} named by its talent community link {url}") \
            if company else None
    if host.endswith("smrtr.io"):
        return Detection("smartrecruiters", None, f"SmartRecruiters short link {url}: it names no company")
    return None

def feed_url(entry: str) -> str | None:
    """None: a link to the board names the account, no feed check is needed."""
    return None


def name_probes(slug: str) -> list[Probe]:
    """The public postings API to try for a company name's *slug*."""
    return [Probe(f"{_API}/{slug}/postings", "content", f"SmartRecruiters company {slug}", {"limit": 100})]
