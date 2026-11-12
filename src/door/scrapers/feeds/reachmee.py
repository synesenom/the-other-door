#!/usr/bin/env python3
"""Scraper for ReachMee (Talentech) public job lists, a Swedish applicant tracking system (issue #527).

ReachMee runs the recruiting of many Swedish employers (universities, agencies, municipalities).
An employer embeds its list on its own career page with a small script the platform hosts, and the
list itself is a plain server-rendered page, read here without a login:

  GET https://web103.reachmee.com/customerjs/<installation>-<customer>-<site>.js
      → the variables the embedding script holds: ``validator`` (a per-site value the list
      URLs carry, public in every embed) and ``langDef`` (the site's language)
  GET https://web103.reachmee.com/ext/<installation>/<customer>/main?site=<site>&validator=<v>&lang=<L>
      → the list: ``#mainjoblist`` with one table row per ad (title link, a deadline, ...); the
      title of the page is ``<Employer> | <page>``; no rows when the employer has no open ad
  GET https://web103.reachmee.com/ext/<installation>/<customer>/job?site=...&validator=...&job_id=<id>
      → one ad: ``h1#jobad-heading``, the place and the reference number (``p.extid``), the
      text in ``div.jobad-body``; the ad page is read only for an ad not seen before

The list is not paged. It carries no publishing date (its date column is the application
deadline), so ``posted_at`` is empty. One customer can publish on several sites, one per language
(Örebro universitet: site 5 in Swedish, site 12 in English); each is its own entry.

Configured by ``reachmee_companies``: ``<installation>/<customer>/<site>`` (``I003/354/5``),
read off an apply link such as
``https://web103.reachmee.com/ext/I003/354/main?site=5&validator=...&rmpage=job&rmjob=12986``
or an embed ``…/customerjs/I003-354-5.js``; a customer on another web host is written
``web104.reachmee.com/I005/77/2``. ReachMee's older RSS feed
(``site106.reachmee.com/Public/rssfeed/external.ashx?id=<site>&InstallationID=<I>&CustomerName=<name>``)
needs the customer's name and the right ``siteNNN`` host, neither of which an apply link gives,
so it is not used; a link to it is known but not followed (``cant_yet``).

Terms: https://talentech.com/sv/legal/ (ReachMee's owner; read 2026-10-31) — nothing on scraping,
robots or automated access; the lists are made to be embedded on the employers' own sites.
robots.txt on web103.reachmee.com and site106.reachmee.com is ``Disallow: /``; it does not gate
the requests (``OBEY_ROBOTS`` in ``http_client``).
"""

import html as _html
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from door.scrapers.sdk import (
    JobPosting, PoliteSession, PROBE_TIMEOUT_S, ProbeResult, followed_name, make_job_id, record_error,
    record_pushback, run_probe, scrape_feeds, strip_html, workers,
)
from door.scrapers.sdk import Detection, keep_local, parts, unfollowable

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("reachmee.com",)

_SITE = "reachmee"
_KEY = "reachmee_companies"
_DEFAULT_HOST = "web103.reachmee.com"
_HEADERS = {"Accept": "text/html"}

_ENTRY = re.compile(r"^(?:(?P<host>web\d+\.reachmee\.com)/)?(?P<inst>I\d{3})/(?P<cust>\d+)/(?P<site>\d+)$", re.I)
_SCRIPT = re.compile(r"^(?P<inst>I\d{3})-(?P<cust>\d+)-(?P<site>\d+)\.js$", re.I)
_INSTALLATION = re.compile(r"I\d{3}", re.I)
_WEB_HOST = re.compile(r"web\d+\.reachmee\.com")
_LOCATION_HEADER = re.compile(r"(?i)\b(ort|plats|arbetsplats|arbetsort|stad|kommun|location|city|place|town)\b")
_NOT_FOLLOWED = ("ReachMee link that names no publishing site (customer and site number); "
                 "the older RSS feed needs the customer's name, which a link does not give")

