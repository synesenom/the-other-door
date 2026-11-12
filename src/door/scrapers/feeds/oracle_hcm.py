#!/usr/bin/env python3
"""Scraper for Oracle Cloud HCM's public candidate-experience feed (issue #438).

Every Oracle Cloud HCM career site (``https://<host>/hcmUI/CandidateExperience/<lang>/sites/<site>``) loads its
jobs from the REST resources the page itself calls, which need no login, key or token:

  GET https://<host>/hcmRestApi/resources/latest/recruitingCESites?onlyData=true
      → ``{"items": [{SiteNumber, SiteName, StatusCode: ORA_ACTIVE | ORA_INACTIVE}]}`` (the sites of the host)
  GET .../recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations
      &finder=findReqs;siteNumber=<site>,limit=<n>,offset=<k>,sortBy=POSTING_DATES_DESC
      → ``{"items": [{TotalJobsCount, requisitionList: [{Id, Title, PostedDate, PrimaryLocation,
      PrimaryLocationCountry, WorkplaceTypeCode, ShortDescriptionStr, secondaryLocations}]}]}``
  GET .../recruitingCEJobRequisitionDetails?onlyData=true&expand=all&finder=ById;Id="<id>",siteNumber=<site>
      → ``{"items": [{ExternalDescriptionStr (HTML), ExternalResponsibilitiesStr, ExternalQualificationsStr}]}``

The search is paged by ``limit``/``offset`` up to ``TotalJobsCount``; the description is read only for a posting
not seen before (``known_ids``). A job page is ``/hcmUI/CandidateExperience/en/sites/<site>/job/<Id>``.

An entry is ``<host>/<site>`` (``ejqi.fa.ocs.oraclecloud.eu/CX_1001``): a host serves several sites, and a shared
host several employers (the UN agencies' ``estm.fa.em2.oraclecloud.com``: ``CX_1`` is UNDP, ``CX_2003`` UNFPA), so
the followed employer's name comes from ``profile/companies.json`` (``followed_name``). A link into an inactive
site (an old career page) is resolved through the host's site list to the one active site (`resolve`).

Configured by ``oracle_hcm_companies``.

Terms: https://www.oracle.com/legal/terms.html (read 2026-10-30; the page carries no date) says "You agree not
to use any robot, spider, scraper or other automated means to access the Site or any Oracle accounts, computer
systems or networks without Oracle's express written permission." That page governs oracle.com; the candidate
experience is the customer's own career site, which Oracle hosts. The other door reads only what a visitor's browser
reads: the REST resources above, logged out, the same calls the career page makes, with no login and no
challenge passed. Commercial job-data services read exactly these resources. The other door's posture is the one in
LEGAL_DISCLAIMER.md: the user decides what to follow and carries the risk. The host serves no robots.txt (404).
"""

import json
from datetime import datetime, timezone
from urllib.parse import urlparse

from door.scrapers.sdk import (
    Detection, FEED_DELAY, JobPosting, PROBE_TIMEOUT_S, PoliteSession, ProbeResult, followed_name, keep_local, make_job_id,
    parse_iso_date, parts, record_error, report, run_probe, scrape_feeds, strip_html, tenant_platform_id, unfollowable,
)

TERMS_URL = "https://www.oracle.com/legal/terms.html"

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("oraclecloud.com", "oraclecloud.eu")

_SITE = "oracle_hcm"
_HEADERS = {"Accept": "application/json"}
_PAGE = 25            # requisitions per search request
_MAX_POSTINGS = 3000  # a safety stop for a runaway listing
_REST = "/hcmRestApi/resources/latest"
_WORKPLACE = {"ORA_REMOTE": "Remote"}  # (a "Hybrid" prefix would count as remote for the local-jobs rule)


def _entry(text: str) -> tuple[str, str] | None:
    """``(host, site)`` of an ``oracle_hcm_companies`` entry: ``<host>/<site>`` or a candidate-experience link
    into a site; ``None`` when it names no site. Pure."""
    text = text.strip()
    det = detect_url(text) if "://" in text or "hcmui" in text.lower() else None
    if det is not None and det.entry:
        text = det.entry
    host, _, site = text.partition("/")
    host, site = host.strip().lower(), site.strip("/")
    return (host, site) if "." in host and site and "/" not in site else None


