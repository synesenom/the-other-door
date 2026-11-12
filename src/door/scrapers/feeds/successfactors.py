#!/usr/bin/env python3
"""Scraper for SAP SuccessFactors "Recruiting Marketing" (RMK) career sites.

Each SuccessFactors customer runs their public careers site on its own
branded RMK hostname (e.g. ``careers.novonordisk.com``) rather than a shared
API host with a slug, unlike Greenhouse/Lever. Configured by
``successfactors_companies`` in the profile config — a list of bare RMK
hostnames, e.g. ``["careers.novonordisk.com"]``.

Data source used:
  GET https://<host>/sitemal.xml
      → an undocumented (and literally misspelled — "sitemal", not
      "sitemap") RSS 2.0 feed containing the *entire* job list for that
      RMK instance in a single request (no pagination needed). Each
      ``<item>`` has ``<title>``, ``<link>``, ``<description>`` (HTML in
      CDATA) and, when present, ``<pubDate>`` (RFC-822).

The keyword-scoped search endpoint (``/services/rss/job/``) is deliberately
*not* used: it is disallowed by ``robots.txt`` on the confirmed instance and
capped at 20 results per query with no pagination. ``/sitemal.xml`` sits at
the host root and is robots-allowed.

Terms: https://www.sap.com/about/legal/terms-of-use.html — the career site feed
is public. robots.txt disallows its services and apply paths, allows the feed.
"""

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

from door.scrapers.sdk import (
    career_site_words, generic_host_labels, word_pattern,
    FEED_DELAY, JobPosting, PoliteSession, PROBE_TIMEOUT_S, ProbeResult, host_of, log_keyword_results,
    make_job_id, tenant_platform_id, map_by_group, record_entry_error, record_error, report, run_probe, strip_html, workers, followed_name,
)
from door.scrapers.sdk import keep_local
from door.scrapers.sdk import Detection, parts

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("successfactors.com", "successfactors.eu", "jobs2web.com")

_HEADERS = {
    "Accept": "application/rss+xml, application/xml, text/xml",
}

_PLATFORM_ID_RE = re.compile(r"/(\d+)/?(?:\?.*)?$")


def _extract_platform_id(link: str | None) -> str:
    """Extract the trailing numeric job id from a SuccessFactors job *link*.

    Returns "" when *link* is missing or has no trailing numeric segment.
    """
    if not link:
        return ""
    m = _PLATFORM_ID_RE.search(link)
    return m.group(1) if m else ""


_SECOND_LEVEL = frozenset({"co", "com", "org", "net", "ac", "gov"})
_TITLE_PREFIX_RE = re.compile(
    r"^\s*(?:apply online for jobs at|available jobs at|open positions at|jobs at|careers at|career at|jobs with|careers with)\s+",
    re.IGNORECASE,
)
_TITLE_SUFFIX_RE = re.compile(
    r"\s*(?:[|:\-\u2013]\s*(?:sap successfactors|search jobs|jobs?|careers?)|\s(?:careers?|jobs?))\s*$",
    re.IGNORECASE,
)


def _company_from_host(host: str) -> str:
    """Name an employer from its RMK hostname: the registrable domain's label.

    Generic first labels (``jobs``, ``careers``, ...) are never the name:
    ``jobs.leo-pharma.com`` -> ``"Leo Pharma"``, ``careers.novonordisk.com``
    -> ``"Novonordisk"``. Returns "" for an empty host.
    """
    labels = [lbl for lbl in (host or "").lower().split(".") if lbl]
    if len(labels) >= 3 and labels[-2] in _SECOND_LEVEL:
        labels = labels[:-1]  # drop the "co" of "co.uk" so the tld pair counts as one
    if len(labels) >= 2:
        labels = labels[:-1]  # the tld
    labels = [lbl for lbl in labels if lbl not in generic_host_labels()] or labels
    name = labels[-1] if labels else ""
    return re.sub(r"[-_]+", " ", name).title()


