#!/usr/bin/env python3
"""Scraper for Choisir le service public (choisirleservicepublic.gouv.fr), the French civil service's job site.

Kind: a keyword board, plain HTTP, no login, no API key. It lists the ads of the three branches of the
civil service (State, local authorities, hospitals): ministries, universities, research bodies, towns,
departments, hospitals. Many of those employers have no applicant-tracking feed, so the board is the
route. The ads are French, a few English (research posts, international posts). Endpoints:
- search ``GET https://choisirleservicepublic.gouv.fr/nos-offres/filtres/mot-cles/<keyword>/
  [localisation/<id>/][page/<n>/]`` - server-rendered HTML, 20 cards per page (``div.fr-card--offer``:
  title and ad link, field tag, place, branch, employer, "En ligne depuis le 25 octobre 2026"; a local
  authority's ad is filed under a category ("Communes", "Conseils départementaux") and named by the last
  " - " part of its title). The
  keyword search is fuzzy (it stems: "engineer" finds "engins", "english" finds "Englos") and ranks by
  relevance, so the on-topic ads come first and unrelated ones follow, 200 pages deep. A page links its
  next one in ``a.fr-pagination__link--next``. ``localisation/<id>`` is the site's own place filter:
  the id of a region or a department (``_LOCATION_IDS``: Île-de-France for Paris, the department for the
  other cities; a city not in the table searches the whole country). The site has no date filter and no
  sort: ``since`` is left to the engine, which drops older ads after the scrape;
- ad ``GET <the card's link>`` (``/offre-emploi/<slug>-reference-<ref>/``) - the full text is in the page
  (``div.col-left.rte``: missions, profile, skills; the same text is in its JSON-LD ``JobPosting`` as a
  single run-on line, the fallback). Employer and place are in the header list.

A card whose title is not on topic for the profile's keywords (``on_topic``) costs no ad request, nor does
an id in ``known_ids`` (a ``seen_only`` record). A keyword reads pages while the next link is there and
the page held an on-topic card (the ranking puts them first), at most ``max_pages_per_keyword`` (default
3). ``posted_at`` is the card's date. A 403 or 429 (after the session's backoff) is pushback: it is
recorded with ``record_pushback`` and the run stops.

Terms: https://choisirleservicepublic.gouv.fr/mentions-legales/ (checked 2026-10-31) - no clause on bots,
scraping or text-and-data mining; the footer says "Sauf mention contraire, tous les textes de ce site sont
sous licence etalab-2.0". No ``tdm`` text on the page or the legal page.
robots.txt (checked 2026-10-31) disallows ``/wp-admin/`` and ``/wp-content/uploads/pdf-offers/`` only.
"""

import html as html_lib
import json
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from door.scrapers.sdk import (
    FEED_DELAY, JobPosting, PROBE_TIMEOUT_S, PoliteSession, ProbeResult, city_names, log_keyword_results,
    make_job_id, on_topic, record_error, record_pushback, report, run_probe, topic_terms,
)

_SITE = "choisirleservicepublic"
_BASE = "https://choisirleservicepublic.gouv.fr"
_MAX_PAGES = 3

# Pause between requests: the employer feeds' (one host, one at a time).
_MIN_DELAY, _MAX_DELAY = FEED_DELAY

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

# Hosts of this board: a link here is an ad on the board, never an employer's own site (`ats_detect.is_job_board`).
JOB_BOARD_HOSTS = ("choisirleservicepublic.",)

# The city (as written in `i18n/country/fr.toml`) -> the id of the site's `localisation` filter: the region
# Île-de-France for Paris (its suburbs are in it), the department for the others.
_LOCATION_IDS: dict[str, str] = {
    "paris": "208", "lyon": "336", "toulouse": "305", "marseille": "326", "lille": "310", "bordeaux": "239",
    "nantes": "312", "nice": "325", "strasbourg": "236", "rennes": "256", "grenoble": "334", "montpellier": "292",
}
_MONTHS = {m: n for n, m in enumerate(
    ["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre", "octobre", "novembre", "decembre"], 1)}
_LONG_DATE = re.compile(r"(\d{1,2})(?:er)?\s+([a-zéûè]+)\s+(\d{4})", re.I)
_NUM_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_REFERENCE = re.compile(r"-reference-([^/?#]+)/?$")
_LOCAL_REFERENCE = re.compile(r"^O\d{6,}")


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "") if unicodedata.category(c) != "Mn").lower()


