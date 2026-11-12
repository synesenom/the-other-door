#!/usr/bin/env python3
"""Scraper for employers on Networx (networx Recruitment, by IRIS Software), a UK applicant-tracking system (issue #603).

Kind of site: a job board shared by many employers, ``www.networxrecruitment.com`` (the same clients' adverts are on
``current-vacancies.com``). Every employer is a client with a number, ``cid`` in the advert links
(``/Jobs/Advert/3382599?cid=1491``, Wates). The employer is that client, never the shared host: the board's search can be
narrowed to one client, and that is what is read. (The ``js=`` of the advert's own request is no client id; it is a
job-seeker flag.) No key and no login:

  GET https://www.networxrecruitment.com/Website/Search?SelectedEmployers=<cid>
      → the server-rendered result page: ``div.row.advert`` rows (title, ``Location:``, ``Salary:``, ``Reference:``,
        ``Closing Date:``, the client's name as the logo's text, the first lines of the ad), a hidden form
        ``#formSearchJobs`` whose ``TotalResultsPageCount`` is the number of result pages (five ads each), and the
        sponsored adverts of other clients (not rows; also filtered by ``cid``). A client with no open ad gets
        "Sorry, there are no jobs matching your search criteria" and the sponsored ones.
  POST https://www.networxrecruitment.com/Website/JobSearchMoreResults   (form: the hidden fields with ``ResultsPage=<n>``,
        header ``__RequestVerificationToken`` from the page, the anonymous cookie the first GET set: the page's own
        "load more" call; the page URL's ``ResultsPage`` is ignored)
      → ``{"HTML": "<rows>", "TotalResultsPageCount": n}``.
  GET https://www.networxrecruitment.com/Jobs/Advert/<id>?cid=<cid>
      → the advert: its text is in ``div.container[id="[@idDisplay@]"]`` blocks (each under a ``.DynamicLinks`` heading:
        "The Vacancy", "About Us", ...; the employer's template decides which), and a schema.org JobPosting JSON-LD for
        ``datePosted`` and the hiring organisation (its ``description`` is a stub, its closing brace is missing, and some
        employers' pages, Wates's, have none). The ad's text is in the advert page only, so one is fetched per ad not
        in ``known_ids``; the ad's salary (not in its text) is put on the first line.

Configured by ``networx_companies`` (filled from ``profile/companies.json``): the client id (``3509``) or an advert or
search link that carries it. Detection: such a link on ``networxrecruitment.com`` or ``current-vacancies.com``. This
module comes before `career_sites` in ``ats_detect.PRECEDENCE``: the JSON-LD on these pages made that generic reader take
the shared host for the employer and read every client's ads.

Terms: https://www.iris.co.uk/legal/website-terms-conditions/ (IRIS's website terms; the site's own privacy policy is
https://www.networxrecruitment.com/PrivacyPolicy): neither bans scraping, bots or text-and-data mining. robots.txt of
``www.networxrecruitment.com``: ``User-agent: *`` ``Allow: /``. Checked 2026-11-04.
"""

import json
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from door.scrapers.sdk import (
    Detection, JobPosting, PROBE_TIMEOUT_S, PoliteSession, ProbeResult, RobotsBlocked, followed_name, host_of,
    keep_local, make_job_id, parse_iso_date, parts, record_entry_error, record_error, record_pushback, report, run_probe,
    scrape_feeds, strip_html, workers,
)

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("networxrecruitment.com", "current-vacancies.com")

_SITE = "networx"
_KEY = "networx_companies"
_HOST = "https://www.networxrecruitment.com"
_HOSTS = ("www.networxrecruitment.com", "networxrecruitment.com", "www.current-vacancies.com", "current-vacancies.com")
_MORE_URL = f"{_HOST}/Website/JobSearchMoreResults"
_PUSHBACK = (401, 403, 429)
_MAX_PAGES = 60   # result pages per client per run (five ads each)
_HEADERS = {"Accept": "text/html,application/xhtml+xml,application/json"}
_TEXT_BLOCK = 'div.container[id="[@idDisplay@]"]'


# --- pure helpers ---

def _cid(entry: str) -> str | None:
    """The client id of a ``networx_companies`` entry: the number, or an advert (``/Jobs/Advert/<id>?cid=``) or search
    (``/Website/Search?SelectedEmployers=``) link on the board that carries it. Pure."""
    entry = (entry or "").strip()
    if re.fullmatch(r"\d+", entry):
        return entry
    if not entry or "." not in entry or " " in entry:
        return None
    host, path, query = parts(entry)
    if host not in _HOSTS:
        return None
    where = "/".join(p.lower() for p in path[:2])
    value = query.get("cid") if where in ("jobs/advert", "jobs/displayadvert") else \
        query.get("selectedemployers") if where == "website/search" else None
    return value if value and re.fullmatch(r"\d+", value) else None


def search_url(cid: str) -> str:
    """The board's search narrowed to the client with id *cid*."""
    return f"{_HOST}/Website/Search?SelectedEmployers={cid}"


