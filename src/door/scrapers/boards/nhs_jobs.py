#!/usr/bin/env python3
"""Scraper for NHS Jobs (jobs.nhs.uk), the UK health service's own job board (NHS England trusts and more).

Kind: a keyword board, plain HTTP, no login, server-rendered HTML. Endpoints:
- search ``GET https://www.jobs.nhs.uk/candidate/search/results?keyword=<kw>&location=<place>&sort=publicationDateDesc&page=<n>``:
  ``sort=publicationDateDesc`` is newest first, ``page`` is 1-based (10 ads a page), a ``Next`` link
  (``data-test=search-next-page``) leads on. Each result is a ``li[data-test=search-result]`` with the title link
  (``/candidate/jobadvert/<ref>``), the trust and its place (``London E13 8AL``: the postcode is dropped), the
  salary, the exact date posted (``3 November 2026``, with its year) and the contract type. The keyword search is
  loose (a "project manager" page is mostly nurses and clerks), so only on-topic titles (``on_topic``) cost an ad
  request. ``location=`` narrows the list to the place; it is sent for a profile city The other door knows,
  otherwise the cards are filtered on their location text (``sdk.location_fits``: the city, its commute area,
  remote and unknown places stay);
- ad ``GET https://www.jobs.nhs.uk/candidate/jobadvert/<ref>`` - the job summary, main duties and job description
  (``#job_overview``, ``#job_description``, ``#job_description_large``), the exact date (``#date_posted``) and the
  job's own place (``#employer_town``, ``#employer_county`` under "Job locations"): the card's place is the
  trust's, so the ad's place replaces it and is checked against the profile again (an ad elsewhere is dropped).

The list is newest first, so a keyword stops at the first card posted before ``since``. A card whose title is not
on topic, whose location does not suit the profile, or whose id is in ``known_ids`` (a ``seen_only`` record) costs
no ad request. A keyword reads pages until there is no ``Next`` link, at most ``max_pages_per_keyword`` (default
3). An ad whose page cannot be read keeps a description built from its card, and the failure is recorded. No
language filter: the board is in English (Welsh NHS ads are on a separate route).

A 403 or 429 (after the session's backoff) or a challenge page is pushback: it is recorded with
``record_pushback`` and the run stops.

Terms: the candidate pages link no terms of their own; the service's terms are
https://api.jobs.nhs.uk/employer/terms-and-conditions (NHS Business Services Authority, last updated 22 July
2025). Clause 10.2: "Most of the content on the NHS Jobs website is published under the Open Government Licence
(OGL) for public sector information. This means you may use and re-use the information featured on this website
free of charge, in any format or medium, as long as you follow the licence's conditions." 10.2.1: "If you do use
our content; you must reference where you copied it from by using links to this website." (every posting keeps
its link to the ad). 10.3: "External recruitment platforms may take a feed of live vacancies, displayed on NHS
Jobs, and advertise them on their own platforms." No clause on bots, scraping, automated access or text-and-data
mining (checked 2026-11-03). robots.txt: none (the host answers a generic page) (checked 2026-11-03).
"""

import re
from datetime import datetime, timezone
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from door.scrapers import sdk
from door.scrapers.sdk import (
    FEED_DELAY, JobPosting, PROBE_TIMEOUT_S, PoliteSession, ProbeResult, log_keyword_results, make_job_id,
    on_topic, record_answered, record_error, record_pushback, report, run_probe, topic_terms,
)

_SITE = "nhs_jobs"
_BASE = "https://www.jobs.nhs.uk"
_MAX_PAGES = 3

_MIN_DELAY, _MAX_DELAY = FEED_DELAY

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

# Hosts of this board: a link here is an ad on the board, never an employer's own site (`ats_detect.is_job_board`).
JOB_BOARD_HOSTS = ("jobs.nhs.uk",)

_CHALLENGE_MARKERS = ("just a moment", "cdn-cgi/challenge-platform", "attention required", "cf-chl", "cf-browser-verification")
_POSTCODE = re.compile(r"\s*\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b")
_DATE = re.compile(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})")
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


class _Pushback(Exception):
    """The site refused the request (a 403/429 or a challenge page); the run stops."""


def _search_url(keyword: str, location: str, page: int = 1) -> str:
    """The newest-first search URL of *keyword*; the place named first in *location* is sent when it is a city
    The other door knows. Pure."""
    url = f"{_BASE}/candidate/search/results?keyword={quote_plus(keyword.strip())}"
    place = (location or "").split(",")[0].strip()
    if place and sdk.known_city(place):
        url += f"&location={quote_plus(place)}"
    return f"{url}&sort=publicationDateDesc&page={page}"


def _clean_location(text: str) -> str:
    """A card's place without its postcodes (``London E13 8AL`` -> ``London``). Pure."""
    return _POSTCODE.sub("", re.sub(r"\s+", " ", text or "").strip()).strip()