def _channel_title(xml_text: str) -> str:
    """The feed's ``<channel><title>``, stripped; "" when absent or the XML is malformed."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return ""
    return (root.findtext("channel/title") or "").strip()


def _company_from_channel_title(title: str) -> str:
    """The employer named by a channel *title*, or "" when it names none.

    Strips boilerplate ("Available jobs at X", "Careers at X: search jobs",
    "X Careers | SAP SuccessFactors"); a title that is only boilerplate is "".
    """
    name = _TITLE_PREFIX_RE.sub("", title or "")
    for _ in range(3):
        name = _TITLE_SUFFIX_RE.sub("", name)
    name = name.strip()
    words = word_pattern(career_site_words())
    sep = r"(?:\s*[|:\u2013]\s*|\s+-\s+)"
    for _ in range(3):  # "Careers | Tryg.com", "LEO Pharma - Ledige stillinger"
        name = re.sub(rf"^{words}{sep}", "", name, flags=re.IGNORECASE)
        name = re.sub(rf"{sep}{words}$", "", name, flags=re.IGNORECASE).strip()
    mailbox = re.fullmatch(r"([\w.-]+)@([\w.-]+)", name)  # "careers@lundbeck"
    if mailbox and mailbox.group(1).lower() in generic_host_labels():
        name = mailbox.group(2)
        name = name.title() if name.islower() else name
    if re.fullmatch(r"[\w-]+\.[a-z]{2,6}", name, re.IGNORECASE):  # a bare domain: "Tryg.com"
        name = name.rsplit(".", 1)[0]
    if name.lower() in generic_host_labels() or name.lower() in {"search", "job search"}:
        return ""
    if re.fullmatch(words, name, re.IGNORECASE):
        return ""
    return name


_COUNTRY_TOKEN = re.compile(r",\s*[A-Z]{2}\s*(?:,|$)")


def _balanced_prefix(text: str) -> bool:
    """True when *text* never closes a parenthesis it did not open. Pure."""
    depth = 0
    for ch in text:
        depth += (ch == "(") - (ch == ")")
        if depth < 0:
            return False
    return True


def _location_from_suffix(suffix: str) -> str:
    """A readable location from a title's parenthesised suffix: ``"Bangkok, Bangkok, TH"`` ->
    ``"Bangkok, TH"``; a messy store-code form keeps only the country code. Pure."""
    parts = [p.strip() for p in suffix.split(",")]
    country = next(p for p in reversed(parts) if re.fullmatch(r"[A-Z]{2}", p))
    city = parts[0]
    if not city or city == country or re.search(r"[\d()_]", city):
        return country
    return f"{city}, {country}"


def _split_title_location(raw: str) -> tuple[str, str]:
    """Split ``"Head of X (Ballerup, DK)"`` into ``("Head of X", "Ballerup, DK")``.

    Conservative: only a final parenthesised group containing a ", XX" country
    token is a location; the feed truncates and unbalances it, so the group may
    hold stray parentheses. Anything else (``"Engineer (m/f/d)"``) is untouched. Pure.
    """
    raw = (raw or "").strip()
    if not raw.endswith(")"):
        return raw, ""
    for pos, ch in enumerate(raw):
        if ch != "(":
            continue
        head, inner = raw[:pos].rstrip(), raw[pos + 1:-1]
        if head and _balanced_prefix(head) and _balanced_prefix(inner) and _COUNTRY_TOKEN.search(inner):
            return head, _location_from_suffix(inner)
    return raw, ""


def _company_name(channel_title: str, host: str) -> str:
    """Employer name: the channel title when it names one, else the host's domain label."""
    return _company_from_channel_title(channel_title) or _company_from_host(host)


def _parse_pubdate(s: Any) -> datetime | None:
    """Parse an RFC-822 ``pubDate`` string to a datetime.

    Returns None when *s* is missing, empty, or unparseable.
    """
    if not isinstance(s, str) or not s:
        return None
    try:
        return parsedate_to_datetime(s)
    except (TypeError, ValueError):
        return None


def _parse_feed(xml_text: str) -> list[dict]:
    """Parse a ``sitemal.xml`` RSS feed into a list of raw item dicts.

    Each dict has ``title``, ``link``, ``description``, ``pub_date`` (the
    latter possibly None). Returns [] on malformed XML or a feed with no
    ``<item>`` elements.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    items = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = (item.findtext("description") or "").strip()
        pub_date = item.findtext("pubDate")
        pub_date = pub_date.strip() if pub_date else None
        location = (item.findtext("{*}location") or "").strip()
        items.append(
            {
                "title": title,
                "link": link,
                "description": description,
                "pub_date": pub_date,
                "location": location,
            }
        )
    return items


def _fetch_feed(session: PoliteSession, host: str) -> tuple[str, list[dict]]:
    """Fetch the ``sitemal.xml`` feed for *host*; return (employer name, parsed items).

    Raises on HTTP errors or if robots.txt disallows the path.
    """
    feed_url = f"https://{host}/sitemal.xml"
    resp = session.get(feed_url, headers=_HEADERS)
    return _company_name(_channel_title(resp.text), host), _parse_feed(resp.text)


def _feed_structure_ok(xml_text: str) -> bool:
    """True when *xml_text* is an RSS document with a ``<channel>`` (even an empty one). Pure."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return False
    return root.find(".//channel") is not None


