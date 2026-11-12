#!/usr/bin/env python3
"""Scraper for Jobindex (jobindex.dk).

Uses the HTML search page which embeds all search results as a JSON Stash object,
then fetches each job's detail page for the full description.

Jobindex's robots.txt (read as RFC 9309 does, wildcards included) allows a search
with the query alone, `/jobsoegning[/<category>][/<area>]?q=<phrase>`, but not its
`page`, `jobage` or `geoareaid` parameters, nor a query of three or more words, so
a search returns one page of 20 results, ranked by relevance. Completeness comes
from narrow searches instead (issue #255). Unless robots.txt gates requests
(`http_client.OBEY_ROBOTS`), a search also reads up to
`max_pages_per_keyword` pages before it is split:

1. each search keyword becomes one or more phrases of at most two words (`_keyword_phrases`),
   quoted so that Jobindex matches the phrase and not each word;
2. the phrase is searched in the profile's area; when the search has more hits than
   one page held (`hitcount`), it is searched again in each job category
   (`/jobsoegning/<category>/<area>`), and a category still over a page is searched
   in the area's sub-areas (`_sub_areas`, from the site's area sitemap), the full
   categories taking turns so that none is favoured when the budget runs out;
3. the splitting stops when the hits are covered or after `_MAX_SEARCHES` searches
   for the phrase; hits not reached are reported, not recorded as an error.

No age filter can be asked for (the cutoff is left to `find`). A new ad whose title is on topic
for the keywords (`door.matching.title_fit.on_topic`) costs a detail-page request (Jobindex,
then often the employer's page); the rest keep their search teaser, which is all the prescreen
needs to drop them. Requests pause `http_client.FEED_DELAY`. Bound it with
`max_postings_per_site`.

Terms: https://www.jobindex.dk/betingelser/vis?id=226 (10 March 2026) — no clause on automated access.
robots.txt allows a one-parameter search (in a category and an area path) and the
ad pages, and disallows paging, age and area filters.
"""

import gzip
import html as html_lib
import json
import re
import unicodedata
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Iterator, NamedTuple, Sequence
from urllib.parse import parse_qs, quote_plus, urlparse

from bs4 import BeautifulSoup

from door.scrapers.sdk import (
    FEED_DELAY, JobPosting, PoliteSession, PROBE_TIMEOUT_S, ProbeResult, RobotsBlocked, city_names,
    compile_words, log_keyword_results, make_job_id, on_topic, record_error, report, run_probe,
    seniority_words, stop_words, topic_terms, transliteration,
)

_BASE = "https://www.jobindex.dk"
_SEARCH_URL = _BASE + "/jobsoegning"
_DETAIL_URL = _BASE + "/jobannonce/{tid}/"

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "da,en;q=0.9",
}

# Maps profile location strings to Jobindex's area path segment
# (`/jobsoegning/<area>`); "" searches all of Denmark. The `geoareaid` parameter
# would do the same, but robots.txt disallows it.
_STORKOEBENHAVN = "storkoebenhavn"
_LOCATION_TO_AREA: dict[str, str] = {
    "copenhagen": _STORKOEBENHAVN,
    "københavn": _STORKOEBENHAVN,
    "aarhus": "region-midtjylland",
    "odense": "region-syddanmark",
    "aalborg": "region-nordjylland",
    "denmark": "",
    "remote": "",
}

_MAX_PAGES = 3
# Pause between requests: the employer feeds' (one host, one at a time).
_MIN_DELAY, _MAX_DELAY = FEED_DELAY
_PAGE_SIZE = 20
# The most searches (pages, categories, sub-areas) spent on one phrase.
_MAX_SEARCHES = 120

_AREA_SITEMAP_URL = _BASE + "/sitemap/area.gz"