def _parse_date(text: str) -> datetime | None:
    """``3 November 2026`` (the month in full or three letters) as a date; None when it is not one. Pure."""
    m = _DATE.search(text or "")
    month = _MONTHS.get(m.group(2)[:3].lower()) if m else None
    if not m or not month:
        return None
    try:
        return datetime(int(m.group(3)), month, int(m.group(1)))
    except ValueError:
        return None


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ")).strip() if node is not None else ""


def _value(block, test: str) -> str:
    """The bold value of a ``li[data-test=<test>]`` in a card (``Salary: <strong>...``)."""
    return _text(block.select_one(f"[data-test={test}] strong"))


def _parse_cards(html: str) -> list[dict] | None:
    """The cards of a search page; None when neither results nor the results heading are on it. Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    blocks = soup.select("li[data-test=search-result]")
    if not blocks and soup.select_one("[data-test=search-result-query]") is None:
        return None
    cards = []
    for block in blocks:
        link = block.select_one("a[data-test=search-result-job-title]")
        title = _text(link)
        href = (link.get("href") or "") if link is not None else ""
        pid = href.split("/jobadvert/", 1)[-1].split("?")[0] if "/jobadvert/" in href else ""
        if not pid or not title:
            continue
        place = block.select_one("[data-test=search-result-location]")
        where = place.select_one(".location-font-size") if place is not None else None
        heading = place.select_one("h3") if place is not None else None
        company = next((_text(t) for t in heading.find_all(string=True, recursive=False) if t.strip()), "") if heading is not None else ""
        cards.append({
            "id": pid,
            "title": title,
            "url": f"{_BASE}/candidate/jobadvert/{pid}",
            "company": company,
            "location": _clean_location(_text(where)),
            "salary": _value(block, "search-result-salary"),
            "contract": _value(block, "search-result-jobType"),
            "posted": _parse_date(_value(block, "search-result-publicationDate")),
        })
    return cards


def _has_next(html: str) -> bool:
    """Whether the page links to a next page. Pure."""
    return BeautifulSoup(html or "", "html.parser").select_one("a[data-test=search-next-page]") is not None


def _html_text(html: str) -> str:
    """Plain text of an HTML fragment: one line per block element, inline markup kept in its line. Pure."""
    broken = re.sub(r"(</(?:p|li|h\d|div|ul|ol|tr)>|<br\s*/?>)", r"\1\n", html)
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in BeautifulSoup(broken, "html.parser").get_text("").splitlines())
    return "\n".join(line for line in lines if line)


def _job_place(soup) -> str:
    """The job's own place on an ad page (``Birmingham, West Midlands``: the town and the county of its "Job
    locations" address, which the page prints twice, for phone and desktop); "" when it names none. Not the
    trust's address on the search card. Pure."""
    towns = []
    for town, county in zip(soup.find_all(id="employer_town"), soup.find_all(id="employer_county")):
        place = ", ".join(t for t in (_text(town), _text(county)) if t)
        if place and place not in towns:
            towns.append(place)
    return "; ".join(towns)


def _parse_detail(html: str) -> dict | None:
    """``{"description", "posted", "location"}`` of an ad page (plain text of the summary, duties and job
    description; the exact date or None; the job's own place or ""); None when the page has no description. Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    parts = []
    for node_id in ("job_overview", "job_description", "job_description_large", "about_organisation"):
        node = soup.find(id=node_id)
        text = _html_text(node.decode_contents()) if node is not None else ""
        if text and text not in parts:
            parts.append(text)
    if not parts:
        return None
    posted = soup.find(id="date_posted")
    return {"description": "\n".join(parts), "posted": _parse_date(_text(posted)), "location": _job_place(soup)}


def _card_text(card: dict) -> str:
    """A description from a card alone (the fallback when the ad page cannot be read)."""
    parts = [card["title"], card["company"]]
    for label, key in (("Location", "location"), ("Salary", "salary"), ("Contract", "contract")):
        if card[key]:
            parts.append(f"{label}: {card[key]}")
    return ". ".join(p for p in parts if p)


def _is_challenge(body: str, status: int) -> bool:
    """Whether an answer is a refusal or a challenge page, not the site. Pure."""
    if status in (403, 429):
        return True
    head = (body or "")[:6000].lower()
    return any(marker in head for marker in _CHALLENGE_MARKERS)


def _get(session: PoliteSession, url: str) -> str:
    """The page at *url*. Raises `_Pushback` on a refusal or a challenge, the request's own error otherwise."""
    try:
        resp = session.get(url)
    except requests.HTTPError as exc:
        status = getattr(exc.response, "status_code", 0)
        if _is_challenge("", status):
            raise _Pushback(f"HTTP {status}") from exc
        raise
    if _is_challenge(resp.text, resp.status_code):
        raise _Pushback("challenge page")
    return resp.text


