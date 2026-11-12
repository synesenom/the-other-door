#!/usr/bin/env python3
"""Scraper for Eploy's public RSS data feed (issue #603).

Eploy (eploy.com, a UK applicant tracking system) hosts each customer's careers site as an ASP.NET application:
on ``<name>web.eploy.net`` (M Group, Vitality, Cardiff University) or, once live, on the employer's own domain
(``portal.careers.turing.ac.uk``). The job list at ``/vacancies/vacancy-search-results.aspx`` pages by an ASP.NET
postback (view state, no URL for page 2), but the platform documents and serves a feed of its own, logged out:

  GET https://<host>/feeds/datafeed.ashx
      RSS 2.0, every open ad of the site in one answer (no paging): ``<item>`` with ``title``, ``link``
      (``.../vacancies/<id>/<slug>.html``), ``pubDate`` (midnight, the day it was posted), ``guid`` and a
      ``description`` that is entity-encoded HTML: a ``<ul>`` of the ad's fields (``<li><b>Location:</b> - London</li>``,
      the salary, the contract, ``Additional Locations``) whose last item, "About The Role" (or "Job Description"),
      is the ad's whole text. The channel title (``Vitality - Vacancies``) names the employer. The feed takes
      Eploy's documented filters; ``RecordLimit=5`` caps it (the probe's request: M Group's whole feed is 6 MB).
  Unknown host: 404 plain text.

The ad page is not opened: the feed holds its text (and its JSON-LD adds nothing), and applying wants a candidate
account, which door never uses.

Configured by ``eploy_hosts``: the site's host (``vitalityweb.eploy.net``, ``portal.careers.turing.ac.uk``) or any
link on it. ``follow`` detects an ``eploy.net`` host from a link (``detect_url``) and a custom domain from its page
(``detect_html``: the "Powered by Eploy" footer link and the ``/vacancies/vacancy-search`` pages).

Terms: https://www.eploy.com/about-eploy/security-compliance/terms-of-use/ (checked 2026-11-04) is the vendor's
website terms; it has no clause on automated access, scraping or copying, and each customer's ads are theirs
to publish, here through the feed Eploy documents for job boards
(https://intercom.help/eploy-support/en/articles/14485302-eploy-datafeed-and-search-handler). robots.txt on an
``eploy.net`` host names only a sitemap; custom domains vary (it does not gate requests, ``http_client.OBEY_ROBOTS``).
"""

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from door.scrapers.sdk import (
    Detection, JobPosting, NOT_ACCOUNTS, PROBE_TIMEOUT_S, PoliteSession, ProbeResult, followed_name, keep_local,
    make_job_id, parts, host_of, run_probe, scrape_feeds, strip_html, tenant_platform_id, workers,
)

# The platform's own domains: a host on one is a customer's, never the employer's name.
PLATFORM_DOMAINS = ("eploy.net",)

_SITE = "eploy"
_SUFFIX = ".eploy.net"
_NOT_HOSTS = NOT_ACCOUNTS | {"eploy", "support", "careers", "help", "docs", "static"}
_JOB_ID = re.compile(r"/vacancies/(\d+)/", re.IGNORECASE)
_CHANNEL = re.compile(r"\s+-\s+Vacancies\s*$", re.IGNORECASE)
_FOOTER = re.compile(r"""href=['"]https?://(?:www\.)?eploy\.(?:co\.uk|com)/?['"]""", re.IGNORECASE)
_SEARCH_PAGES = re.compile(r"/vacancies/vacancy-search", re.IGNORECASE)
_PLACE_FIELDS = ("location", "additional locations")


def _host(entry: str) -> str:
    """The host of an ``eploy_hosts`` entry: a host or a link on it, lowercased. Pure."""
    entry = entry.strip().lower()
    return (parts(entry)[0] if "://" in entry else entry.split("/")[0]).strip()


def datafeed_url(entry: str, limit: int | None = None) -> str:
    """The host's RSS data feed (every open ad; ``limit`` caps it with Eploy's ``RecordLimit``). Pure."""
    url = f"https://{_host(entry)}/feeds/datafeed.ashx"
    return f"{url}?RecordLimit={limit}" if limit else url


def _job_id(url: str) -> str:
    """The vacancy number of an ad link (``.../vacancies/21883/head-of-events.html``), "" for any other link. Pure."""
    match = _JOB_ID.search(url or "")
    return match.group(1) if match else ""


def _channel_name(title: str) -> str:
    """The employer a channel title names (``Vitality - Vacancies`` → ``Vitality``). Pure."""
    return _CHANNEL.sub("", (title or "").strip()).strip()