# Jobindex's job categories, as path segments (`/jobsoegning/<category>/<area>`; each
# title checked on the live site, 2026-10-12), in alphabetical order and "oevrige" (other) last;
# every one is searched, and their sub-area searches take turns (`_Searcher.collect`).
_CATEGORIES: tuple[str, ...] = (
    "handel", "industri", "ingenioer", "it", "kontor",
    "ledelse", "salg", "social", "undervisning", "oevrige",
)

# The postcodes (a path slug starts with its postcode) inside an area that has
# sub-areas to split a search by. The sitemap lists areas flat, with no hierarchy.
_AREA_POSTCODES: dict[str, range] = {_STORKOEBENHAVN: range(1000, 3000)}


# Hosts of this board: a link here is an ad on the board, never an employer's own site (`ats_detect.is_job_board`).
JOB_BOARD_HOSTS = ("jobindex.",)


def _load_stash(html: str) -> dict:
    """Decode the page's Stash object; {} when absent. Raises ValueError on bad JSON. Pure."""
    m = re.search(r"var Stash = ({.*?});\n", html, re.DOTALL)
    if not m:
        return {}
    return json.loads(m.group(1))


def _parse_stash(html: str) -> dict:
    try:
        return _load_stash(html)
    except Exception as exc:
        report(f"parse error decoding Stash JSON: {exc}")
        record_error("jobindex", f"parse error decoding Stash JSON: {exc}")
        return {}


def _search_response(stash: dict) -> dict | None:
    """Return the `searchResponse` block from a parsed Stash, or None if absent.

    The results app is keyed `jobsearch/result_app` on older pages and
    `jobsearch/result_app/list` since Oct 2026, so accept any key with that prefix.
    """
    for key, app in stash.items():
        if not key.startswith("jobsearch/result_app") or not isinstance(app, dict):
            continue
        response = (app.get("storeData") or {}).get("searchResponse")
        if isinstance(response, dict):
            return response
    return None


def _parse_search(html: str) -> tuple[dict | None, list[dict]]:
    """Pure: ``(searchResponse | None, results)`` for a search page; no error recording."""
    try:
        response = _search_response(_load_stash(html))
    except Exception:
        return None, []
    if response is None:
        return None, []
    return response, response.get("results") or []


class _Page(NamedTuple):
    hitcount: int
    page_size: int
    results: list[dict]


class _Search(NamedTuple):
    """One search: a phrase in an area (a path slug, "" for Denmark) and a category ("" for any)."""

    phrase: str
    area: str
    category: str


def _keyword_phrases(keyword: str) -> list[str]:
    """The search phrases for *keyword*: each at most two words, lower case. Pure.

    A keyword of up to two words is used as is. A longer one loses its seniority and
    function words (``lead``, ``head``, ``of``, ``and``, ... from ``i18n``'s language files),
    ``&`` and list commas; each run of words left next to each other keeps its last two
    words: "Head of Finance" -> "finance", "monitoring and evaluation" -> "monitoring" and
    "evaluation" (a quoted "monitoring evaluation" is in no ad, #434). Empty when nothing is left.
    """
    words = keyword.split()
    if len(words) <= 2:
        return [" ".join(words).lower()] if words else []
    drop = compile_words([*seniority_words(), *stop_words()])
    runs: list[list[str]] = [[]]
    for word in words:
        bare = word.strip(",;")
        if bare and re.search(r"\w", bare) and not drop.search(bare):
            runs[-1].append(bare)
        elif runs[-1]:
            runs.append([])
        if word != bare and runs[-1]:  # "Monitoring, Evaluation": a list ends a run
            runs.append([])
    return [" ".join(run[-2:]).lower() for run in runs if run]


def _search_phrases(keywords: Sequence[str]) -> tuple[list[str], list[str]]:
    """``(phrases, skipped keywords)``: the distinct search phrases of *keywords*, in order. Pure."""
    phrases: dict[str, None] = {}
    skipped: list[str] = []
    for keyword in keywords:
        found = _keyword_phrases(keyword)
        if not found:
            skipped.append(keyword)
        for phrase in found:
            phrases.setdefault(phrase, None)
    return list(phrases), skipped


