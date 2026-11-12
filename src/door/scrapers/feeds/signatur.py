#!/usr/bin/env python3
"""Scraper for the Signatur recruitment portal's public job lists (Danish municipalities and others).

Every Signatur customer (a ``ClientId``) has a public list of its open jobs:

  GET https://portal.signatur.dk/ExtJobs/DefaultHosting/JobList.aspx?ClientId=<id>
      → HTML: the ``<title>`` is ``<employer> - Ledige stillinger``; each job is an
      ``<a href="JobDetails.aspx?ClientId=<id>&WebAdId=<n>">`` holding the title
  GET https://portal.signatur.dk/ExtJobs/DefaultHosting/JobDetails.aspx?ClientId=<id>&WebAdId=<n>
      → HTML: ``<h1>`` title, the ad body in ``contentBodyOuterDiv`` and the
      workplace address in the hidden ``googleMapAddressHf`` input

The portal publishes no posting date; ``posted_at`` stays empty. The detail is
fetched once per job that is not in ``known_ids`` (a ``<ClientId>-<WebAdId>`` platform
id); a failed detail keeps the job from the list, without a description.

Configured by ``signatur_companies``: each customer's ClientId, or any portal link
carrying ``ClientId=`` (the apply links ``JobApplication.aspx?ClientId=1449&ERId=…``).

Terms: https://portal.signatur.dk/ExtJobs/DefaultHosting/TermsAndConditions.aspx?ClientId=1449 —
the applicants' data-protection policy; nothing on reading the public job list.
robots.txt: the portal host has none (404).
"""

import html as _html
import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, unquote_plus, urlparse

from bs4 import BeautifulSoup

from door.scrapers.sdk import (
    FEED_DELAY, JobPosting, PoliteSession, PROBE_TIMEOUT_S, ProbeResult, log_keyword_results, make_job_id,
    map_by_group, record_entry_error, record_error, report, run_probe, strip_html, workers, followed_name,
)
from door.scrapers.sdk import Detection, parts

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("signatur.dk",)

_SITE = "signatur"
_BASE = "https://portal.signatur.dk/ExtJobs/DefaultHosting"
_HOST = "portal.signatur.dk"
_TITLE_SUFFIX = re.compile(r"\s+-\s+Ledige stillinger\s*$", re.IGNORECASE)
_WEBADID = re.compile(r"WebAdId=(\d+)", re.IGNORECASE)


def _client_id(entry: str) -> str:
    """The ClientId of a ``signatur_companies`` entry: the number, or a portal link carrying ``ClientId=``. Pure."""
    entry = entry.strip()
    if entry.isdigit():
        return entry
    query = {k.lower(): v[0] for k, v in parse_qs(urlparse(entry if "://" in entry else f"https://{entry}").query).items()}
    return query.get("clientid", entry)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(text or "")).strip()


def _parse_list(html: str) -> tuple[str | None, list[dict]]:
    """``(employer, [{id, title}])`` from a JobList page. Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    company = None
    if soup.title and soup.title.string:
        name = _TITLE_SUFFIX.sub("", _clean(soup.title.string))
        company = name or None
    jobs: list[dict] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        match = _WEBADID.search(a["href"])
        if "JobDetails" not in a["href"] or not match or match.group(1) in seen:
            continue
        box = a.find("div")
        title = _clean(" ".join(box.find_all(string=True, recursive=False))) if box else ""
        if not title:
            continue
        seen.add(match.group(1))
        jobs.append({"id": match.group(1), "title": title})
    return company, jobs


def _parse_detail(html: str) -> dict | None:
    """``{title, location, description}`` from a JobDetails page; ``None`` when it is not an ad. Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    body = soup.find(id="ctl00_mainContent_contentBodyOuterDiv")
    if body is None:
        return None
    h1 = soup.find(id="ctl00_mainContent_contentHeadlineH1")
    address = soup.find(id="ctl00_mainContent_googleMapAddressHf")
    return {
        "title": _clean(h1.get_text(" ")) if h1 else "",
        "location": _clean(unquote_plus(address.get("value") or "")) if address else "",
        "description": strip_html(body.decode_contents()),
    }