def _posting(card: dict, description: str, posted: datetime | None, scraped_at: datetime) -> dict:
    return JobPosting(
        id=make_job_id(_SITE, card["id"]),
        title=card["title"],
        company=card["company"],
        location=card["location"],
        url=card["url"],
        description=description,
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=card["id"],
        posted_at=posted,
    ).model_dump(mode="json")


def _pushback(message: str) -> None:
    report(f"{_SITE}: {message}; stopping for this run")
    record_error(_SITE, f"{_SITE}: {message}; stopped for this run")
    record_pushback(_SITE)


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """JobPosting dicts for the on-topic ads of every search keyword (``seen_only`` records for known ids)."""
    keywords: list[str] = config.get("search_keywords") or config.get("role_targets") or []
    location = config.get("location", "")
    max_pages = int(config.get("max_pages_per_keyword", _MAX_PAGES))
    since = kwargs.get("since")
    since_day = since.date() if since is not None else None
    topic = topic_terms(config)
    scraped_at = datetime.now(timezone.utc)
    session = PoliteSession(min_delay=_MIN_DELAY, max_delay=_MAX_DELAY, timeout=20, headers=_HEADERS)
    seen: set[str] = set()
    out: list[dict] = []

    for keyword in keywords:
        start = len(out)
        done = False
        for page in range(1, max_pages + 1):
            try:
                html = _get(session, _search_url(keyword, location, page))
            except _Pushback as exc:
                _pushback(str(exc))
                return out
            except Exception as exc:  # noqa: BLE001 - one bad page never stops the run
                report(f"search error (keyword={keyword!r}, page={page}): {exc}")
                record_error(_SITE, f"search error (keyword={keyword!r}, page={page}): {exc}")
                break
            cards = _parse_cards(html)
            if cards is None:
                report(f"no search results block on page (keyword={keyword!r}, page={page})")
                record_error(_SITE, f"no search results block on page (keyword={keyword!r}, page={page})")
                break
            if not cards:
                record_answered(_SITE)

            for card in cards:
                placed = card["posted"]
                if since_day is not None and placed is not None and placed.date() < since_day:
                    done = True  # newest first: every later card is older too
                    break
                if card["id"] in seen or (topic and not on_topic(card["title"], topic)):
                    continue
                if not sdk.location_fits(card["location"], config) or not sdk.keep_local(
                        [{"location": card["location"]}], config, _SITE):
                    continue
                seen.add(card["id"])
                if card["id"] in known_ids:
                    out.append({"platform_id": card["id"], "seen_only": True})
                    continue
                report(f"'{keyword}' details", len(out) - start + 1, len(cards))
                detail = None
                try:
                    detail = _parse_detail(_get(session, card["url"]))
                    if detail is None:
                        raise ValueError("no JobPosting data on the page")
                except _Pushback as exc:
                    _pushback(str(exc))
                    return out
                except Exception as exc:  # noqa: BLE001 - the card is the fallback
                    report(f"detail error ({card['url']}): {exc}")
                    record_error(_SITE, f"detail error ({card['url']}): {exc}")
                description = detail["description"] if detail else _card_text(card)
                posted = (detail or {}).get("posted") or placed
                # The card shows the trust's place; the ad names where the job is: it wins, and is checked again.
                own = (detail or {}).get("location") or ""
                if own:
                    card = {**card, "location": own}
                    if not sdk.location_fits(own, config) or not sdk.keep_local([{"location": own}], config, _SITE):
                        continue
                out.append(_posting(card, description, posted, scraped_at))

            if done or not cards or not _has_next(html):
                break
        log_keyword_results(_SITE, keyword, [p for p in out[start:] if not p.get("seen_only")])
    return out


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: page 1 of the first keyword, no ad requests.

    ``raw`` is the page's HTML. Never records errors; ``None`` when no keyword is configured.
    """
    keywords = config.get("search_keywords") or config.get("role_targets") or []
    if not keywords:
        return None
    session = PoliteSession(min_delay=_MIN_DELAY, max_delay=_MAX_DELAY, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)
    url = _search_url(keywords[0], config.get("location", ""), 1)

    def fetch() -> str:
        return session.get(url).text

    def parse(html: str):
        if _is_challenge(html, 200):
            return [], False, "bot-wall: a challenge page"
        cards = _parse_cards(html)
        if cards is None:
            return [], False, "no search results block (li[data-test=search-result], search-result-query) on the page"
        scraped_at = datetime.now(timezone.utc)
        return [_posting(c, _card_text(c), c["posted"], scraped_at) for c in cards], True, ""

    result = run_probe(fetch, parse, "html")
    if str(result.get("reason", "")).startswith("bot-wall"):
        result["wall"] = True
    return result
