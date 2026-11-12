#!/usr/bin/env python3
"""Scraper for Talentech HR-Manager's public job feed (issue #228).

HR-Manager runs the job pages of the Danish state (Statens Rekrutteringsløsning),
the regions, many municipalities and universities, and a good many companies.
Each customer has a public feed, made to be embedded on other sites (hence the
``JobPortal`` name and its RSS variant), read here without a login:

  GET https://api.hr-manager.net/JobPortal.svc/<alias>/PositionList/json/
      ?take=<n>&skip=<offset>&incads=true
      → ``{"CustomerName", "TransactionStatus": {"StatusCode": 0, ...},
      "Items": [...], "PositionCountCustomer": N, ...}``

Configured by ``hr_manager_aliases``: each customer's alias, the ``customer=``
of its job-agent link or the alias in its feed URL (``regionh``, ``kkdk``,
``statensrekrutteringsloesning_tr``). An unknown alias answers HTTP 400.

Items carry contact people (names, e-mails, phone numbers); only the fields a
posting needs are read, nothing else is kept.

Terms: https://talentech.com/legal — nothing on its public feeds, which are made
to be embedded on other sites. No robots.txt (allowed).
"""

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests

from door.scrapers.sdk import (
    FEED_DELAY, JobPosting, PoliteSession, PROBE_TIMEOUT_S, ProbeResult, log_keyword_results, make_job_id,
    record_entry_error, record_error, report, run_probe, strip_html, tracked,
)
from door.scrapers.sdk import keep_local
from door.scrapers.sdk import Detection, RobotsBlocked, career_links, parts, slug_candidates

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("hr-manager.net", "talentech.com")

_SITE = "hr_manager"
_FEED_URL = "https://api.hr-manager.net/JobPortal.svc/{alias}/PositionList/json/"
_PAGE_SIZE = 100
_MAX_PAGES = 30
_HEADERS = {"Accept": "application/json"}

# Feeds that serve several employers at once: {alias: (name that says what the feed is, customer number)}.
# The employer list follows such a feed once, under that name (issue #308).
SHARED = {"statensrekrutteringsloesning_tr": ("Statens Rekrutteringsløsning", "3010")}


def shared_name(alias: str) -> str | None:
    """The name of the shared feed *alias*, or None when the alias is one employer's own."""
    entry = SHARED.get((alias or "").lower())
    return entry[0] if entry else None


def shared_alias_for_cid(cid: str | None) -> str | None:
    """The alias of the shared feed whose customer number is *cid*, else None."""
    return next((a for a, (_, c) in SHARED.items() if c == cid), None) if cid else None

_DOTNET_DATE = re.compile(r"/Date\((-?\d+)([+-]\d{4})?\)/")
_INVISIBLE = re.compile(r"[​-‏⁠﻿]")
# The state's recruitment service files each ad under "§ <n> <ministry>", then
# the agency that is hiring.
_STATE_SECTION = re.compile(r"^§\s*\d+")


def _parse_dotnet_date(raw) -> datetime | None:
    """A WCF ``/Date(<ms><±hhmm>)/`` as an aware datetime; None for anything else,
    including the year-1 placeholder the feed uses for "no date". Pure."""
    if not isinstance(raw, str):
        return None
    match = _DOTNET_DATE.fullmatch(raw.strip())
    if not match or int(match.group(1)) < 0:
        return None
    offset = match.group(2) or "+0000"
    sign = -1 if offset[0] == "-" else 1
    tz = timezone(sign * timedelta(hours=int(offset[1:3]), minutes=int(offset[3:5])))
    return datetime.fromtimestamp(int(match.group(1)) / 1000, tz=tz)


def _clean(text) -> str:
    return re.sub(r"\s+", " ", _INVISIBLE.sub("", str(text or ""))).strip()


def _tree_chain(tree: dict | None) -> list[dict]:
    """The department tree's single path, root first."""
    chain = []
    while tree:
        chain.append(tree)
        tree = (tree.get("SubItems") or [None])[0]
    return chain