def _detail_url(client: str, web_ad_id: str) -> str:
    return f"{_BASE}/JobDetails.aspx?ClientId={client}&WebAdId={web_ad_id}"


def _to_posting(job: dict, detail: dict | None, client: str, company: str, scraped_at: datetime) -> dict:
    detail = detail or {}
    platform_id = f"{client}-{job['id']}"
    title = detail.get("title") or job["title"]
    url = _detail_url(client, job["id"])
    posting = JobPosting(
        id=make_job_id(_SITE, platform_id),
        title=title,
        company=company,
        location=detail.get("location") or "",
        url=url,
        description=detail.get("description") or "",
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=platform_id,
        apply_type="external",
        apply_url=url,
    )
    return posting.model_dump(mode="json")


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Every open job of each configured Signatur customer."""
    entries = [e for e in config.get("signatur_companies") or [] if e.strip()]
    if not entries:
        return []
    scraped_at = datetime.now(timezone.utc)
    session = PoliteSession(min_delay=FEED_DELAY[0], max_delay=FEED_DELAY[1], timeout=30)

    def fetch(entry: str) -> list[dict] | None:
        """One customer's jobs; ``None`` after a recorded error."""
        client = _client_id(entry)
        try:
            company, jobs = _parse_list(session.get(f"{_BASE}/JobList.aspx", params={"ClientId": client}).text)
        except Exception as exc:
            report(f"error fetching jobs for {entry!r}: {exc}")
            record_entry_error(_SITE, entry, f"error fetching jobs for {entry!r}: {exc}")
            return None
        company = followed_name(config, "signatur_companies", entry, company or f"Signatur {client}")
        fresh = [j for j in jobs if f"{client}-{j['id']}" not in known_ids]
        out: list[dict] = []
        for n, job in enumerate(fresh, 1):
            report("detail", n, len(fresh))
            try:
                detail = _parse_detail(session.get(_detail_url(client, job["id"])).text)
            except Exception as exc:
                record_error(_SITE, f"error fetching job {job['id']} of {entry!r}: {exc}")
                detail = None
            out.append(_to_posting(job, detail, client, company, scraped_at))
        return out

    fetched = map_by_group(entries, lambda e: _HOST, fetch, workers(config))
    seen: set[str] = set()
    postings: list[dict] = []
    for entry, company_postings in zip(entries, fetched):
        if company_postings is None:
            continue
        fresh = [p for p in company_postings if p["platform_id"] not in seen]
        seen.update(p["platform_id"] for p in fresh)
        log_keyword_results(_SITE, entry.strip(), fresh)
        postings.extend(fresh)
    return postings


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the first customer's job list. ``None`` when none is set."""
    entries = [e for e in config.get("signatur_companies") or [] if e.strip()]
    if not entries:
        return None
    client = _client_id(entries[0])
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0)

    def fetch() -> str:
        return session.get(f"{_BASE}/JobList.aspx", params={"ClientId": client}).text

    def parse(text: str):
        company, jobs = _parse_list(text)
        if not jobs and "JobList" not in text and "special-link" not in text:
            return [], False, "no job links in the Signatur job list"
        scraped_at = datetime.now(timezone.utc)
        return [_to_posting(j, None, client, company or f"Signatur {client}", scraped_at) for j in jobs], True, ""

    return run_probe(fetch, parse, "html")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

def detect_url(url: str) -> Detection | None:
    """A Signatur job-portal link and the numeric ``ClientId`` it names."""
    host, _path, query = parts(url.strip())
    if host != "portal.signatur.dk":
        return None
    client = query.get("clientid", "")
    return Detection("signatur", client, f"Signatur job portal link {url}") if client.isdigit() else None

def feed_url(entry: str) -> str | None:
    """None: a link to the board names the account, no feed check is needed."""
    return None