def _search_url(query: str, area: str, page: int = 1, category: str = "") -> str:
    """The search URL for *query* (quoted when it has two words) in *category* and *area*
    (path segments, "" for any). Pure."""
    q = f'"{query}"' if " " in query else query
    path = "/".join(part for part in (category, area) if part)
    url = f"{_SEARCH_URL}/{path}" if path else _SEARCH_URL
    return f"{url}?q={quote_plus(q)}" + (f"&page={page}" if page > 1 else "")


def _split(search: _Search, hitcount: int, capacity: int, categories: Sequence[str],
           sub_areas: Callable[[], Sequence[str]]) -> list[_Search]:
    """The narrower searches to run after *search* found *hitcount* hits but could
    read only *capacity* of them. Pure.

    A full search without a category is split by category; a full category (in the
    profile's area) by sub-area. Nothing narrower than that, and nothing when the
    page held every hit. *sub_areas* is only called when a category is full.
    """
    if hitcount <= capacity:
        return []
    if not search.category:
        return [_Search(search.phrase, search.area, c) for c in categories]
    subs = sub_areas()
    if search.area in subs:
        return []
    return [_Search(search.phrase, a, search.category) for a in subs]


def _slug(name: str) -> str:
    """A city name as a Jobindex path slug: "København*" -> "koebenhavn". Pure."""
    spelled = name.lower().rstrip("*").translate(transliteration())
    ascii_ = unicodedata.normalize("NFD", spelled).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_).strip("-")


def _area_slugs(data: bytes) -> list[str]:
    """The area slugs of Jobindex's area sitemap (``sitemap/area.gz``, gzipped or
    plain XML); [] for anything else. Pure."""
    try:
        data = gzip.decompress(data)
    except (OSError, EOFError):
        pass
    text = data.decode("utf-8", errors="ignore")
    return re.findall(r"<loc>https://www\.jobindex\.dk/jobsoegning/([^/<?]+)</loc>", text)


def _sub_areas(area: str, slugs: Sequence[str], location: str) -> list[str]:
    """The areas inside the profile's *area* to split a full search by: the cities
    ``i18n`` knows around *location* and the postcode areas of ``_AREA_POSTCODES``,
    among the sitemap's *slugs*. [] for an area with none. Pure."""
    postcodes = _AREA_POSTCODES.get(area)
    if postcodes is None:
        return []
    available = set(slugs)
    subs = [c for c in dict.fromkeys(_slug(n) for n in city_names(location)) if c in available and c != area]
    for slug in sorted(available):
        m = re.match(r"(\d{4})-", slug)
        if m and int(m.group(1)) in postcodes and slug not in subs:
            subs.append(slug)
    return subs


def _search_page(session: PoliteSession, query: str, area: str, page: int, category: str = "") -> _Page | None:
    """Fetch one search results page.

    A page without a results block means Jobindex changed its markup, so it is
    recorded as an error rather than passing for a search with no hits (``None``).
    """
    resp = session.get(_search_url(query, area, page, category), headers=_HEADERS)
    response = _search_response(_parse_stash(resp.text))
    if response is None:
        report(f"no search results block on page (role={query!r}, page={page})")
        record_error("jobindex", f"no search results block on page (role={query!r}, page={page})")
        return None
    results = response.get("results") or []
    return _Page(int(response.get("hitcount") or len(results)), int(response.get("page_size") or _PAGE_SIZE), results)