def _places(description: str) -> str:
    """The ad's places, ``Location`` then ``Additional Locations`` (comma-separated in the feed), joined by ``, ``
    ("" when the description names none). Pure."""
    found: dict[str, list[str]] = {}
    ul = BeautifulSoup(description or "", "html.parser").find("ul")
    for li in (ul.find_all("li", recursive=False) if ul is not None else []):
        label = li.find("b", recursive=False)
        name = label.get_text(" ", strip=True).strip(": ").lower() if label is not None else ""
        if name in _PLACE_FIELDS:
            label.extract()
            text = li.get_text(" ", strip=True).lstrip("- ").strip()
            found[name] = [p.strip() for p in text.split(",") if p.strip()]
    return ", ".join(found.get("location", []) + found.get("additional locations", []))


def parse_feed(xml_text: str) -> tuple[str, list[dict]]:
    """``(employer name, ads)`` of a host's RSS feed; each ad ``{id, title, url, location, description, posted_at}``.
    Raises ``ValueError`` when the text is no RSS feed (an HTML error page, a block page). Pure."""
    try:
        root = ElementTree.fromstring((xml_text or "").encode("utf-8"))
    except ElementTree.ParseError as exc:
        raise ValueError(f"not an RSS feed: {exc}") from exc
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise ValueError("no RSS channel in Eploy's answer")
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
        description = item.findtext("description") or ""
        ads.append({
            "id": job_id,
            "title": (item.findtext("title") or "").strip(),
            "url": url,
            "location": _places(description),
            "description": strip_html(description),
            "posted_at": posted,
        })
    return _channel_name(channel.findtext("title") or ""), ads


def _to_posting(ad: dict, host: str, scraped_at: datetime, name: str = "") -> dict:
    platform_id = tenant_platform_id(f"https://{host}", ad["id"])
    posting = JobPosting(
        id=make_job_id(_SITE, platform_id),
        title=ad["title"],
        company=name or host,
        location=ad["location"],
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


def _get(session: PoliteSession, url: str) -> str:
    """The feed's text, decoded as UTF-8 whatever the content type says (a ``text/xml`` answer without a charset
    would otherwise be read as Latin-1, and its byte-order mark would break the parse)."""
    return session.get(url, headers={"Accept": "application/rss+xml"}).content.decode("utf-8-sig", errors="replace")


def _host_postings(session: PoliteSession, entry: str, scraped_at: datetime, name: str = "") -> list[dict]:
    """Every open ad of one site, labelled with the followed *name* when given. Raises when the feed cannot be read."""
    host = _host(entry)
    channel, ads = parse_feed(_get(session, datafeed_url(host)))
    return [_to_posting(ad, host, scraped_at, name or channel) for ad in ads]


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Every open ad of each configured Eploy site. The feed holds the ads' text, so a known ad saves no
    request and *known_ids* is not needed."""
    entries = [e.strip() for e in config.get("eploy_hosts") or [] if e.strip()]

    def fetch(session, entry, scraped_at):
        return _host_postings(session, entry, scraped_at, followed_name(config, "eploy_hosts", entry))

    return keep_local(scrape_feeds(_SITE, entries, fetch, label=_host, group=lambda e: host_of(f"https://{_host(e)}"),
                                   max_workers=workers(config)), config, _SITE)


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the first five ads of the first configured host's feed (one request).
    ``None`` when none is set."""
    entries = [e for e in config.get("eploy_hosts") or [] if e.strip()]
    if not entries:
        return None
    host = _host(entries[0])
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0)

    def fetch() -> str:
        return _get(session, datafeed_url(host, limit=5))

    def parse(text: str):
        try:
            channel, ads = parse_feed(text)
        except ValueError as exc:
            return [], False, str(exc)
        scraped_at = datetime.now(timezone.utc)
        return [_to_posting(ad, host, scraped_at, channel) for ad in ads], True, ""

    return run_probe(fetch, parse, "xml")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

def detect_url(url: str) -> Detection | None:
    """A link on an Eploy-hosted site (``<name>web.eploy.net``) and the host it names."""
    host, _path, _query = parts(url.strip())
    label = host[: -len(_SUFFIX)] if host.endswith(_SUFFIX) else ""
    if label and "." not in label and label not in _NOT_HOSTS:
        return Detection("eploy", host, f"Eploy site {host}")
    return None


def detect_html(html: str, url: str) -> Detection | None:
    """A careers page on a customer's own domain: Eploy's "Powered by" footer link beside its ``/vacancies/vacancy-search``
    pages. The entry is the host of *url*."""
    host = parts(url.strip())[0]
    if host and _FOOTER.search(html or "") and _SEARCH_PAGES.search(html or ""):
        return Detection("eploy", host, f"{host} is an Eploy careers site (its footer and vacancy pages)")
    return None


def feed_url(entry: str) -> str | None:
    """None: the feed is RSS, not the JSON list the confirmation reads; the host's shape (or `detect_html`'s two
    signatures) vouches for it, and `alive_url` drops a host that does not exist."""
    return None


def alive_url(entry: str) -> str:
    """The first read of a site's feed: an unknown host answers 404, which `companies add` reports."""
    return datafeed_url(entry)