def _folded_platform_id(link: str | None) -> str | None:
    """The link's numeric id with its host folded in (ids repeat across tenants)."""
    raw = _extract_platform_id(link)
    return tenant_platform_id(link or "", raw) if raw else None


def _to_posting(item: dict, company: str, platform_id: str, scraped_at: datetime) -> dict:
    """Map one parsed feed item to a JobPosting dict."""
    link = item.get("link") or ""
    title, title_location = _split_title_location(item.get("title") or "")
    posting = JobPosting(
        id=make_job_id("successfactors", platform_id),
        title=title,
        company=company,
        location=(item.get("location") or "").strip() or title_location,
        url=link,
        description=strip_html(item.get("description") or "", encoded=True),
        source="successfactors",
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=_parse_pubdate(item.get("pub_date")),
        apply_type="external",
        apply_url=link,
    )
    return posting.model_dump(mode="json")


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Return a list of JobPosting-compatible dicts from configured SuccessFactors hosts."""
    hosts: list[str] = config.get("successfactors_companies", [])
    if not hosts:
        return []

    scraped_at = datetime.now(timezone.utc)
    session = PoliteSession(min_delay=FEED_DELAY[0], max_delay=FEED_DELAY[1], timeout=30, headers=_HEADERS)

    def fetch(host: str):
        """One host's (employer name, items); ``None`` after a recorded error."""
        try:
            return _fetch_feed(session, host)
        except Exception as exc:
            report(f"error fetching {host!r}: {exc}")
            record_entry_error("successfactors", host, f"error fetching {host!r}: {exc}")
            return None

    # Hosts of different employers are fetched side by side; the rest below is in config order.
    fetched = map_by_group(hosts, host_of, fetch, workers(config))
    seen_ids: set[str] = set()
    postings: list[dict] = []

    for host, feed in zip(hosts, fetched):
        if feed is None:
            continue
        company, items = feed
        company = followed_name(config, "successfactors_companies", host, company)
        host_postings: list[dict] = []

        for item in items:
            link = item.get("link") or ""
            platform_id = _folded_platform_id(link)
            if not platform_id or platform_id in seen_ids:
                continue
            seen_ids.add(platform_id)

            host_postings.append(_to_posting(item, company, platform_id, scraped_at))

        host_postings = keep_local(host_postings, config, "successfactors")
        log_keyword_results("successfactors", host, host_postings)
        postings.extend(host_postings)

    return postings


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the first configured host. ``None`` when none is set."""
    hosts: list[str] = config.get("successfactors_companies", [])
    if not hosts:
        return None
    host = hosts[0]
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

    def fetch() -> str:
        return session.get(f"https://{host}/sitemal.xml", headers=_HEADERS).text

    def parse(text: str):
        if not _feed_structure_ok(text):
            return [], False, "the response is not an RSS feed with a <channel>"
        company = _company_name(_channel_title(text), host)
        scraped_at = datetime.now(timezone.utc)
        postings = []
        for item in _parse_feed(text):
            platform_id = _folded_platform_id(item.get("link"))
            if platform_id:
                postings.append(_to_posting(item, company, platform_id, scraped_at))
        return postings, True, ""

    return run_probe(fetch, parse, "xml")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

def is_shared_host(host: str) -> bool:
    """Whether *host* is a ``career<N>.successfactors`` host shared by many employers, whose ad pages
    hold nothing that leads to an employer's own list."""
    return re.fullmatch(r"career\d*\.successfactors\.(eu|com)", host) is not None


def detect_url(url: str) -> Detection | None:
    """A ``<company>.jobs2web.com`` career site (older ``career*.successfactors`` links name no job list)."""
    host, _path, _query = parts(url.strip())
    if host.endswith(".jobs2web.com"):
        return Detection("successfactors", host, f"SAP SuccessFactors career site {host}")
    return None

def feed_url(entry: str) -> str | None:
    """None: a link to the site names the account, no feed check is needed."""
    return None


def detect_cname(host: str, target: str, where: str) -> Detection | None:
    """A career host that is a CNAME for a ``jobs2web.com`` host."""
    return Detection("successfactors", host, where) if target.endswith(".jobs2web.com") else None


def detect_html(html: str, url: str) -> Detection | None:
    """A career site on the employer's own host that loads SuccessFactors' assets."""
    if "rmkcdn.successfactors.com" in html or "jobs2web" in html:
        return Detection("successfactors", urlparse(url).netloc.lower(), f"{url} is an SAP SuccessFactors career site")
    return None