def _search_url(host: str, site: str, *, offset: int, limit: int) -> str:
    finder = f"findReqs;siteNumber={site},limit={limit},offset={offset},sortBy=POSTING_DATES_DESC"
    return (f"https://{host}{_REST}/recruitingCEJobRequisitions?onlyData=true"
            f"&expand=requisitionList.secondaryLocations&finder={finder}")


def _detail_url(host: str, site: str, req_id: str) -> str:
    return (f"https://{host}{_REST}/recruitingCEJobRequisitionDetails?expand=all&onlyData=true"
            f'&finder=ById;Id="{req_id}",siteNumber={site}')


def _job_url(host: str, site: str, req_id: str) -> str:
    return f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{req_id}"


def _location_text(item: dict) -> str:
    """The primary place (with the country's code when it is a bare city) and the secondary ones joined by
    ``;``, led by ``Remote`` for a remote posting (hybrid and on-site ones are at their place). Pure."""
    primary = (item.get("PrimaryLocation") or "").strip()
    code = (item.get("PrimaryLocationCountry") or "").strip()
    if primary and code and "," not in primary:
        primary = f"{primary}, {code}"
    others = [(s.get("Name") or "").strip() for s in item.get("secondaryLocations") or [] if isinstance(s, dict)]
    places = "; ".join(dict.fromkeys(p for p in [primary, *others] if p))
    prefix = _WORKPLACE.get(item.get("WorkplaceTypeCode") or "", "")
    return f"{prefix}, {places}" if prefix and places else prefix or places


def _description(detail: dict) -> str:
    """The full text of a posting's detail: description, responsibilities and qualifications. Pure."""
    fields = ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")
    return "\n\n".join(t for t in (strip_html(detail.get(f) or "") for f in fields) if t)


def _company_name(host: str) -> str:
    return host.split(".")[0].replace("-", " ").title()


def _to_posting(item: dict, host: str, site: str, company: str, scraped_at: datetime) -> dict:
    url = _job_url(host, site, str(item.get("Id")))
    platform_id = tenant_platform_id(url, str(item.get("Id")))  # requisition numbers repeat across hosts
    posting = JobPosting(
        id=make_job_id(_SITE, platform_id),
        title=(item.get("Title") or "").strip(),
        company=company,
        location=_location_text(item),
        url=url,
        description=strip_html(item.get("ShortDescriptionStr") or ""),
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=parse_iso_date(item.get("PostedDate")),
        apply_type="external",
        apply_url=url,
    )
    return posting.model_dump(mode="json")


def _page(session: PoliteSession, host: str, site: str, offset: int, limit: int) -> tuple[list[dict], int]:
    """``(requisitions, total)`` of one search page. Raises on HTTP errors."""
    data = session.get(_search_url(host, site, offset=offset, limit=limit), headers=_HEADERS).json()
    return _requisitions(data), _total(data)


def _first(data) -> dict:
    items = data.get("items") if isinstance(data, dict) else None
    return items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}


def _requisitions(data) -> list[dict]:
    listed = _first(data).get("requisitionList")
    return [r for r in listed or [] if isinstance(r, dict) and r.get("Id")]


def _total(data) -> int:
    try:
        return int(_first(data).get("TotalJobsCount") or 0)
    except (TypeError, ValueError):
        return 0