Parts = tuple[str, str, str, str]  # (web host, installation, customer, site)


# --- entries and URLs ---

def _entry_text(host: str, inst: str, cust: str, site: str) -> str:
    """The ``reachmee_companies`` entry for a publishing site; the default web host is left out. Pure."""
    base = f"{inst.upper()}/{cust}/{site}"
    return base if host == _DEFAULT_HOST else f"{host}/{base}"


def _entry_parts(entry: str) -> Parts | None:
    """``(web host, installation, customer, site)`` of an entry (``I003/354/5``, ``web104.reachmee.com/I005/77/2``)
    or of a ReachMee link; ``None`` when it names no publishing site. Pure."""
    text = entry.strip()
    if "://" in text:
        det = detect_url(text)
        text = det.entry if det is not None and det.entry else ""
    match = _ENTRY.match(text)
    if match is None:
        return None
    return ((match["host"] or _DEFAULT_HOST).lower(), match["inst"].upper(), match["cust"], match["site"])


def _script_url(p: Parts) -> str:
    host, inst, cust, site = p
    return f"https://{host}/customerjs/{inst}-{cust}-{site}.js"


def _list_url(p: Parts, validator: str, lang: str) -> str:
    host, inst, cust, site = p
    return f"https://{host}/ext/{inst}/{cust}/main?site={site}&validator={validator}&lang={lang}"


def _platform_id(p: Parts, job_id: str) -> str:
    """Ids are per installation: the customer is folded in."""
    return f"{p[1]}-{p[2]}-{job_id}".lower()


# --- parsing ---

def _parse_customer_js(text: str) -> dict | None:
    """``{"validator", "lang"}`` from the embedding script's variables; ``None`` when it holds no validator
    (an unknown customer answers an empty script). Pure."""
    validator = re.search(r"var\s+validator\s*=\s*'([^']+)'", text or "")
    if validator is None:
        return None
    lang = re.search(r"var\s+langDef\s*=\s*'([^']*)'", text)
    return {"validator": validator.group(1), "lang": (lang.group(1) if lang else "") or "SE"}


def _has_list(html: str) -> bool:
    """Whether *html* is a ReachMee job list (its ``#mainjoblist`` block), empty or not. Pure."""
    return BeautifulSoup(html or "", "html.parser").find(id="mainjoblist") is not None


def _page_employer(soup: BeautifulSoup) -> str:
    """The employer a ReachMee page's ``<title>`` names (``Employer | page``); ``""`` when it has none."""
    title = soup.title.get_text() if soup.title is not None else ""
    return " ".join(title.split("|")[0].split())


def _parse_list(html: str, base: str = f"https://{_DEFAULT_HOST}/") -> tuple[str, list[dict]]:
    """``(employer, rows)`` of a job list: each row has ``job_id``, ``title``, ``url`` and, when the list has a
    place column, ``location``. ``("", [])`` for a page that is no list. Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    block = soup.find(id="mainjoblist")
    if block is None:
        return "", []
    table = block.find("table")
    headers = [th.get_text(" ", strip=True) for th in table.find_all("th")] if table is not None else []
    place = next((i for i, h in enumerate(headers) if _LOCATION_HEADER.search(h)), None)
    rows = []
    for tr in table.find_all("tr") if table is not None else []:
        link = tr.find("a", href=True)
        if link is None:
            continue
        url = urljoin(base, _html.unescape(link["href"]))
        job_id = (parse_qs(urlparse(url).query).get("job_id") or [""])[0]
        if not job_id:
            continue
        row = {"job_id": job_id, "title": link.get_text(" ", strip=True), "url": url}
        cells = tr.find_all("td")
        if place is not None and place < len(cells):
            row["location"] = cells[place].get_text(" ", strip=True)
        rows.append(row)
    return _page_employer(soup), rows


def _parse_job(html: str) -> dict:
    """``title``, ``location``, ``reference`` and ``description`` of an ad page; ``{}`` for a page with no ad. Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    body = soup.find(class_="jobad-body")
    heading = soup.find(id="jobad-heading")
    if body is None and heading is None:
        return {}
    place, reference = "", ""
    for p in soup.find_all("p", class_="extid"):
        label = p.find("span")
        if label is not None:
            label.extract()
            reference = reference or p.get_text(" ", strip=True)
        else:
            place = place or p.get_text(" ", strip=True)
    if body is not None:
        for extra in body.find_all("p", class_=("prefix-text", "suffix-text")):
            extra.extract()
    return {
        "title": heading.get_text(" ", strip=True) if heading is not None else "",
        "location": place,
        "reference": reference,
        "description": strip_html("".join(str(c) for c in body.children)) if body is not None else "",
    }