def feed_url(entry: str) -> str | None:
    """None: the list is HTML, not a JSON answer to confirm by; a link that carries a client id is proof enough."""
    return None


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)) if node is not None else ""


def parse_rows(html: str) -> list[dict]:
    """The adverts of a result page or of a "load more" fragment: ``{id, cid, title, location, salary, reference,
    closing, employer, teaser}`` (the first lines of the ad). Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    rows = []
    for row in soup.select("div.row.advert"):
        link = row.select_one("a.title")
        found = re.search(r"/Jobs/Advert/(\d+)\?cid=(\d+)", link.get("href", "")) if link is not None else None
        title = _text(link)
        if not (found and title):
            continue
        info = {}
        for p in row.select(".aFurtherInfo p"):
            label = _text(p.find("span")).rstrip(":").lower()
            info[label] = _text(p)[len(_text(p.find("span"))):].strip()
        teaser = row.select_one("section.details > p")
        logo = _text(row.select_one(".aLogo .off-screen"))
        rows.append({
            "id": found.group(1),
            "cid": found.group(2),
            "title": title,
            "location": info.get("location", ""),
            "salary": info.get("salary", ""),
            "reference": info.get("reference", ""),
            "closing": info.get("closing date", ""),
            "employer": logo.removesuffix(" Logo").strip(),
            "teaser": re.sub(r"\s*\.\.\.$", "", strip_html(str(teaser))) if teaser is not None else "",
        })
    return rows


def parse_search(html: str) -> dict:
    """``{rows, pages, token, form}`` of a search page: the client's adverts, the number of result pages, the anti-forgery
    token and the hidden fields a next page is asked with. Raises ``ValueError`` for a page with no results block (an error
    or block page); a search with no adverts is valid and empty. Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    results = soup.select_one("section.results-container")
    if results is None:
        raise ValueError("no results block in the Networx search page")
    rows = parse_rows(str(results))
    form_tag = soup.find("form", id="formSearchJobs")
    form = {i.get("name"): i.get("value") or "" for i in form_tag.find_all("input") if i.get("name")} if form_tag is not None else {}
    token = soup.find("input", attrs={"name": "__RequestVerificationToken"})
    try:
        pages = int(form.get("TotalResultsPageCount") or 0)
    except ValueError:
        pages = 0
    return {"rows": rows, "pages": pages or (1 if rows else 0), "token": token.get("value") if token is not None else None,
            "form": form}


