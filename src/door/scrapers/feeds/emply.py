#!/usr/bin/env python3
"""Scraper for Emply's public vacancy API (issue #437).

Emply career sites (``<tenant>.career.emply.com``: DanChurchAid, Dansk Røde Kors) draw their
listing from one JSON endpoint that needs no key and no cookie:

  POST https://<tenant>.career.emply.com/api/integration/vacancy/get-page
      JSON body ``{count, offset, langCode, sectionId, filters: [], searchText: "", ...}``
      → ``{"vacancies": [{id, shortId, title, titleAsUrl, published, created, deadline,
      department, location, translations: [{title, content (HTML), languageKey}]}], "count": n}``

``sectionId: null`` lists every vacancy of the tenant at once (a tenant's several listing pages
are filters of the same list), paged by ``offset``. The ad page is
``https://<tenant>.career.emply.com/<lang>/ad/<titleAsUrl>/<shortId>``. A tenant that does not
exist answers a redirect to emply.com. The ad pages carry no schema.org markup and load
reCAPTCHA's script, which is why ``career_sites`` could not read them.

Configured by ``emply_tenants``: the tenant slug (``dca``) or any link on its career host.

A second shape (issue #431): Aarhus University embeds its Emply vacancy list in its own pages as a script
variable, ``DYCON.EmplyData.<id>.vacancies = [{title, deadline_date, registered_date, faculty (the
department), location {name, zip}, id, link, teaser, ...}]`` (``/about/profile/vacant-positions/``), with
the university's name in ``DYCON.EmplyData.<id>.title``. Such a page is an ``emply_tenants`` entry as its
whole URL; the ad text is the ``au-vacancies-single-text`` block of each new vacancy's page, and a
vacancy past its ``deadline_date`` is dropped.

Terms: none found for the API (emply.com/terms leads to its owner's site); the endpoint is
undocumented. robots.txt on a tenant host: ``Allow: /``.
"""

import json
import re
from datetime import date, datetime, timezone
from urllib.parse import urljoin

from door.scrapers.sdk import (
    JobPosting, PoliteSession, PROBE_TIMEOUT_S, ProbeResult, host_of, make_job_id, parse_iso_date, run_probe,
    report, scrape_feeds, strip_html, tenant_platform_id, workers, followed_name,
)
from door.scrapers.sdk import keep_local
from door.scrapers.sdk import Detection, NOT_ACCOUNTS, parts

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("emply.com",)

# `companies add` reads the careers page of a link on a tenant: it names the employer (#436).
NAME_FROM_PAGE = True

_SITE = "emply"
_SUFFIX = ".career.emply.com"
_HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}
_PAGE = 50
_MAX_PAGES = 100  # a safety stop for a runaway listing


def _is_page(entry: str) -> bool:
    """Whether an ``emply_tenants`` entry is a page that embeds the list (a link off Emply's own hosts). Pure."""
    entry = entry.strip().lower()
    return "://" in entry and not parts(entry)[0].endswith(_SUFFIX)


def _tenant(entry: str) -> str:
    """The tenant slug of an ``emply_tenants`` entry: a slug or a link on ``<tenant>.career.emply.com``. Pure."""
    entry = entry.strip().lower()
    host = parts(entry)[0] if ("://" in entry or "." in entry) else entry
    return host[: -len(_SUFFIX)] if host.endswith(_SUFFIX) else host


def _base(tenant: str) -> str:
    return f"https://{tenant}{_SUFFIX}"


def _request_body(offset: int, lang: str = "da-DK") -> dict:
    """The body of one ``get-page`` call: every section of the tenant (``sectionId`` null), *_PAGE* vacancies. Pure."""
    return {"count": _PAGE, "filters": [], "langCode": lang, "offset": offset, "searchText": "", "sectionId": None,
            "sortAscending": False, "light": False, "isJobAgent": False, "siteId": None}


def _translation(vacancy: dict) -> dict:
    translations = [t for t in vacancy.get("translations") or [] if isinstance(t, dict)]
    return translations[0] if translations else {}


def _ad_url(tenant: str, vacancy: dict) -> str:
    """``https://<tenant>.career.emply.com/<lang>/ad/<titleAsUrl>/<shortId>``, the language of the ad's text. Pure."""
    key = str(_translation(vacancy).get("languageKey") or "")
    lang = key.split("-")[0].lower() if re.fullmatch(r"[A-Za-z]{2}(-[A-Za-z]{2})?", key) else "en"
    return f"{_base(tenant)}/{lang}/ad/{vacancy.get('titleAsUrl') or ''}/{vacancy.get('shortId') or ''}"


