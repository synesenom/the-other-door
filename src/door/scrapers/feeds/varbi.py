#!/usr/bin/env python3
"""Scraper for Varbi's public job boards and RSS feeds (issue #525).

Varbi (Grade Varbi Recruit, varbi.com) is the recruiting system of much of Swedish public sector: universities
(``ki``, ``kth``, ``uu``, ``su``), regions, municipalities and authorities each have a board on
``<tenant>.varbi.com`` that needs no login, key or cookie:

  GET https://<tenant>.varbi.com/what:rssfeed/
      RSS 2.0, every open ad of the tenant in one answer (no paging): ``<item>`` with ``title``, ``link``
      (``.../what:job/jobID:<id>/``), ``description`` (the ad's whole text, plain), ``pubDate`` (midnight, the
      day it was published), ``guid``. The channel title (``New jobs at <employer>``) names the employer. The
      feed has no place and no department.
  GET https://<tenant>.varbi.com/
      The board page, server-rendered, every open ad too: a table row each with the title, the town
      (``td.pos-town``), the department (``td.pos-subcompany``) and the deadline (``td.pos-ends``). The
      two are joined by job id; a board page that cannot be read leaves the ads without a place.

The ad page (``/what:job/jobID:<id>/``) is not opened: the feed holds its text, and applying needs a Varbi
account (``/what:login/...``), which door never uses. An unknown tenant answers 404 with an HTML error page.

Configured by ``varbi_tenants``: the tenant slug (``ki`` for ``ki.varbi.com``) or any link on its host. An
apply link from Jobbsafari or Platsbanken on a ``<tenant>.varbi.com`` host is what ``follow`` detects.

Terms: Grade Varbi's terms for candidates (https://www.grade.com/villkor-grade-varbi/) cover candidate accounts
and the brand; they say nothing of reading the public job list or the feed, which the platform offers
itself (its board page links ``/what:rssfeed/``). robots.txt on a tenant host disallows only a few
named crawlers (SemrushBot, AhrefsBot, ...), not other agents.
"""

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from door.scrapers.sdk import (
    Detection, JobPosting, NOT_ACCOUNTS, PROBE_TIMEOUT_S, PoliteSession, ProbeResult, followed_name, keep_local,
    make_job_id, parts, record_error, report, run_probe, scrape_feeds, strip_html, tenant_platform_id, workers,
    host_of,
)

# The platform's own domains: a host on one is a customer's, never the employer's name.
PLATFORM_DOMAINS = ("varbi.com",)

# `companies add` reads the board page of a link on a tenant: its title names the employer.
NAME_FROM_PAGE = True

_SITE = "varbi"
_SUFFIX = ".varbi.com"
# Hosts of Varbi's own that are no employer's board.
_NOT_TENANTS = NOT_ACCOUNTS | {"web", "profile", "cdn", "mail", "support", "help", "docs", "static", "img"}
_JOB_ID = re.compile(r"jobID:(\d+)", re.IGNORECASE)
_CHANNEL = re.compile(r"^(?:New jobs at|Nya lediga jobb hos|Lediga jobb hos)\s+", re.IGNORECASE)


def _tenant(entry: str) -> str:
    """The tenant slug of a ``varbi_tenants`` entry: a slug or a link on ``<tenant>.varbi.com``. Pure."""
    entry = entry.strip().lower()
    host = parts(entry)[0] if ("://" in entry or "." in entry) else entry
    return host[: -len(_SUFFIX)] if host.endswith(_SUFFIX) else host


def _base(tenant: str) -> str:
    return f"https://{tenant}{_SUFFIX}"


def _job_id(url: str) -> str:
    """The job id of an ad link (``.../what:job/jobID:985204/``), "" for any other link. Pure."""
    match = _JOB_ID.search(url or "")
    return match.group(1) if match else ""


def _channel_name(title: str) -> str:
    """The employer a feed's channel title names (``New jobs at Acme`` → ``Acme``); the title as it is without
    the known lead-in. Pure."""
    return _CHANNEL.sub("", (title or "").strip()).strip()


def parse_feed(xml_text: str) -> tuple[str, list[dict]]:
    """``(employer name, ads)`` of a tenant's RSS feed; each ad ``{id, title, url, description, posted_at}``.
    Raises ``ValueError`` when the text is no RSS feed (an HTML error page, a block page). Pure."""
    try:
        root = ElementTree.fromstring((xml_text or "").encode("utf-8"))
    except ElementTree.ParseError as exc:
        raise ValueError(f"not an RSS feed: {exc}") from exc
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise ValueError("no RSS channel in Varbi's answer")
    ads = []
    for item in channel.findall("item"):
        url = (item.findtext("link") or "").strip()
        job_id = _job_id(url)
        if not job_id:
            continue
        try:
            posted = parsedate_to_datetime(item.findtext("pubDate") or "")
        except (TypeError, ValueError):
            posted = None
        ads.append({
            "id": job_id,
            "title": (item.findtext("title") or "").strip(),
            "url": url,
            "description": strip_html(item.findtext("description") or ""),
            "posted_at": posted,
        })
    return _channel_name(channel.findtext("title") or ""), ads