def _site_postings(session: PoliteSession, config: dict, entry: str, scraped_at: datetime,
                   known_ids: frozenset[str]) -> list[dict]:
    """The new postings of one entry, local ones only, with their full description. Raises on HTTP errors."""
    target = _entry(entry)
    if target is None:
        raise ValueError(f"not an Oracle Cloud HCM site (expected <host>/<site>): {entry!r}")
    host, site = target
    name = followed_name(config, "oracle_hcm_companies", entry, _company_name(host))
    items: list[dict] = []
    offset, total = 0, 1
    while offset < min(total, _MAX_POSTINGS):
        page, total = _page(session, host, site, offset, _PAGE)
        if not page:
            break
        items.extend(page)
        offset += len(page)
    ids = {}   # platform id -> requisition number, for the detail request
    fresh = []
    for item in items:
        platform_id = tenant_platform_id(f"https://{host}", str(item["Id"]))
        if platform_id not in known_ids:
            ids[platform_id] = str(item["Id"])
            fresh.append(_to_posting(item, host, site, name, scraped_at))
    postings = keep_local(fresh, config, _SITE)  # before the detail requests: the others are never read
    for posting in postings:
        try:
            detail = _first(session.get(_detail_url(host, site, ids[posting["platform_id"]]), headers=_HEADERS).json())
        except Exception as exc:  # noqa: BLE001 - the list text stays when the detail cannot be read
            report(f"error fetching the detail of {posting['url']}: {exc}")
            continue
        text = _description(detail)
        if text:
            posting["description"] = text
    return postings


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Every open posting of each configured Oracle Cloud HCM career site (the new ones in full)."""
    entries = [e.strip() for e in config.get("oracle_hcm_companies") or [] if e.strip()]

    def fetch(session, entry, scraped_at):
        return _site_postings(session, config, entry, scraped_at, known_ids)

    def host(entry):
        target = _entry(entry)
        return target[0] if target else entry

    return scrape_feeds(_SITE, entries, fetch, key=lambda p: p["platform_id"], group=host,
                        max_workers=int(config.get("scrape_workers") or 1), headers=_HEADERS)


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: page 1 of the first configured site. ``None`` when none is set."""
    entries = [e for e in config.get("oracle_hcm_companies") or [] if e.strip()]
    target = _entry(entries[0]) if entries else None
    if target is None:
        return None
    host, site = target
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

    def fetch() -> str:
        return session.get(_search_url(host, site, offset=0, limit=_PAGE), headers=_HEADERS).text

    def parse(text: str):
        data = json.loads(text)
        if not isinstance(_first(data).get("requisitionList"), list):
            return [], False, "no `requisitionList` in the Oracle Cloud HCM job search"
        scraped_at = datetime.now(timezone.utc)
        return [_to_posting(r, host, site, _company_name(host), scraped_at) for r in _requisitions(data)], True, ""

    return run_probe(fetch, parse, "json")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

def detect_url(url: str) -> Detection | None:
    """An Oracle Cloud candidate-experience link (``.../hcmUI/CandidateExperience/<lang>/sites/<site>/...`` on
    an ``oraclecloud`` host): the host and the site it names; a link that names no site yet gives no entry
    (`resolve` takes the host's only active site)."""
    host, path, _query = parts(url.strip())
    if not (host.endswith(".oraclecloud.com") or host.endswith(".oraclecloud.eu")):
        return None
    lower = [p.lower() for p in path]
    if "hcmui" not in lower:
        return None
    site = path[lower.index("sites") + 1] if "sites" in lower and lower.index("sites") + 1 < len(path) else ""
    if site:
        return Detection(_SITE, f"{host}/{site}", f"Oracle Cloud HCM career site {host}, site {site}")
    return unfollowable(_SITE, host, "Oracle Cloud HCM, but the link names no career site", "cant_yet")


def feed_url(entry: str) -> str | None:
    """None: a link into a site names the entry; `resolve` and `alive_url` check it."""
    return None


def alive_url(entry: str) -> str | None:
    """The one-job search whose 4xx answer means the site no longer exists (read once by `companies add`)."""
    target = _entry(entry)
    return _search_url(*target[:1], target[1], offset=0, limit=1) if target else None


def _active_sites(session: PoliteSession, host: str) -> list[str] | None:
    """The site numbers of *host* that are active, or None when the list cannot be read."""
    try:
        data = session.get(f"https://{host}{_REST}/recruitingCESites?onlyData=true", headers=_HEADERS).json()
    except Exception:  # noqa: BLE001 - no list is no verdict
        return None
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return None
    return [s["SiteNumber"] for s in items if isinstance(s, dict) and s.get("StatusCode") == "ORA_ACTIVE" and s.get("SiteNumber")]


def resolve(session: PoliteSession, det: Detection, url: str) -> Detection:
    """*det* (from the link *url*) pointed at an active site of its host: the named site when it is active,
    else the host's only active site (an old career page's link), else no entry and the active sites named,
    for the user to choose. *det* itself when the site list cannot be read."""
    host = urlparse(url if "://" in url else f"https://{url}").netloc.lower().split(":")[0]
    named = det.entry.partition("/")[2] if det.entry else ""
    active = _active_sites(session, host)
    if active is None or (named and named in active):
        return det
    if len(active) == 1:
        was = f"site {named} is not active" if named else "the link names no site"
        return Detection(_SITE, f"{host}/{active[0]}", f"Oracle Cloud HCM career site {host}: {was}; its active site is {active[0]}")
    listed = ", ".join(active) or "none"
    return unfollowable(_SITE, host, f"Oracle Cloud HCM host with several career sites (active: {listed}); link to the one to follow", "cant_yet")