class _Searcher:
    """Runs the searches of one scrape: reads each URL once and counts the requests."""

    def __init__(self, session: PoliteSession, area: str, location: str, max_pages: int) -> None:
        self.session, self.area, self.location, self.max_pages = session, area, location, max_pages
        self.requests = 0
        self._cache: dict[_Search, tuple[int, int, list[dict]] | None] = {}
        self._subs: list[str] | None = None

    def sub_areas(self) -> list[str]:
        if self._subs is None:
            slugs: list[str] = []
            if self.area in _AREA_POSTCODES:
                try:
                    self.requests += 1
                    slugs = _area_slugs(self.session.get(_AREA_SITEMAP_URL, headers=_HEADERS).content)
                except Exception as exc:  # noqa: BLE001 - splitting by sub-area is an extra, not a must
                    report(f"area sitemap unavailable, not splitting by sub-area: {exc}")
            self._subs = _sub_areas(self.area, slugs, self.location)
        return self._subs

    def fetch(self, search: _Search) -> tuple[int, int, list[dict]] | None:
        """``(hitcount, capacity, results)`` of *search* - capacity being what the pages
        read could hold - or ``None`` when the search failed (recorded)."""
        if search in self._cache:
            return self._cache[search]
        got: tuple[int, int, list[dict]] | None = None
        label = search.phrase + (f" in {search.category}" if search.category else "")
        try:
            self.requests += 1
            page = _search_page(self.session, search.phrase, search.area, 1, search.category)
            if page is not None:
                results, pages = list(page.results), 1
                # Further pages when robots.txt is not obeyed (it disallows `page`).
                while pages < self.max_pages and page.results and len(results) < page.hitcount:
                    url = _search_url(search.phrase, search.area, pages + 1, search.category)
                    if not self.session.allows(url):
                        break
                    self.requests += 1
                    try:
                        more = _search_page(self.session, search.phrase, search.area, pages + 1, search.category)
                    except Exception as exc:  # noqa: BLE001 - keep the pages already read
                        report(f"search error (role={label!r}, page={pages + 1}): {exc}")
                        record_error("jobindex", f"search error (role={label!r}, page={pages + 1}): {exc}")
                        break
                    pages += 1
                    if more is None:
                        break
                    results += more.results
                got = (page.hitcount, page.page_size * pages, results)
        except Exception as exc:  # noqa: BLE001 - one bad search must not end the run
            report(f"search error (role={label!r}, page=1): {exc}")
            record_error("jobindex", f"search error (role={label!r}, page=1): {exc}")
        self._cache[search] = got
        return got

    def collect(self, phrase: str) -> list[dict]:
        """The distinct results for *phrase*: its search in the profile's area, then
        narrower ones while the hits are not all covered (see the module docstring)."""
        found: dict[str, dict] = {}
        root = _Search(phrase, self.area, "")
        queue: deque[_Search] = deque([root])
        # A full category's sub-area searches, one lane per category, taken in turns.
        lanes: list[deque[_Search]] = []
        target = 0
        spent = 0
        while (queue or lanes) and spent < _MAX_SEARCHES:
            if not queue:
                queue.extend(lane.popleft() for lane in lanes)
                lanes = [lane for lane in lanes if lane]
            search = queue.popleft()
            got = self.fetch(search)
            spent += 1
            if got is None:
                continue
            hitcount, capacity, results = got
            if search == root:
                target = hitcount
            for r in results:
                if r.get("tid"):
                    found.setdefault(r["tid"], r)
            if len(found) >= target:
                break
            narrower = _split(search, hitcount, capacity, _CATEGORIES, self.sub_areas)
            if search.category:
                lanes += [deque(narrower)] if narrower else []
            else:
                queue.extend(narrower)
        if len(found) < target:
            report(f"'{phrase}': {target - len(found)} of {target} hits not reached "
                   f"(more than one page at the narrowest search)")
        return list(found.values())


