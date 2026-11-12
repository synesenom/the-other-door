#!/usr/bin/env python3
"""Scraper for employers on Jobtrain, a UK applicant-tracking system (issue #603).

Kind of site: an ATS whose customers publish their ads on a Jobtrain career site, either on the vendor's shared
host, ``https://www.jobtrain.co.uk/<tenant>/`` (Leigh Academies Trust), or on a host of their own that points at
Jobtrain (``jobs.crisis.org.uk``, a DNS CNAME for ``jobs-crisis.jobtrain.co.uk``; the tenant is then served at the
root of that host and the shared path ``www.jobtrain.co.uk/crisis/`` is a 404). The employer is the tenant, never the
shared host: the first path segment names it, so one tenant's ads never mix with another's. Both forms answer the same
two pages, server-rendered and logged out, no key and no login:

  GET <base>/Home/_JobCard?Skip=<n>
      → an HTML fragment of up to 12 ``div.job-card`` (the "load more" call of the jobs page) with hidden inputs
        ``totalMatchRecords`` (all open ads) and ``totalCurrentRecords`` (this page): the ad's id
        (``/Job/JobDetail?JobId=<id>``), title, place name, reference, salary, closing date. ``Skip`` is the offset;
        paging goes on until the total is reached (the jobs page itself starts empty and loads this by script).
  GET <base>/Job/JobDetail?JobId=<id>
      → the ad page, whose ``<script type="application/ld+json">`` (the type written ``ld&#x2B;json``) holds a schema.org
        JobPosting: HTML description, ``datePosted``, ``jobLocation`` (locality, region, country), the hiring
        organisation's name (the tenant's id spelled as one word, ``LeighAcademiesTrust``).
  The ad's text is in the ad page only, so one ad page is fetched per ad that is not in ``known_ids``.

Configured by ``jobtrain_companies`` (filled from ``profile/companies.json``): a tenant slug (``leighacademiestrust``),
a link into ``www.jobtrain.co.uk/<tenant>/`` or the career host of a tenant with its own (``jobs.crisis.org.uk``).
Detection: a link on ``www.jobtrain.co.uk/<tenant>/...``; a career host that is a CNAME for a ``*.jobtrain.co.uk`` host;
or a page whose ``var SITE_BASE_PATH`` / ``var Site_Client_Name`` globals (every Jobtrain page writes them) name the
tenant. This module comes before `career_sites` in ``ats_detect.PRECEDENCE``: the JSON-LD on these pages made that
generic reader take the shared host for the employer (and read every other tenant's ads).

Terms: https://jobtrain.co.uk/privacy-policy/ (the vendor's site has no terms-of-use page; the tenant's own
"Terms & Conditions" page, ``<base>/TermAndCondition``, covers its applicants' accounts); neither mentions scraping,
bots or text-and-data mining. robots.txt: ``www.jobtrain.co.uk/robots.txt`` and ``jobs.crisis.org.uk/robots.txt`` are
404; the marketing site's ``jobtrain.co.uk/robots.txt`` allows everything. Checked 2026-11-04.
"""

import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from door.scrapers.sdk import (
    NOT_ACCOUNTS, Detection, JobPosting, PROBE_TIMEOUT_S, PoliteSession, ProbeResult, RobotsBlocked, followed_name,
    host_of, keep_local, make_job_id, parse_iso_date, parts, record_entry_error, record_error, record_pushback, report,
    run_probe, scrape_feeds, strip_html, workers,
)

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("jobtrain.co.uk",)

_SITE = "jobtrain"
_KEY = "jobtrain_companies"
_SHARED = "www.jobtrain.co.uk"
_VENDOR = "jobtrain.co.uk"
_NOT_TENANTS = NOT_ACCOUNTS | {
    "content", "images", "dist", "lib", "assets", "clientimages", "scripts", "favicon.ico", "robots.txt", "home",
    "privacy-policy", "terms-and-conditions",
}
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_PUSHBACK = (401, 403, 429)
_MAX_PAGES = 100   # list pages per tenant per run (12 ads each)
_HEADERS = {"Accept": "text/html,application/xhtml+xml"}


# --- pure helpers ---

def _target(entry: str) -> tuple[str, str] | None:
    """``(base URL, label)`` of a ``jobtrain_companies`` entry: a tenant slug or a link on the shared host
    (``https://www.jobtrain.co.uk/<slug>``, the slug as label), or any other host, a tenant's own
    (``https://jobs.crisis.org.uk``, the host as label). ``None`` for an entry that names no tenant. Pure."""
    entry = (entry or "").strip().lower()
    if not entry:
        return None
    if "." not in entry and "/" not in entry:
        return (f"https://{_SHARED}/{entry}", entry) if _SLUG.match(entry) else None
    if " " in entry:
        return None
    host, path, _query = parts(entry)
    if not host:
        return None
    if host == _SHARED:
        slug = path[0] if path else ""
        return (f"https://{_SHARED}/{slug}", slug) if slug not in _NOT_TENANTS and _SLUG.match(slug) else None
    if host == _VENDOR or host.endswith("." + _VENDOR):
        return None   # the marketing site, or a host the vendor points customers' domains at (it answers none itself)
    return f"https://{host}", host


