#!/usr/bin/env python3
"""Scraper for employers on Personio, the German HR and applicant-tracking system (issue #558).

Kind of site: an ATS whose customers (mostly small and mid-sized companies in Germany, France, the Nordics
and the Benelux) publish their ads on ``<account>.jobs.personio.com`` (or ``.personio.de``). Every career
page offers, without a key, login or cookie, one XML feed with all its open positions:

  GET https://<account>.jobs.personio.com/xml
      → ``<workzag-jobs>`` with one ``<position>`` per ad: ``id``, ``subcompany`` (the legal entity),
        ``office`` and ``additionalOffices/office``, ``department``, ``name`` (the title), ``jobDescriptions``
        (``jobDescription/name`` and ``value``, HTML in CDATA), ``employmentType``, ``seniority``,
        ``schedule``, ``createdAt`` (ISO 8601). No paging; the ad is at ``/job/<id>``. An account with no open
        ad answers an empty ``<workzag-jobs>``; an unknown one answers 404 with an HTML page. The feed has
        every ad in the account's default language; no language is asked for.

The feed holds each ad's whole text, so an ad page is never opened and *known_ids* saves no request.
Applying happens on the ad page (a form, no account).

Configured by ``personio_companies``: the account slug (``pno-group-europe``), or its host when it is on
``personio.de`` (``acme.jobs.personio.de``); a link on the host is read the same way. The feed does not name
the employer (``subcompany`` is a legal entity, often per country), so the followed name wins and the
``subcompany``, then the slug, are the fallbacks.

Terms: Personio's career pages have no terms of use for visitors; the only legal page there is the privacy
policy, https://www.personio.com/privacy-policy/ (nothing about reading ads), and the feed is what Personio
documents for job boards and career sites. Nothing bans scraping, bots or text-and-data mining.
robots.txt of ``<account>.jobs.personio.com`` is ``User-agent: *`` / ``Allow: /``. Checked 2026-11-01.
"""

import re
from datetime import datetime, timezone
from urllib.parse import urlparse
from xml.etree import ElementTree

import requests

from door.scrapers.sdk import (
    Detection, JobPosting, NOT_ACCOUNTS, PROBE_TIMEOUT_S, PoliteSession, ProbeResult, followed_name, host_of,
    keep_local, make_job_id, parse_iso_date, parts, record_pushback, run_probe, scrape_feeds, strip_html, workers,
)

# The platform's own domains: a host on one is a customer's, never the employer's name.
PLATFORM_DOMAINS = ("personio.com", "personio.de")

_SITE = "personio"
_HEADERS = {"Accept": "application/xml"}
_HOST = re.compile(r"^([a-z0-9][a-z0-9-]*)\.jobs\.personio\.(com|de)$")
_NOT_ACCOUNTS = NOT_ACCOUNTS | {"personio", "help", "support", "developer", "status"}


def _host(entry: str) -> str:
    """The career host of a ``personio_companies`` entry: a slug (``.com``), a host or a link. Pure."""
    entry = entry.strip().lower()
    if "." not in entry and "/" not in entry:
        return f"{entry}.jobs.personio.com"
    return parts(entry)[0] if "://" in entry else entry.split("/")[0]


def xml_url(entry: str) -> str:
    return f"https://{_host(entry)}/xml"


def _text(node, tag: str) -> str:
    return (node.findtext(tag) or "").strip()


def _location(position) -> str:
    """The additional offices (cities), then the main office (often the country), without repeats. Pure."""
    names = [(o.text or "").strip() for o in position.findall("additionalOffices/office")]
    names.append(_text(position, "office"))
    return ", ".join(dict.fromkeys(n for n in names if n))


def _description(position) -> str:
    blocks = (strip_html(d.findtext("value") or "") for d in position.findall("jobDescriptions/jobDescription"))
    return "\n\n".join(b for b in blocks if b)


def parse_feed(xml_text: str) -> list[dict]:
    """The ads of an account's XML feed: ``{id, title, subcompany, location, posted_at, description, employment}``
    each. Raises ``ValueError`` when the text is no Personio feed (an HTML 404 page, a block page). Pure."""
    try:
        root = ElementTree.fromstring((xml_text or "").encode("utf-8"))
    except ElementTree.ParseError as exc:
        raise ValueError(f"not a Personio feed: {exc}") from exc
    if root.tag != "workzag-jobs":
        raise ValueError("no `workzag-jobs` list in Personio's answer")
    ads = []
    for position in root.findall("position"):
        ad_id = _text(position, "id")
        if not ad_id:
            continue
        ads.append({
            "id": ad_id,
            "title": _text(position, "name"),
            "subcompany": _text(position, "subcompany"),
            "location": _location(position),
            "posted_at": parse_iso_date(_text(position, "createdAt")),
            "description": _description(position),
            "employment": " / ".join(p for p in (_text(position, t) for t in ("employmentType", "seniority", "schedule")) if p),
        })
    return ads