def _to_posting(row: dict, job: dict, name: str, p: Parts, scraped_at: datetime) -> dict:
    """One JobPosting dict from a list *row* and its ad page *job* (``{}`` when the page was not read). Pure."""
    platform_id = _platform_id(p, row["job_id"])
    posting = JobPosting(
        id=make_job_id(_SITE, platform_id),
        title=job.get("title") or row["title"],
        company=name,
        location=job.get("location") or row.get("location", ""),
        url=row["url"],
        description=job.get("description", ""),
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=None,
        apply_type="external",
        apply_url=row["url"],
    )
    return posting.model_dump(mode="json")


# --- network ---

def _refused(exc: Exception) -> bool:
    return getattr(getattr(exc, "response", None), "status_code", None) in (403, 429)


def _read_list(session: PoliteSession, p: Parts) -> str:
    """The list page of a publishing site (its customer script first, for the validator); raises
    ``ValueError`` when the customer script holds none."""
    script = _parse_customer_js(session.get(_script_url(p), headers=_HEADERS).text)
    if script is None:
        raise ValueError("the customer script holds no validator (no such publishing site?)")
    return session.get(_list_url(p, script["validator"], script["lang"]), headers=_HEADERS).text


def _entry_postings(session: PoliteSession, entry: str, known_ids: frozenset[str], config: dict,
                    scraped_at: datetime) -> list[dict]:
    """The postings of one publishing site: its list, then the page of each ad not seen before."""
    p = _entry_parts(entry)
    if p is None:
        raise ValueError(f"not a ReachMee publishing site (expected <installation>/<customer>/<site>): {entry!r}")
    try:
        employer, rows = _parse_list(_read_list(session, p), f"https://{p[0]}/")
    except Exception as exc:
        if _refused(exc):
            record_pushback(_SITE)
        raise
    name = followed_name(config, _KEY, entry, employer or entry)
    postings = []
    refused = False
    for row in rows:
        if _platform_id(p, row["job_id"]) in known_ids:
            continue
        job: dict = {}
        if not refused:
            try:
                job = _parse_job(session.get(row["url"], headers=_HEADERS).text)
            except Exception as exc:  # noqa: BLE001 - the row stays, without its text
                record_error(_SITE, f"error fetching the ad {row['url']!r}: {exc}")
                if _refused(exc):
                    record_pushback(_SITE)
                    refused = True
        postings.append(_to_posting(row, job, name, p, scraped_at))
    return postings


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Every open ad of each followed ReachMee publishing site, those in another country left out."""
    entries = [e.strip() for e in config.get(_KEY) or [] if e.strip()]

    def host_of_entry(entry: str) -> str:
        p = _entry_parts(entry)
        return p[0] if p else _DEFAULT_HOST

    def fetch(session, entry, scraped_at):
        return _entry_postings(session, entry, known_ids, config, scraped_at)

    return keep_local(scrape_feeds(_SITE, entries, fetch, group=host_of_entry, max_workers=workers(config),
                                   headers=_HEADERS), config, _SITE)


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the list page of the first configured publishing site (two requests: the
    customer script holds the validator the list needs). ``None`` when none is set."""
    entries = [e for e in config.get(_KEY) or [] if e.strip()]
    p = _entry_parts(entries[0]) if entries else None
    if p is None:
        return None
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

    def parse(text: str):
        if not _has_list(text):
            return [], False, "no `#mainjoblist` block in the ReachMee job list"
        employer, rows = _parse_list(text, f"https://{p[0]}/")
        scraped_at = datetime.now(timezone.utc)
        return [_to_posting(r, {}, employer or entries[0], p, scraped_at) for r in rows], True, ""

    return run_probe(lambda: _read_list(session, p), parse, "html")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