def _fetch_detail(session: PoliteSession, tid: str, teaser_html: str = "") -> dict:
    """The full description and apply route from the detail page.

    `/jobannonce/<tid>/` either serves the Jobindex-hosted ad or redirects to
    the employer's own page. On the employer's page the description is its
    JobPosting JSON-LD or, failing that, its main content (`_main_text`, when
    at least `_MIN_MAIN_TEXT` long), and the page itself is where to apply
    (``apply_type="external"``); an ad an applicant-tracking system renders with
    JavaScript is fetched from that system (`_ats_description`). Falls back to the search-result teaser when
    the request fails or nothing usable is found. When robots.txt is obeyed
    and the employer's disallows its page, the page is not read (an error is
    recorded) but is still where to apply.
    """
    url = _DETAIL_URL.format(tid=tid)
    try:
        resp = session.get(url, headers=_HEADERS)
    except RobotsBlocked as exc:
        report(f"{tid}: {exc}")
        record_error("jobindex", f"{tid}: {exc}")
        employer_url = _employer_url(exc.url)
        return {"description": _teaser_text(teaser_html), "apply_type": "external" if employer_url else None,
                "apply_url": employer_url}
    except Exception:
        return {"description": _teaser_text(teaser_html), "apply_type": None, "apply_url": None}
    employer_url = _employer_url(resp.url)
    description = _description_from_html(resp.text)
    if not description and employer_url:
        description = _ats_description(session, resp.url, resp.text)
    if not description and employer_url:
        main = _main_text(resp.text)
        description = main if len(main) >= _MIN_MAIN_TEXT else ""
    return {
        "description": description or _teaser_text(teaser_html),
        "apply_type": "external" if employer_url else None,
        "apply_url": employer_url,
    }


def _ats_description(session: PoliteSession, url: str, html: str) -> str:
    """The ad from the applicant-tracking system behind an employer page whose
    ad is rendered by JavaScript (so not in *html*); "" for any other page or
    on failure.

    HR-Manager (``candidate.hr-manager.net``): Jobindex links its application
    form, which shows the advertisement once the department/media parameters are
    dropped; its robots.txt allows that page. (HR-ON's embedded ads are not read:
    ``recruit.hr-on.com``'s robots.txt disallows everything.)
    """
    try:
        ad_url = _hr_manager_ad_url(url)
        if ad_url is not None:
            return _hr_manager_text(session.get(ad_url, headers=_HEADERS).text)
    except Exception:  # noqa: BLE001 - the teaser is the fallback, not an error
        return ""
    return ""


def _hr_manager_ad_url(url: str) -> str | None:
    """The advertisement for an HR-Manager application link (only ``cid`` and
    ``ProjectId`` kept), else ``None``. Pure."""
    parsed = urlparse(url)
    if parsed.netloc.lower() != "candidate.hr-manager.net" or not parsed.path.lower().endswith("/applicationinit.aspx"):
        return None
    query = {k.lower(): v[0] for k, v in parse_qs(parsed.query).items()}
    if "cid" not in query or "projectid" not in query:
        return None
    return f"https://candidate.hr-manager.net/ApplicationInit.aspx?cid={query['cid']}&ProjectId={query['projectid']}"


def _hr_manager_text(html: str) -> str:
    """The text of an HR-Manager advertisement (``#AdvertisementContent``); "" if absent. Pure."""
    container = BeautifulSoup(html, "html.parser").find(id="AdvertisementContent")
    return container.get_text(separator="\n", strip=True) if container is not None else ""


def _employer_url(url: str) -> str | None:
    """*url* when it is off Jobindex (the employer's own page), else ``None``. Pure."""
    host = urlparse(url or "").netloc.lower()
    if not host or host == "jobindex.dk" or host.endswith(".jobindex.dk"):
        return None
    return url


# The fewest characters of main content that pass for an ad: below it is page
# chrome (a JavaScript-rendered ad leaves only menus behind), and the teaser wins.
_MIN_MAIN_TEXT = 1000

# Elements that are never the ad: banners, menus, forms, embeds.
_CHROME_TAGS = ("script", "style", "noscript", "nav", "header", "footer", "form", "button", "iframe", "svg")
_CONSENT_RE = re.compile(r"cookie|consent|gdpr|onetrust|cookiebot", re.IGNORECASE)