def _location_text(item: dict) -> str:
    """The department's city, else the deepest city in its tree, else the position's location. Pure."""
    city = _clean((item.get("Department") or {}).get("City"))
    if city:
        return city
    for node in reversed(_tree_chain(item.get("DepartmentTree"))):
        if _clean(node.get("City")):
            return _clean(node.get("City"))
    return _clean((item.get("PositionLocation") or {}).get("Name"))


def _company(item: dict, customer: str) -> str:
    """The employer: the customer, except
    - the state's recruitment service, where the agency under the ministry section is
      ("§ 29 KEFM …" → "Energistyrelsen");
    - a customer whose tree has a grouping level without a site between the root and its
      institutions (Region Hovedstaden: root → "Direktørområde 1" → "Herlev og Gentofte
      Hospital"): the first node at least two levels down that has a City. Wards and
      departments below it have none (and a node directly under the root is not looked
      at: Region Syddanmark's "Regionshuset", BEC's numbered units). Pure."""
    chain = _tree_chain(item.get("DepartmentTree"))
    names = [_clean(n.get("Name")) for n in chain]
    for i, name in enumerate(names[:-1]):
        if _STATE_SECTION.match(name):
            return names[i + 1]
    if chain and _clean(chain[0].get("City")):
        for node in chain[2:]:
            if _clean(node.get("City")) and _clean(node.get("Name")):
                return _clean(node.get("Name"))
    return _clean(customer)


def _to_posting(item: dict, alias: str, customer: str, scraped_at: datetime) -> dict:
    title = _clean(item.get("Name"))
    company = _company(item, customer) or alias
    platform_id = f"{alias}-{item.get('Id')}"
    url = item.get("AdvertisementUrl") or item.get("AdvertisementUrlSecure") or ""
    ad = next((a for a in item.get("Advertisements") or [] if a), {})
    # The ad's body; a position posted without an ad has none, and `scrape`
    # drops it as having no description.
    body = ad.get("Content") or ad.get("Introduction") or ad.get("Description") or item.get("ShortDescription") or ""
    posting = JobPosting(
        id=make_job_id(_SITE, platform_id),
        title=title,
        company=company,
        location=_location_text(item),
        url=url,
        description=strip_html(body),
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=_parse_dotnet_date(item.get("Published")),
        apply_type="external",
        apply_url=url,
    )
    return posting.model_dump(mode="json")