def _to_posting(vacancy: dict, tenant: str, scraped_at: datetime, name: str = "") -> dict:
    short_id = str(vacancy.get("shortId") or "")
    translation = _translation(vacancy)
    url = _ad_url(tenant, vacancy)
    platform_id = tenant_platform_id(url, short_id)
    posting = JobPosting(
        id=make_job_id(_SITE, platform_id),
        title=(vacancy.get("title") or translation.get("title") or "").strip(),
        company=(name or vacancy.get("department") or tenant).strip(),
        location=(vacancy.get("location") or "").strip(),
        url=url,
        description=strip_html(translation.get("content") or ""),
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=parse_iso_date(vacancy.get("published") or vacancy.get("created") or ""),
        apply_type="external",
        apply_url=url,
    )
    return posting.model_dump(mode="json")


def _vacancies(items) -> list[dict]:
    return [v for v in items if isinstance(v, dict) and v.get("shortId")]


def _page(session: PoliteSession, tenant: str, offset: int) -> dict:
    """One ``get-page`` answer. Raises when the tenant does not exist (a redirect to emply.com) or the
    answer has no ``vacancies`` list."""
    resp = session.post(f"{_base(tenant)}/api/integration/vacancy/get-page", headers=_HEADERS,
                        json=_request_body(offset))
    if resp.is_redirect:
        raise ValueError(f"no Emply career site {tenant}{_SUFFIX} (redirected to {resp.headers.get('Location')})")
    data = resp.json()
    if not isinstance(data, dict) or not isinstance(data.get("vacancies"), list):
        raise ValueError("no `vacancies` list in Emply's answer")
    return data


def _tenant_postings(session: PoliteSession, entry: str, scraped_at: datetime, name: str = "") -> list[dict]:
    """Every vacancy of one tenant, labelled with the followed *name* when given. Raises on HTTP errors."""
    tenant = _tenant(entry)
    found: list[dict] = []
    seen: set[str] = set()
    offset = 0
    for _ in range(_MAX_PAGES):
        data = _page(session, tenant, offset)
        batch = data["vacancies"]
        for vacancy in _vacancies(batch):
            if vacancy["shortId"] not in seen:
                seen.add(vacancy["shortId"])
                found.append(_to_posting(vacancy, tenant, scraped_at, name))
        offset += len(batch)
        if not batch or offset >= int(data.get("count") or 0):
            break
    return found


# --- a page that embeds the vacancy list (Aarhus University, #431) ---

_EMBEDDED = re.compile(r"DYCON\.EmplyData\.\w+\.vacancies\s*=\s*")
_TITLE = re.compile(r'DYCON\.EmplyData\.\w+\.title\s*=\s*("(?:[^"\\]|\\.)*")')
_AD_TEXT = re.compile(r'class="au-vacancies-single-text">(.*?)<div class="au-vacancies-(?:vcard|apply)', re.DOTALL)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def embedded_vacancies(html: str) -> list[dict]:
    """The vacancies of the ``DYCON.EmplyData.<id>.vacancies`` JSON array in a page's script; empty when the page
    has none or it does not parse. Pure."""
    match = _EMBEDDED.search(html or "")
    if not match:
        return []
    try:
        data, _ = json.JSONDecoder().raw_decode(html, match.end())
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    return [v for v in data if isinstance(v, dict) and v.get("id") is not None and v.get("link")]


def _embedded_name(html: str) -> str:
    match = _TITLE.search(html or "")
    try:
        return str(json.loads(match.group(1))).strip() if match else ""
    except ValueError:
        return ""


def _embedded_title(title: str, faculty: str) -> str:
    """The title with its department after it (``Postdoc in X – Department of Physics``) unless the title names
    it already: an academic title often carries no field word. The department is the part of ``faculty`` before
    its first `` - `` (the rest is a section and an address). Pure."""
    department = (faculty or "").split(" - ")[0].strip()
    title = title.strip()
    if not department or department.lower() in title.lower():
        return title
    return f"{title} – {department}"


def _open(vacancy: dict, today: date) -> bool:
    """False for a vacancy whose ``deadline_date`` has passed. Pure."""
    deadline = parse_iso_date(str(vacancy.get("deadline_date") or ""))
    return deadline is None or deadline.date() >= today