def _list_url(base: str, skip: int) -> str:
    return f"{base}/Home/_JobCard?Skip={skip}"


def alive_url(entry: str) -> str | None:
    """The first page of *entry*'s job list: it answers 4xx for a tenant that does not exist."""
    target = _target(entry)
    return _list_url(target[0], 0) if target else None


def feed_url(entry: str) -> str | None:
    """None: the list is HTML, not a JSON answer to confirm by; a link that names a tenant is proof enough."""
    return None


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)) if node is not None else ""


def parse_cards(html: str) -> tuple[int, list[dict]]:
    """``(total open ads, cards)`` of a ``_JobCard`` page; each card ``{id, title, location, reference}``.
    Raises ``ValueError`` when the text is no job list (no ``totalMatchRecords`` input: an error or block page). Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    total_input = soup.find("input", id="totalMatchRecords")
    if total_input is None:
        raise ValueError("no `totalMatchRecords` in the Jobtrain job list")
    try:
        total = int(total_input.get("value") or 0)
    except ValueError as exc:
        raise ValueError(f"bad `totalMatchRecords` in the Jobtrain job list: {exc}") from exc
    cards = []
    for card in soup.select("div.job-card"):
        link = card.select_one("a[href*='JobDetail']")
        found = re.search(r"JobId=(\d+)", link.get("href", "")) if link is not None else None
        title = _text(link)
        if not (found and title):
            continue
        reference = card.select_one("p.jobreference")
        value = _text(reference)
        label = _text(reference.find("strong")) if reference is not None else ""
        cards.append({
            "id": found.group(1),
            "title": title,
            "location": _text(card.select_one(".job-card__location strong")),   # (the block also holds an icon's name)
            "reference": value[len(label):].strip() if label and value.startswith(label) else value,
        })
    return total, cards


def _load(text: str):
    try:
        return json.loads(text, strict=False)
    except ValueError:
        return None


def _place(node: dict) -> str:
    """"Locality, Region, CC" of a JobPosting's ``jobLocation`` (the parts it has)."""
    place = node.get("jobLocation")
    place = place[0] if isinstance(place, list) and place else place
    address = place.get("address") if isinstance(place, dict) else None
    if not isinstance(address, dict):
        return ""
    keys = ("addressLocality", "addressRegion", "addressCountry")
    return ", ".join(p for p in (strip_html(str(address.get(k) or "")) for k in keys) if p)