def _page(session: PoliteSession, alias: str, skip: int, take: int) -> dict:
    """One feed page; raises on HTTP errors and on a failed ``TransactionStatus``."""
    data = session.get(_FEED_URL.format(alias=alias), headers=_HEADERS,
                       params={"take": take, "skip": skip, "incads": "true"}).json()
    status = data.get("TransactionStatus") or {}
    if status.get("StatusCode", 0) != 0:
        raise ValueError(status.get("Description") or "the feed reported a failure")
    return data


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Every open position of each configured HR-Manager customer."""
    aliases: list[str] = [a.strip().lower() for a in config.get("hr_manager_aliases") or [] if a.strip()]
    if not aliases:
        return []
    scraped_at = datetime.now(timezone.utc)
    session = PoliteSession(min_delay=FEED_DELAY[0], max_delay=FEED_DELAY[1], timeout=30, headers=_HEADERS)
    seen: set[str] = set()
    postings: list[dict] = []
    for alias in tracked(aliases):
        alias_postings: list[dict] = []
        try:
            for page in range(_MAX_PAGES):
                data = _page(session, alias, page * _PAGE_SIZE, _PAGE_SIZE)
                items = data.get("Items") or []
                customer = data.get("CustomerName") or alias
                for item in items:
                    platform_id = f"{alias}-{item.get('Id')}"
                    if item.get("Id") is None or platform_id in seen:
                        continue
                    seen.add(platform_id)
                    alias_postings.append(_to_posting(item, alias, customer, scraped_at))
                if len(items) < _PAGE_SIZE:
                    break
        except Exception as exc:
            report(f"error fetching {alias!r}: {exc}")
            record_entry_error(_SITE, alias, f"error fetching {alias!r}: {exc}")
        alias_postings = keep_local(alias_postings, config, _SITE)
        log_keyword_results(_SITE, alias, alias_postings)
        postings.extend(alias_postings)
    return postings


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: page 1 of the first alias. ``None`` when none is set."""
    aliases = [a.strip().lower() for a in config.get("hr_manager_aliases") or [] if a.strip()]
    if not aliases:
        return None
    alias = aliases[0]
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

    def fetch() -> str:
        return session.get(_FEED_URL.format(alias=alias), headers=_HEADERS,
                           params={"take": _PAGE_SIZE, "skip": 0, "incads": "true"}).text

    def parse(text: str):
        data = json.loads(text)
        items = data.get("Items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return [], False, "no `Items` list in the HR-Manager feed"
        scraped_at = datetime.now(timezone.utc)
        customer = data.get("CustomerName") or alias
        return [_to_posting(i, alias, customer, scraped_at) for i in items if isinstance(i, dict) and i.get("Id")], True, ""

    return run_probe(fetch, parse, "json")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

def detect_url(url: str) -> Detection | None:
    """An HR-Manager feed or job-agent link and the customer alias it names; an application link
    (``cid=``) names the customer by number only, so it comes back without an entry."""
    host, path, query = parts(url.strip())
    if host == "api.hr-manager.net" and len(path) >= 2 and path[0].lower() == "jobportal.svc":
        return Detection("hr_manager", path[1].lower(), f"HR-Manager feed {url}")
    if host.endswith("hr-manager.net"):
        if query.get("customer"):
            return Detection("hr_manager", query["customer"].lower(), f"HR-Manager link {url}")
        if query.get("cid"):
            return Detection("hr_manager", None, f"HR-Manager customer {query['cid']} ({url}): the link names no alias; "
                                                 "find `customer=` in the employer's job-agent link")
    return None


def feed_url(entry: str) -> str | None:
    """None: an alias in a link is taken as it is (the name and ad-page lookups below confirm theirs)."""
    return None


def alive_url(entry: str) -> str | None:
    """The feed whose 4xx says the alias no longer exists (a customer with no open job answers 200 with no
    items, so an empty list is no sign): `commands.companies._dead_feed` reads it before following (#435)."""
    return _FEED_URL.format(alias=entry.strip().lower()) + "?take=1&skip=0"


def hr_manager_cid(url: str) -> str | None:
    """The ``cid=`` customer number of an HR-Manager link, else None."""
    if "hr-manager.net" not in url.lower():
        return None
    return parts(url)[2].get("cid") or None


def hr_manager_item_cid(item: dict) -> str | None:
    """The customer number an HR-Manager feed position's ``AdvertisementUrl`` carries, else None."""
    return hr_manager_cid(str((item or {}).get("AdvertisementUrl") or ""))


_CUSTOMER_LINK = re.compile(r"""hr-manager\.net/[^\s"'<>]*?[?&;]customer=([A-Za-z0-9_.\-]+)""", re.IGNORECASE)


def hr_manager_alias_from_html(html: str) -> str | None:
    """The alias an HR-Manager ad page names in a ``customer=`` link (job list, job agent), else None."""
    match = _CUSTOMER_LINK.search((html or "").replace("&amp;", "&"))
    return match.group(1).lower() if match else None


def detect_html(html: str, url: str) -> Detection | None:
    """The customer alias a page names in a ``customer=`` link to HR-Manager (a job agent or login link,
    often written ``//delta.hr-manager.net/...`` with no scheme, which the dispatcher's link scan skips): a
    university's vacancy list links its ads by customer number only (#431)."""
    alias = hr_manager_alias_from_html(html)
    return Detection("hr_manager", alias, f"HR-Manager customer link on {url}") if alias else None


def hr_manager_ad_page_url(url: str) -> str | None:
    """The ad page to read for a ``cid=`` link, without ``SkipAdvertisement`` (robots.txt disallows
    that variant: it is never requested); None for a link that is not such an ad page."""
    parsed = urlparse(url.strip())
    if parsed.netloc.lower() != "candidate.hr-manager.net" or parsed.path.lower() != "/applicationinit.aspx":
        return None
    pairs = [p for p in parsed.query.split("&") if p and p.split("=")[0].lower() != "skipadvertisement"]
    if not any(p.split("=")[0].lower() == "cid" for p in pairs):
        return None
    return f"https://candidate.hr-manager.net/ApplicationInit.aspx?{'&'.join(pairs)}"


# --- the customer behind an application link or a company name: confirmed by the feed itself ---

def feed_items(session, alias: str, take: int = 1) -> list:
    """The positions of the HR-Manager feed of *alias* (``StatusCode`` 0 only); empty when it lists none."""
    try:
        data = session.get(_FEED_URL.format(alias=alias), params={"take": take, "incads": "true"},
                           headers={"Accept": "application/json"}).json()
    except (requests.RequestException, RobotsBlocked, ValueError):
        return []
    if not isinstance(data, dict) or (data.get("TransactionStatus") or {}).get("StatusCode", 0) != 0:
        return []
    return [i for i in data.get("Items") or [] if isinstance(i, dict)]


def feed_has_cid(session, alias: str, cid: str | None) -> bool:
    """Whether *alias*'s feed lists jobs, and (with a *cid*) that they are customer *cid*'s: a feed whose
    jobs carry another customer number is another employer's."""
    items = feed_items(session, alias)
    if not items:
        return False
    cids = {c for c in (hr_manager_item_cid(i) for i in items) if c}
    return cid is None or not cids or cid in cids


def alias_by_name(session, name: str, cid: str | None = None, confirm=None) -> Detection | None:
    """The HR-Manager feed whose alias is one of the name's likely slugs and lists jobs; with a *cid*
    those jobs must be that customer's, else (with *confirm*) they must fit what was queued."""
    bare = re.sub(r"\.(com|dk|net|org)$", "", name.strip(), flags=re.IGNORECASE)
    for slug in dict.fromkeys([*slug_candidates(name), *slug_candidates(bare)]):
        items = feed_items(session, slug, take=200 if cid is None and confirm else 1)
        if not items:
            continue
        if cid is not None:
            cids = {c for c in (hr_manager_item_cid(i) for i in items) if c}
            if cids and cid not in cids:
                continue
            return Detection("hr_manager", slug, f"HR-Manager feed {slug} lists open jobs of customer {cid}")
        why = confirm(items) if confirm else None
        if confirm and why is None:
            continue
        return Detection("hr_manager", slug, f"HR-Manager feed {slug} lists open jobs" + (f"; {why}" if why else ""))
    return None


def alias_from_ad(session, link: str, detect_link) -> Detection | None:
    """The alias behind an HR-Manager ``cid=`` ad page, confirmed by its feed.

    Reads the page without ``SkipAdvertisement`` (robots.txt disallows it): its ``customer=`` link names the
    alias; failing that, the employer's careers pages it links to are followed to the alias with
    *detect_link* (the feed's jobs must carry the same customer number)."""
    url = hr_manager_ad_page_url(link)
    if url is None:
        return None
    cid = hr_manager_cid(link)
    try:
        html = session.get(url, headers={"Accept": "text/html"}).text
    except (requests.RequestException, RobotsBlocked):
        return None
    alias = hr_manager_alias_from_html(html)
    if alias and feed_has_cid(session, alias, cid):
        return Detection("hr_manager", alias, f"{url} links to the job list of {alias}; its feed lists open jobs")
    for page in career_links(html, url, limit=4):
        if "hr-manager" in page.lower() or "talentech" in page.lower():
            continue
        det = detect_link(session, page)
        if det is not None and det.platform == "hr_manager" and det.entry and feed_has_cid(session, det.entry, cid):
            return Detection("hr_manager", det.entry,
                             f"{url} links to {page}: {det.evidence}; its feed lists open jobs of customer {cid}")
    return None