def _embedded_description(html: str) -> str:
    """The ad text of a vacancy page: its ``au-vacancies-single-text`` block, tags stripped; "" without one. Pure."""
    match = _AD_TEXT.search(html or "")
    return strip_html(match.group(1)) if match else ""


def _embedded_posting(vacancy: dict, page_url: str, name: str, scraped_at: datetime) -> dict:
    url = urljoin(page_url, str(vacancy["link"]))
    platform_id = tenant_platform_id(url, str(vacancy["id"]))
    posting = JobPosting(
        id=make_job_id(_SITE, platform_id),
        title=_embedded_title(str(vacancy.get("title") or ""), str(vacancy.get("faculty") or "")),
        company=name,
        location=str((vacancy.get("location") or {}).get("name") or "").strip(),
        url=url,
        description=strip_html(str(vacancy.get("teaser") or "")) or str(vacancy.get("title") or ""),
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=parse_iso_date(str(vacancy.get("registered_date") or "")),
        apply_type="external",
        apply_url=url,
    )
    return posting.model_dump(mode="json")


def _page_postings(session: PoliteSession, page_url: str, scraped_at: datetime, name: str,
                   known_ids: frozenset[str]) -> list[dict]:
    """The new open vacancies of a page that embeds the list, each with its ad text. Raises when the page has none."""
    html = session.get(page_url, headers={"Accept": "text/html"}).text
    vacancies = embedded_vacancies(html)
    if not vacancies:
        raise ValueError("no embedded Emply vacancy list in the page")
    label = name or _embedded_name(html) or host_of(page_url)
    today = _today()
    postings = []
    for vacancy in vacancies:
        if not _open(vacancy, today):
            continue
        posting = _embedded_posting(vacancy, page_url, label, scraped_at)
        if posting["platform_id"] in known_ids:
            continue
        try:
            text = _embedded_description(session.get(posting["url"], headers={"Accept": "text/html"}).text)
        except Exception as exc:  # noqa: BLE001 - the teaser stays when the page cannot be read
            report(f"error fetching the ad of {posting['url']}: {exc}")
            text = ""
        if text:
            posting["description"] = text
        postings.append(posting)
    return postings


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Every open vacancy of each configured Emply career site; of a page that embeds the list, the new ones."""
    entries = [e.strip() for e in config.get("emply_tenants") or [] if e.strip()]

    def fetch(session, entry, scraped_at):
        name = followed_name(config, "emply_tenants", entry)
        if _is_page(entry):
            return _page_postings(session, entry, scraped_at, name, known_ids)
        return _tenant_postings(session, entry, scraped_at, name)

    def group(entry):
        return host_of(entry) if _is_page(entry) else host_of(_base(_tenant(entry)))

    return keep_local(scrape_feeds(_SITE, entries, fetch, group=group, max_workers=workers(config),
                                   headers=_HEADERS), config, _SITE)


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: page 1 of the first configured tenant. ``None`` when none is set."""
    entries = [e for e in config.get("emply_tenants") or [] if e.strip()]
    if not entries:
        return None
    tenant = _tenant(entries[0])
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

    def fetch() -> str:
        resp = session.post(f"{_base(tenant)}/api/integration/vacancy/get-page", headers=_HEADERS,
                            json=_request_body(0))
        if resp.is_redirect:
            raise ValueError(f"no Emply career site {tenant}{_SUFFIX}")
        return resp.text

    def parse(text: str):
        data = json.loads(text)
        items = data.get("vacancies") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return [], False, "no `vacancies` list in the Emply API response"
        scraped_at = datetime.now(timezone.utc)
        return [_to_posting(v, tenant, scraped_at) for v in _vacancies(items)], True, ""

    return run_probe(fetch, parse, "json")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

def detect_url(url: str) -> Detection | None:
    """A link on an Emply career site (``<tenant>.career.emply.com``) and the tenant it names."""
    host, _path, _query = parts(url.strip())
    tenant = host[: -len(_SUFFIX)] if host.endswith(_SUFFIX) else ""
    if tenant and "." not in tenant and tenant not in NOT_ACCOUNTS:
        return Detection("emply", tenant, f"Emply career site {host}")
    return None


def detect_html(html: str, url: str) -> Detection | None:
    """A page that embeds an Emply vacancy list (Aarhus University's, #431): the page itself is the entry."""
    if embedded_vacancies(html):
        return Detection("emply", url, f"{url} embeds an Emply vacancy list")
    return None


def feed_url(entry: str) -> str | None:
    """None: the vacancy list is a POST, which the link's shape (a tenant host) vouches for."""
    return None