def _location_id(location: str | None) -> str | None:
    """The id of the site's place filter for the city a `location` names (its suburbs and districts
    included), or None: an unknown place searches the whole country. Pure."""
    if not location:
        return None
    names = {n.lower() for n in city_names(location)}
    for city, code in _LOCATION_IDS.items():
        if city in names:
            return code
    return None


def _search_url(keyword: str, location_id: str | None, page: int) -> str:
    url = f"{_BASE}/nos-offres/filtres/mot-cles/{quote(keyword, safe='')}/"
    if location_id:
        url += f"localisation/{location_id}/"
    if page > 1:
        url += f"page/{page}/"
    return url


def _platform_id(url: str) -> str | None:
    """The reference at the end of an ad link (``...-reference-2026-2452785/``), or None. Pure."""
    m = _REFERENCE.search(url or "")
    return m.group(1) if m else None


def _parse_date(text: str | None) -> datetime | None:
    """The day of "En ligne depuis le 25 octobre 2026", "1er août 2026" or "28/09/2026" (naive, midnight); None
    for anything else. Pure."""
    t = _fold(text or "")
    try:
        m = _NUM_DATE.search(t)
        if m:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        m = _LONG_DATE.search(t)
        if m and m.group(2) in _MONTHS:
            return datetime(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)))
    except ValueError:
        return None
    return None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _item_text(li) -> str:
    """The text of a list item without its screen-reader label ("Localisation : ")."""
    for label in li.select(".sr-only"):
        label.extract()
    return _clean(li.get_text(" ", strip=True))


def _company(platform_id: str, title: str, employer: str) -> str:
    """The employer's name. A local authority's ad (reference ``O<department><date>...``) is filed under a category
    ("Communes", "Conseils départementaux"); the town or body is the last " - " part of its title. Pure."""
    if _LOCAL_REFERENCE.match(platform_id) and " - " in title:
        name = title.rsplit(" - ", 1)[1].strip()
        if name:
            return name
    return employer


def _parse_cards(html: str) -> list[dict]:
    """The result cards of a search page: ``id``, ``url``, ``title``, ``company`` (the employer; a local authority's ad is named by its title's suffix), ``location``
    ("Paris (75)", "France"), ``published`` (the date's text). A card without an ad link is skipped. Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    cards = []
    for card in soup.select("div.fr-card--offer"):
        link = card.select_one("h3 a[href]")
        pid = _platform_id(link["href"]) if link is not None else None
        title = _clean(link.get_text(" ", strip=True)) if link is not None else ""
        if not pid or not title:
            continue
        place = card.select_one("li.fr-icon-map-pin-2-line")
        employer = card.select_one("li.fr-icon-user-line")
        date = card.select_one("li.fr-icon-calendar-line")
        cards.append({
            "id": pid,
            "url": link["href"].strip(),
            "title": title,
            "company": _company(pid, title, _item_text(employer) if employer is not None else ""),
            "location": _item_text(place) if place is not None else "",
            "published": _item_text(date) if date is not None else "",
        })
    return cards


def _has_next(html: str) -> bool:
    """Whether the page links to the next page of results. Pure."""
    return BeautifulSoup(html or "", "html.parser").select_one("a.fr-pagination__link--next[href]") is not None


def _is_results_page(html: str) -> bool:
    """Whether a page is the search's answer: a result list, or the "no offers" answer (an empty one). Pure."""
    h = html or ""
    return "js-results" in h or "fr-card--offer" in h


def _json_ld(soup) -> dict:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return {}


def _parse_detail(page: str) -> dict | None:
    """``description`` (plain text: missions, profile, skills), ``company`` and ``location`` from an ad page;
    None when it has no ad text. Pure."""
    soup = BeautifulSoup(page or "", "html.parser")
    ld = _json_ld(soup)
    body = soup.select_one("div.col-left.rte")
    text = ""
    if body is not None:
        for noise in body.select("button, .block-cards, script, style"):
            noise.decompose()
        blocks = [_clean(e.get_text(" ", strip=True)) for e in body.find_all(["h2", "h3", "h4", "p", "li"])]
        text = "\n".join(b for b in blocks if b)
    if not text:
        text = html_lib.unescape(str(ld.get("Description") or "")).strip()
    if not text:
        return None
    employer = soup.select_one("li.ic--user")
    company = ""
    if employer is not None:
        for label in employer.select(".sr-only"):
            label.extract()
        company = next((_clean(s) for s in employer.stripped_strings), "")
    company = company or _clean(str(ld.get("hiringOrganization") or ""))
    place = soup.select_one("li.ic--pin")
    location = _item_text(place) if place is not None else ""
    return {"description": text, "company": company, "location": location}