def _main_text(html: str) -> str:
    """The text of a page's ``<main>`` (else ``<article>``, else ``<body>``),
    without menus, headers, footers, forms or cookie banners. Pure."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(list(_CHROME_TAGS)):
        tag.decompose()
    for tag in soup.find_all(lambda e: any(
        _CONSENT_RE.search(" ".join(v) if isinstance(v, list) else str(v))
        for k, v in (e.attrs or {}).items() if k in ("id", "class", "role", "aria-label")
    )):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body
    return root.get_text(separator="\n", strip=True) if root is not None else ""


def _description_from_html(html: str) -> str:
    """The ad text of a detail page, or "" when no known source is on it. Pure.

    Tries, in order: the Jobindex-hosted body (`jobtext-jobad__body` since Oct
    2026, `read-more` before; `jobcontent` for employer-branded ads), then the schema.org `JobPosting` JSON-LD most
    applicant-tracking systems put on the employer pages Jobindex redirects to.
    """
    soup = BeautifulSoup(html, "html.parser")
    container = (
        soup.find("section", class_="jobtext-jobad__body")
        or soup.find("section", class_="read-more-container")
        or soup.find("div", class_="read-more")
        or soup.find(class_="jobcontent")
    )
    if container:
        return container.get_text(separator="\n", strip=True)
    for script in soup.find_all("script", type="application/ld+json"):
        description = _json_ld_job_description(script.string or "")
        if description:
            # Some (TeamTailor) entity-escape the markup: unescape before stripping tags.
            return BeautifulSoup(html_lib.unescape(description), "html.parser").get_text(separator="\n", strip=True)
    return ""


def _json_ld_job_description(raw: str) -> str:
    """The `description` of the first `JobPosting` in a JSON-LD block; "" if none. Pure."""
    try:
        data = json.loads(raw)
    except ValueError:
        return ""
    nodes = data if isinstance(data, list) else (data.get("@graph") or [data]) if isinstance(data, dict) else []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        types = node.get("@type")
        if "JobPosting" in (types if isinstance(types, list) else [types]):
            description = node.get("description")
            if isinstance(description, str) and description.strip():
                return description
    return ""


def _teaser_text(html_snippet: str) -> str:
    if not html_snippet:
        return ""
    soup = BeautifulSoup(html_snippet, "html.parser")
    # Strip toolbar / share / nav elements to get just the job text.
    for tag in soup.find_all(class_=lambda c: c and any(
        kw in c for kw in ("jix_toolbar", "jix_appetizer_toolbar", "jix_share")
    )):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


def _area_for_profile(config: dict) -> str:
    """The Jobindex area for the profile's `location`; all of Denmark ("") for one
    the table does not know, rather than silently searching one region."""
    location = config.get("location", "").lower().strip()
    for key, area in _LOCATION_TO_AREA.items():
        if key in location:
            return area
    return ""


def _to_posting(raw: dict, description: str, scraped_at: datetime, apply_type: str | None = None,
                apply_url: str | None = None) -> dict:
    """Map one raw search result (plus its description and apply route) to a JobPosting dict."""
    tid = raw["tid"]  # e.g. "h1673146"
    title = raw.get("headline") or ""
    company = raw.get("companytext") or (raw.get("company") or {}).get("name") or ""  # some ads: "company": null
    share_url = raw.get("share_url") or f"{_BASE}/vis-job/{tid}"

    posted_at: datetime | None = None
    if raw.get("firstdate"):
        try:
            posted_at = datetime.fromisoformat(raw["firstdate"]).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    posting = JobPosting(
        id=make_job_id("jobindex", tid),
        title=title,
        company=company,
        location=raw.get("area") or "",
        url=share_url,
        description=description,
        source="jobindex",
        scraped_at=scraped_at,
        platform_id=tid,
        posted_at=posted_at,
        apply_type=apply_type,
        apply_url=apply_url,
    )
    return posting.model_dump(mode="json")


def iter_scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> Iterator[dict]:
    """Yield JobPosting-compatible dicts one at a time (issue #134).

    Same search -> per-hit detail-fetch logic as `scrape`, but incremental:
    each result is yielded as soon as it's ready instead of building the
    whole list first, so a caller consuming this generator (`_scrape_core`)
    can persist progress as it goes and survive a mid-run interruption.

    For a hit whose `tid` is already in `known_ids` (i.e. the caller's
    history store already has it and it's not due for a recheck), the slow
    `_fetch_detail` HTTP call is skipped entirely and a lightweight
    ``{"platform_id": tid, "seen_only": True}`` record is yielded instead of
    a full posting dict — the caller is expected to just touch the entry's
    `last_seen` in history for these, not write a new posting file.

    `max_pages_per_keyword` (config key, default `_MAX_PAGES`) bounds how
    many result pages are fetched per search. When robots.txt is obeyed, a page
    it disallows is never requested (every page after the first), and a full
    search is split instead (see the module docstring).
    """
    role_targets: list[str] = config.get("role_targets", [])
    # search_keywords broadens retrieval; fall back to role_targets when absent or empty.
    search_keywords: list[str] = config.get("search_keywords") or role_targets
    area = _area_for_profile(config)
    max_pages = config.get("max_pages_per_keyword", _MAX_PAGES)
    scraped_at = datetime.now(timezone.utc)

    session = PoliteSession(min_delay=_MIN_DELAY, max_delay=_MAX_DELAY, timeout=20, headers=_HEADERS)
    searcher = _Searcher(session, area, config.get("location", ""), max_pages)
    # Only a title on topic for the keywords earns a detail request (one or more fetches:
    # Jobindex, then often the employer's page); the rest keep their search teaser.
    topic = topic_terms(config)
    seen_tids: set[str] = set()

    phrases, skipped = _search_phrases(search_keywords)
    for keyword in skipped:
        report(f"'{keyword}': skipped (nothing left to search once seniority and function words go)")

    for n, phrase in enumerate(phrases, 1):
        report(phrase, n, len(phrases), stage="keyword_search")
        role_results: list[dict] = []
        for r in searcher.collect(phrase):
            if r["tid"] not in seen_tids:
                seen_tids.add(r["tid"])
                role_results.append(r)
        log_keyword_results("jobindex", phrase, role_results)

        for i, raw in enumerate(role_results, 1):
            report(phrase, i, len(role_results), stage="ad_details")
            tid = raw["tid"]

            if tid in known_ids:
                yield {"platform_id": tid, "seen_only": True}
                continue

            if topic and not on_topic(raw.get("headline") or "", topic):
                yield _to_posting(raw, _teaser_text(raw.get("html", "")), scraped_at, None, None)
                continue
            detail = _fetch_detail(session, tid, raw.get("html", ""))
            yield _to_posting(raw, detail["description"], scraped_at, detail["apply_type"], detail["apply_url"])

    if searcher.requests:
        report(f"{searcher.requests} search request{'' if searcher.requests == 1 else 's'}", site="jobindex")


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Return a list of JobPosting-compatible dicts for all matching jobs.

    A thin wrapper around `iter_scrape` — kept as a list-returning function
    so callers that don't need incremental consumption (and the existing
    fixture tests) have a simple contract; `_scrape_core` prefers
    `iter_scrape` directly when available so it can persist progress as it
    goes (issue #134).
    """
    return list(iter_scrape(config, known_ids, **kwargs))


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: page 1 of the first keyword, no detail fetches.

    Never records errors; ``None`` when no keyword is configured.
    """
    phrases, _ = _search_phrases(config.get("search_keywords") or config.get("role_targets") or [])
    if not phrases:
        return None
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)
    url = _search_url(phrases[0], _area_for_profile(config))

    def fetch() -> str:
        return session.get(url, headers=_HEADERS).text

    def parse(html: str):
        response, results = _parse_search(html)
        if response is None:
            return [], False, "no search results block on the page (Stash/result_app missing)"
        scraped_at = datetime.now(timezone.utc)
        return [_to_posting(r, _teaser_text(r.get("html", "")), scraped_at) for r in results if r.get("tid")], True, ""

    return run_probe(fetch, parse, "html")