def _link_site(path: list[str], query: dict[str, str]) -> tuple[str, str, str] | None:
    """``(installation, customer, site)`` a ReachMee link's path and query name: an ``/ext/<I>/<customer>/…?site=<n>``
    page or a ``/customerjs/<I>-<customer>-<n>.js`` embed."""
    kind = path[0].lower() if path else ""
    if kind == "ext" and len(path) >= 3 and _INSTALLATION.fullmatch(path[1]) and path[2].isdigit() and query.get("site", "").isdigit():
        return path[1], path[2], query["site"]
    if kind == "customerjs" and len(path) >= 2 and (m := _SCRIPT.match(path[1])):
        return m["inst"], m["cust"], m["site"]
    return None


def detect_url(url: str) -> Detection | None:
    """A ReachMee link and the publishing site it names (an apply link or an embed script). Any other link on a
    ReachMee host (the RSS feed, the login) is known but not followed."""
    host, path, query = parts(url.strip())
    if not host.endswith(".reachmee.com") or host.startswith("www."):
        return None
    site = _link_site(path, query)
    if site is not None and _WEB_HOST.fullmatch(host):
        entry = _entry_text(host, *site)
        return Detection(_SITE, entry, f"ReachMee job list {entry}")
    return unfollowable(_SITE, host, _NOT_FOLLOWED, "cant_yet")


_URL_IN_HTML = re.compile(r"""https?://[\w.-]*reachmee\.com/[^"'\s<>)]+""", re.I)


def detect_html(html: str, url: str) -> Detection | None:
    """A career page that loads the employer's ReachMee embed script or frames its list."""
    for found in _URL_IN_HTML.findall(html or ""):
        det = detect_url(_html.unescape(found))
        if det is not None and det.entry:
            return Detection(_SITE, det.entry, f"{url} embeds the ReachMee list {det.entry}")
    return None


NAME_FROM_PAGE = True


def name_page(entry: str, link: str) -> str:
    """The page that names the employer: the publishing site's list, whose title is ``Employer | page`` (an ad
    page is titled by the job). The list needs the validator, which an apply link carries; *link* itself when
    it carries none (an embed script)."""
    p = _entry_parts(entry)
    validator = parse_qs(urlparse(link if "://" in link else f"https://{link}").query).get("validator")
    if p is None or not validator:
        return link
    return _list_url(p, validator[0], "SE")


def feed_url(entry: str) -> str | None:
    """None: the list is HTML behind a validator, so a link's shape is proof enough (``resolve`` reads the script)."""
    return None


def resolve(session: PoliteSession, det: Detection, url: str) -> Detection:
    """*det* if the publishing site's customer script answers with a validator, else no entry (an unknown
    customer answers an empty script). *det* itself when the script cannot be read."""
    p = _entry_parts(det.entry or "")
    if p is None:
        return det
    try:
        script = _parse_customer_js(session.get(_script_url(p), headers=_HEADERS).text)
    except Exception:  # noqa: BLE001 - no answer is no verdict
        return det
    if script is None:
        return unfollowable(_SITE, det.entry, "no ReachMee publishing site answers there", "cant_yet")
    return det