def _posting(card: dict, detail: dict, scraped_at: datetime) -> dict:
    return JobPosting(
        id=make_job_id(_SITE, card["id"]),
        title=card["title"],
        company=card["company"] or detail["company"],
        location=card["location"] or detail["location"],
        url=card["url"],
        description=detail["description"],
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=card["id"],
        posted_at=_parse_date(card["published"]),
    ).model_dump(mode="json")


def _card_posting(card: dict, scraped_at: datetime | None = None) -> dict:
    """A posting from a search card alone (the probe's): the title and the employer stand in for the text."""
    text = ". ".join(x for x in (card["title"], card["company"]) if x)
    return _posting(card, {"description": text, "company": "", "location": ""}, scraped_at or datetime.now(timezone.utc))


def _pushback(message: str) -> None:
    report(f"{_SITE}: {message}; stopping for this run")
    record_error(_SITE, f"{_SITE}: {message}; stopped for this run")
    record_pushback(_SITE)


def _refused(exc: requests.HTTPError) -> bool:
    return getattr(exc.response, "status_code", 0) in (403, 429)


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """JobPosting dicts for the on-topic ads of every search keyword (``seen_only`` records for known ids)."""
    keywords: list[str] = config.get("search_keywords") or config.get("role_targets") or []
    max_pages = int(config.get("max_pages_per_keyword", _MAX_PAGES))
    topic = topic_terms(config)
    scraped_at = datetime.now(timezone.utc)
    place = _location_id(config.get("location") or "")
    session = PoliteSession(min_delay=_MIN_DELAY, max_delay=_MAX_DELAY, timeout=30, headers=_HEADERS)
    seen: set[str] = set()
    out: list[dict] = []

    for keyword in keywords:
        start = len(out)
        for page in range(1, max_pages + 1):
            try:
                html = session.get(_search_url(keyword, place, page)).text
            except requests.HTTPError as exc:
                if _refused(exc):
                    _pushback(f"HTTP {exc.response.status_code}")
                    return out
                report(f"search error (keyword={keyword!r}, page={page}): {exc}")
                record_error(_SITE, f"search error (keyword={keyword!r}, page={page}): {exc}")
                break
            except Exception as exc:  # noqa: BLE001 - one bad page never stops the run
                report(f"search error (keyword={keyword!r}, page={page}): {exc}")
                record_error(_SITE, f"search error (keyword={keyword!r}, page={page}): {exc}")
                break
            if not _is_results_page(html):
                record_error(_SITE, f"search (keyword={keyword!r}, page={page}): no result list on the page (the site may have changed)")
                break

            cards = _parse_cards(html)
            relevant = [c for c in cards if not topic or on_topic(c["title"], topic)]
            for card in relevant:
                if card["id"] in seen:
                    continue
                seen.add(card["id"])
                if card["id"] in known_ids:
                    out.append({"platform_id": card["id"], "seen_only": True})
                    continue
                report(f"'{keyword}' details", len(out) - start + 1, len(relevant))
                try:
                    detail = _parse_detail(session.get(card["url"]).text)
                except requests.HTTPError as exc:
                    if _refused(exc):
                        _pushback(f"HTTP {exc.response.status_code}")
                        return out
                    record_error(_SITE, f"detail error ({card['id']}): {exc}")
                    continue
                except Exception as exc:  # noqa: BLE001
                    record_error(_SITE, f"detail error ({card['id']}): {exc}")
                    continue
                if detail is None:
                    record_error(_SITE, f"detail error ({card['id']}): no ad text on the page")
                    continue
                out.append(_posting(card, detail, scraped_at))

            # The ranking puts the on-topic ads first: a page without one ends the keyword.
            if not relevant or not _has_next(html):
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
    url = _search_url(keywords[0], _location_id(config.get("location") or ""), 1)

    def fetch() -> str:
        return session.get(url).text

    def parse(html: str):
        if not _is_results_page(html):
            return [], False, "no result list and no 'no offers' answer on the page"
        cards = _parse_cards(html)
        if not cards and "fr-card--offer" in html:
            return [], False, "result cards without an ad link"
        scraped_at = datetime.now(timezone.utc)
        return [_card_posting(c, scraped_at) for c in cards], True, ""

    return run_probe(fetch, parse, "html")