def parse_ad(html: str) -> dict | None:
    """``{description, posted_at, location, organization}`` from an ad page's JobPosting JSON-LD; ``None`` when it
    has none. Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup.find_all("script", type=re.compile(r"ld(\+|&#x2B;|&#43;)json", re.IGNORECASE)):
        data = _load(tag.string or tag.get_text())
        for node in data if isinstance(data, list) else [data]:
            if not isinstance(node, dict) or node.get("@type") != "JobPosting":
                continue
            organization = node.get("hiringOrganization")
            posted = parse_iso_date(node.get("datePosted"))
            return {
                "description": strip_html(str(node.get("description") or "")),
                "posted_at": posted.replace(tzinfo=timezone.utc) if posted is not None and posted.tzinfo is None else posted,
                "location": _place(node),
                "organization": strip_html(str(organization.get("name") or "")) if isinstance(organization, dict) else "",
            }
    return None


def _to_posting(card: dict, ad: dict | None, base: str, label: str, name: str, scraped_at: datetime) -> dict:
    platform_id = f"{label}-{card['id']}"
    url = f"{base}/Job/JobDetail?JobId={card['id']}"
    ad = ad or {}
    posting = JobPosting(
        id=make_job_id(_SITE, platform_id),
        title=card["title"],
        company=name or ad.get("organization") or label,
        location=ad.get("location") or card["location"],
        url=url,
        description=ad.get("description") or "",
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=ad.get("posted_at"),
        apply_type="external",
        apply_url=url,
    )
    return posting.model_dump(mode="json")


def _status(exc: Exception) -> int | None:
    return getattr(getattr(exc, "response", None), "status_code", None)


# --- network ---

def _cards_of(session: PoliteSession, base: str) -> list[dict]:
    """Every card of a tenant's list, page after page until the total is reached (or a page adds nothing new).
    Raises on an HTTP error (a refusal is recorded as pushback first) or on a page that is no job list."""
    cards: list[dict] = []
    seen: set[str] = set()
    skip = 0
    for _ in range(_MAX_PAGES):
        try:
            text = session.get(_list_url(base, skip)).text
        except (requests.RequestException, RobotsBlocked) as exc:
            if _status(exc) in _PUSHBACK:
                record_pushback(_SITE)
            raise
        total, page = parse_cards(text)
        fresh = [c for c in page if c["id"] not in seen]
        seen.update(c["id"] for c in fresh)
        cards += fresh
        skip += len(page)
        if not fresh or skip >= total:
            break
    return cards


def _tenant_postings(session: PoliteSession, entry: str, scraped_at: datetime, known_ids: frozenset[str],
                     name: str) -> list[dict]:
    """One tenant's postings: its list, then the ad page of each ad not in *known_ids*. Raises when the list cannot be
    read; a refusal on an ad page is recorded as pushback and ends the tenant."""
    target = _target(entry)
    if target is None:
        raise ValueError("not a Jobtrain tenant")
    base, label = target
    cards = [c for c in _cards_of(session, base) if f"{label}-{c['id']}" not in known_ids]
    out: list[dict] = []
    for n, card in enumerate(cards, 1):
        report("detail", n, len(cards))
        try:
            ad = parse_ad(session.get(f"{base}/Job/JobDetail?JobId={card['id']}").text)
        except (requests.RequestException, RobotsBlocked) as exc:
            if _status(exc) in _PUSHBACK:
                record_pushback(_SITE)
                record_entry_error(_SITE, entry, f"{entry!r} refused job {card['id']} ({_status(exc)}); stopped", blocked=True)
                break
            record_error(_SITE, f"error fetching job {card['id']} of {entry!r}: {exc}")
            continue
        if ad is None:
            record_error(_SITE, f"job {card['id']} of {entry!r} has no ad data")
            continue
        out.append(_to_posting(card, ad, base, label, name, scraped_at))
    return out


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Every open ad of each configured Jobtrain career site."""
    entries = [e for e in config.get(_KEY) or [] if e.strip()]

    def fetch(session, entry, scraped_at):
        return _tenant_postings(session, entry, scraped_at, known_ids, followed_name(config, _KEY, entry, ""))

    return keep_local(scrape_feeds(_SITE, entries, fetch, group=lambda e: host_of(alive_url(e) or e),
                                   max_workers=workers(config), headers=_HEADERS), config, _SITE)


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the first tenant's first list page (one request). ``None`` when none is set.
    The list carries no text, so a posting here has the title, place and link only."""
    entries = [e for e in config.get(_KEY) or [] if e.strip()]
    target = _target(entries[0]) if entries else None
    if target is None:
        return None
    base, label = target
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

    def fetch() -> str:
        return session.get(_list_url(base, 0)).text

    def parse(text: str):
        try:
            _total, cards = parse_cards(text)
        except ValueError as exc:
            return [], False, str(exc)
        now = datetime.now(timezone.utc)
        return [_to_posting(c, None, base, label, "", now) for c in cards], True, ""

    return run_probe(fetch, parse, "html")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

def is_shared_host(host: str) -> bool:
    """Whether *host* is the vendor's own (a link there with no tenant is no employer's career site)."""
    return host in (_SHARED, _VENDOR)


def detect_url(url: str) -> Detection | None:
    """A link on ``www.jobtrain.co.uk/<tenant>/...``, and the tenant it names."""
    host, path, _query = parts(url.strip())
    if host != _SHARED:
        return None
    target = _target(url)
    return Detection(_SITE, target[1], f"Jobtrain tenant {target[1]} on {_SHARED}") if target else None


def detect_cname(host: str, target: str, where: str) -> Detection | None:
    """A career host that is a CNAME for a host of the vendor's (``jobs-crisis.jobtrain.co.uk``): the host is the
    tenant's own, served at its root."""
    target = target.rstrip(".").lower()
    if target == _SHARED or not target.endswith("." + _VENDOR) or _target(host) is None:
        return None
    return Detection(_SITE, host.lower(), where)


_BASE_PATH = re.compile(r"""var\s+SITE_BASE_PATH\s*=\s*['"]([^'"]*)['"]""")
_CLIENT_NAME = re.compile(r"""var\s+Site_Client_Name\s*=\s*['"]([^'"]+)['"]""")


def detect_html(html: str, url: str) -> Detection | None:
    """A page of a Jobtrain career site: every page writes ``var SITE_BASE_PATH='/<tenant>/'`` (``'/'`` on a tenant's own
    host) and ``var Site_Client_Name='<tenant>'``."""
    base_path, client = _BASE_PATH.search(html or ""), _CLIENT_NAME.search(html or "")
    if base_path is None or client is None:
        return None
    segment = base_path.group(1).strip("/").lower()
    entry = segment or urlparse(url if "://" in url else f"https://{url}").netloc.lower().split(":")[0]
    if _target(entry) is None:
        return None
    return Detection(_SITE, entry, f"{url} is a Jobtrain career site ({client.group(1)})")