def parse_list(html: str) -> dict[str, dict]:
    """The rows of a tenant's board page by job id: ``{id: {location, department, deadline}}``; empty when the
    page has none. Pure."""
    rows: dict[str, dict] = {}
    for tr in BeautifulSoup(html or "", "html.parser").find_all("tr"):
        link = tr.find("a", href=_JOB_ID)
        if link is None:
            continue

        def cell(name: str) -> str:
            td = tr.find("td", class_=name)
            return " ".join(td.get_text(" ", strip=True).split()) if td is not None else ""

        rows[_job_id(link["href"])] = {
            "location": cell("pos-town"), "department": cell("pos-subcompany"), "deadline": cell("pos-ends"),
        }
    return rows


def _to_posting(ad: dict, tenant: str, scraped_at: datetime, name: str = "", row: dict | None = None) -> dict:
    platform_id = tenant_platform_id(_base(tenant), ad["id"])
    posting = JobPosting(
        id=make_job_id(_SITE, platform_id),
        title=ad["title"],
        company=name or tenant,
        location=(row or {}).get("location", ""),
        url=ad["url"],
        description=ad["description"],
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=ad["posted_at"],
        apply_type="external",
        apply_url=ad["url"],
    )
    return posting.model_dump(mode="json")


def _get(session: PoliteSession, url: str, accept: str) -> str:
    return session.get(url, headers={"Accept": accept}).text


def _tenant_postings(session: PoliteSession, entry: str, scraped_at: datetime, name: str = "") -> list[dict]:
    """Every open ad of one tenant, labelled with the followed *name* when given. Raises when the feed cannot
    be read; a board page that cannot be read only leaves the places out."""
    tenant = _tenant(entry)
    channel, ads = parse_feed(_get(session, f"{_base(tenant)}/what:rssfeed/", "application/rss+xml"))
    rows: dict[str, dict] = {}
    if ads:
        try:
            rows = parse_list(_get(session, f"{_base(tenant)}/", "text/html"))
        except Exception as exc:  # noqa: BLE001 - the ads stay, without a place
            message = f"error fetching the board page of {tenant!r}: {exc}"
            report(message)
            record_error(_SITE, message)
    label = name or channel
    return [_to_posting(ad, tenant, scraped_at, label, rows.get(ad["id"])) for ad in ads]


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Every open ad of each configured Varbi board. The feed holds the ads' text, so a known ad saves no
    request and *known_ids* is not needed."""
    entries = [e.strip() for e in config.get("varbi_tenants") or [] if e.strip()]

    def fetch(session, entry, scraped_at):
        return _tenant_postings(session, entry, scraped_at, followed_name(config, "varbi_tenants", entry))

    return keep_local(scrape_feeds(_SITE, entries, fetch, group=lambda e: host_of(_base(_tenant(e))),
                                   max_workers=workers(config)), config, _SITE)


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the RSS feed of the first configured tenant (one request). ``None`` when
    none is set."""
    entries = [e for e in config.get("varbi_tenants") or [] if e.strip()]
    if not entries:
        return None
    tenant = _tenant(entries[0])
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0)

    def fetch() -> str:
        return _get(session, f"{_base(tenant)}/what:rssfeed/", "application/rss+xml")

    def parse(text: str):
        try:
            channel, ads = parse_feed(text)
        except ValueError as exc:
            return [], False, str(exc)
        scraped_at = datetime.now(timezone.utc)
        return [_to_posting(ad, tenant, scraped_at, channel) for ad in ads], True, ""

    return run_probe(fetch, parse, "xml")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

def detect_url(url: str) -> Detection | None:
    """A link on a Varbi board (``<tenant>.varbi.com``: a job ad, the board page) and the tenant it names."""
    host, _path, _query = parts(url.strip())
    tenant = host[: -len(_SUFFIX)] if host.endswith(_SUFFIX) else ""
    if tenant and "." not in tenant and tenant not in _NOT_TENANTS:
        return Detection("varbi", tenant, f"Varbi board {host}")
    return None


def feed_url(entry: str) -> str | None:
    """None: the feed is RSS, not the JSON list the confirmation reads; the link's shape (a tenant host) vouches
    for it, and `alive_url` drops a board that does not exist."""
    return None


def name_page(entry: str, link: str) -> str:
    """The page that names the employer: the tenant's board page, whatever *link* (an ad, whose title is the job's)."""
    return f"{_base(_tenant(entry))}/"


def alive_url(entry: str) -> str:
    """The first read of a board's feed: an unknown tenant answers 404, which `companies add` reports."""
    return f"{_base(_tenant(entry))}/what:rssfeed/"