def _to_posting(ad: dict, host: str, scraped_at: datetime, name: str = "") -> dict:
    url = f"https://{host}/job/{ad['id']}"
    match = _HOST.match(host)
    posting = JobPosting(
        id=make_job_id(_SITE, ad["id"]),
        title=ad["title"],
        company=name or ad["subcompany"] or (match.group(1) if match else host),
        location=ad["location"],
        url=url,
        description=ad["description"],
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=ad["id"],
        posted_at=ad["posted_at"],
        apply_type="external",
        apply_url=url,
    )
    return posting.model_dump(mode="json")


def _get(session: PoliteSession, entry: str) -> str:
    try:
        return session.get(xml_url(entry), headers=_HEADERS).text
    except requests.HTTPError as exc:
        if getattr(exc.response, "status_code", None) in (403, 429):
            record_pushback(_SITE)
        raise


def _company_postings(session: PoliteSession, entry: str, scraped_at: datetime, name: str = "") -> list[dict]:
    """Every open ad of one account, labelled with the followed *name* when given. Raises when the feed cannot
    be read (a 429/403 is recorded as pushback first)."""
    host = _host(entry)
    return [_to_posting(ad, host, scraped_at, name) for ad in parse_feed(_get(session, entry))]


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Every open ad of each followed Personio account (``personio_companies``). The feed holds the ads' text,
    so a known ad saves no request."""
    entries = [e.strip() for e in config.get("personio_companies") or [] if e.strip()]

    def fetch(session, entry, scraped_at):
        return _company_postings(session, entry, scraped_at, followed_name(config, "personio_companies", entry))

    return keep_local(scrape_feeds(_SITE, entries, fetch, group=lambda e: host_of(f"https://{_host(e)}"),
                                   max_workers=workers(config), headers=_HEADERS), config, _SITE)


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the XML feed of the first account (one request). ``None`` when none is set."""
    entries = [e for e in config.get("personio_companies") or [] if e.strip()]
    if not entries:
        return None
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

    def fetch() -> str:
        return session.get(xml_url(entries[0]), headers=_HEADERS).text

    def parse(text: str):
        try:
            ads = parse_feed(text)
        except ValueError as exc:
            return [], False, str(exc)
        scraped_at = datetime.now(timezone.utc)
        return [_to_posting(ad, _host(entries[0]), scraped_at) for ad in ads], True, ""

    return run_probe(fetch, parse, "xml")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

def _entry(host: str) -> str | None:
    """The ``personio_companies`` entry of a career host: the slug on ``.com``, the whole host on ``.de``."""
    match = _HOST.match(host)
    if not match or match.group(1) in _NOT_ACCOUNTS:
        return None
    return match.group(1) if match.group(2) == "com" else host


def detect_url(url: str) -> Detection | None:
    """A link on a Personio career page (``<account>.jobs.personio.com|de``: an ad, the list) and the account."""
    host, _path, _query = parts(url.strip())
    entry = _entry(host)
    return Detection(_SITE, entry, f"Personio career page {host}") if entry else None


def feed_url(entry: str) -> str | None:
    """None: the feed is XML, not the JSON list the confirmation reads; the link's shape vouches for it and
    `alive_url` drops an account that does not exist."""
    return None


def alive_url(entry: str) -> str:
    """The first read of an account's feed: an unknown account answers 404, which `companies add` reports."""
    return xml_url(entry)


_PAGE_MARKER = re.compile(r"(?:https?:)?//([a-z0-9][a-z0-9-]*\.jobs\.personio\.(?:com|de))\b", re.IGNORECASE)


def detect_html(html: str, url: str) -> Detection | None:
    """A career site on the employer's own host that embeds or links its Personio page."""
    for match in _PAGE_MARKER.finditer(html or ""):
        entry = _entry(match.group(1).lower())
        if entry:
            return Detection(_SITE, entry, f"{urlparse(url).netloc.lower() or url} embeds the Personio page {match.group(1).lower()}")
    return None