def parse_more(text: str) -> tuple[int, list[dict]]:
    """``(result pages, adverts)`` of a "load more" answer. Raises ``ValueError`` when it is no such JSON. Pure."""
    try:
        data = json.loads(text or "")
    except ValueError as exc:
        raise ValueError(f"not a Networx result page: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("HTML"), str):
        raise ValueError("no `HTML` in the Networx answer")
    try:
        pages = int(data.get("TotalResultsPageCount") or 0)
    except (TypeError, ValueError):
        pages = 0
    return pages, parse_rows(data["HTML"])


def _load_ld(text: str):
    """The JSON-LD object of *text*; the unclosed object the site writes is closed first. ``None`` when it is not JSON."""
    text = (text or "").strip()
    for candidate in (text, text + "}" * max(text.count("{") - text.count("}"), 0)):
        try:
            return json.loads(candidate, strict=False)
        except ValueError:
            continue
    return None


def parse_ad(html: str) -> dict | None:
    """``{description, posted_at, organization}`` of an advert page: the text of its blocks under their headings, the
    day and the hiring organisation from the JSON-LD (``None`` and ``""`` when the page has none). ``None`` when the page
    has neither text nor markup. Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    node = None
    for tag in soup.find_all("script", type=re.compile(r"ld(\+|&#x2B;|&#43;)json", re.IGNORECASE)):
        data = _load_ld(tag.string or tag.get_text())
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            node = data
            break
    sections = []
    for block in soup.select(_TEXT_BLOCK):
        for junk in block.find_all(["script", "style"]):
            junk.decompose()
        text = strip_html(str(block))
        if not text:
            continue
        before = block.find_previous_sibling()
        heading = _text(before) if before is not None and "DynamicLinks" in (before.get("class") or []) else ""
        sections.append(f"{heading}\n{text}" if heading else text)
    description = "\n\n".join(sections)
    if not description:
        meta = soup.find("meta", attrs={"property": "og:description"})
        description = strip_html(meta.get("content") if meta is not None else "")
    if node is None and not description:
        return None
    node = node or {}
    organization = node.get("hiringOrganization")
    posted = parse_iso_date(node.get("datePosted"))
    return {
        "description": description,
        "posted_at": posted.replace(tzinfo=timezone.utc) if posted is not None and posted.tzinfo is None else posted,
        "organization": strip_html(str(organization.get("name") or "")) if isinstance(organization, dict) else "",
    }


def _to_posting(row: dict, ad: dict | None, name: str, scraped_at: datetime) -> dict:
    ad = ad or {}
    url = f"{_HOST}/Jobs/Advert/{row['id']}?cid={row['cid']}"
    text = ad.get("description") or row["teaser"]
    posting = JobPosting(
        id=make_job_id(_SITE, row["id"]),
        title=row["title"],
        company=name or ad.get("organization") or row["employer"] or row["cid"],
        location=row["location"],
        url=url,
        description=f"Salary: {row['salary']}\n\n{text}" if row["salary"] and text else text,
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=row["id"],
        posted_at=ad.get("posted_at"),
        apply_type="external",
        apply_url=url,
    )
    return posting.model_dump(mode="json")


def _status(exc: Exception) -> int | None:
    return getattr(getattr(exc, "response", None), "status_code", None)


# --- network ---

def _rows_of(session: PoliteSession, entry: str, cid: str) -> list[dict]:
    """Every advert of one client: its search page, then the next result pages the page's own call asks for until the
    count is reached or a page adds nothing new. Raises when the search page cannot be read (a refusal is recorded as
    pushback first); a next page that fails is recorded and ends the paging."""
    try:
        search = parse_search(session.get(search_url(cid)).text)
    except (requests.RequestException, RobotsBlocked) as exc:
        if _status(exc) in _PUSHBACK:
            record_pushback(_SITE)
        raise
    rows = {r["id"]: r for r in search["rows"] if r["cid"] == cid}
    for page in range(2, min(search["pages"], _MAX_PAGES) + 1):
        if search["token"] is None:
            record_error(_SITE, f"no token to ask page {page} of {entry!r}")
            break
        try:
            answer = session.post(_MORE_URL, data={**search["form"], "ResultsPage": str(page)},
                                  headers={"__RequestVerificationToken": search["token"], "X-Requested-With": "XMLHttpRequest"})
            _pages, more = parse_more(answer.text)
        except (requests.RequestException, RobotsBlocked, ValueError) as exc:
            if _status(exc) in _PUSHBACK:
                record_pushback(_SITE)
                raise
            record_error(_SITE, f"error fetching page {page} of {entry!r}: {exc}")
            break
        fresh = {r["id"]: r for r in more if r["cid"] == cid and r["id"] not in rows}
        if not fresh:
            break
        rows.update(fresh)
    return list(rows.values())


def _employer_postings(session: PoliteSession, entry: str, scraped_at: datetime, known_ids: frozenset[str],
                       name: str) -> list[dict]:
    """One client's postings: its adverts, then the page of each advert not in *known_ids*. Raises when the search cannot
    be read; a refusal on an advert is recorded as pushback and ends the client."""
    cid = _cid(entry)
    if cid is None:
        raise ValueError("not a Networx client")
    rows = [r for r in _rows_of(session, entry, cid) if r["id"] not in known_ids]
    out: list[dict] = []
    for n, row in enumerate(rows, 1):
        report("detail", n, len(rows))
        try:
            ad = parse_ad(session.get(f"{_HOST}/Jobs/Advert/{row['id']}", params={"cid": row["cid"]}).text)
        except (requests.RequestException, RobotsBlocked) as exc:
            if _status(exc) in _PUSHBACK:
                record_pushback(_SITE)
                record_entry_error(_SITE, entry, f"{entry!r} refused advert {row['id']} ({_status(exc)}); stopped", blocked=True)
                break
            record_error(_SITE, f"error fetching advert {row['id']} of {entry!r}: {exc}")
            continue
        if ad is None:
            record_error(_SITE, f"advert {row['id']} of {entry!r} has no ad data")
            continue
        out.append(_to_posting(row, ad, name, scraped_at))
    return out


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Every open advert of each configured Networx client."""
    entries = [e for e in config.get(_KEY) or [] if e.strip()]

    def fetch(session, entry, scraped_at):
        return _employer_postings(session, entry, scraped_at, known_ids, followed_name(config, _KEY, entry, ""))

    return keep_local(scrape_feeds(_SITE, entries, fetch, group=lambda e: host_of(_HOST),
                                   max_workers=workers(config), headers=_HEADERS), config, _SITE)


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the first client's search page (one request). ``None`` when none is set.
    The page carries the first lines of each ad, so a posting here has those, not the whole text."""
    entries = [e for e in config.get(_KEY) or [] if e.strip()]
    cid = _cid(entries[0]) if entries else None
    if cid is None:
        return None
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)

    def fetch() -> str:
        return session.get(search_url(cid)).text

    def parse(text: str):
        try:
            search = parse_search(text)
        except ValueError as exc:
            return [], False, str(exc)
        now = datetime.now(timezone.utc)
        return [_to_posting(r, None, "", now) for r in search["rows"] if r["cid"] == cid], True, ""

    return run_probe(fetch, parse, "html")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

def is_shared_host(host: str) -> bool:
    """Whether *host* is the board's own (a link there that carries no client id is no employer's career site)."""
    return host in _HOSTS


def detect_url(url: str) -> Detection | None:
    """An advert or search link on the board, and the client id it carries."""
    host = parts(url.strip())[0]
    cid = _cid(url) if host in _HOSTS else None
    return Detection(_SITE, cid, f"Networx client {cid} ({host})") if cid else None
