#!/usr/bin/env python3
"""Scraper for France Travail (candidat.francetravail.fr), France's public employment service.

Kind: a keyword board, plain HTTP, no login. Its search also lists the ads of partner boards
(HelloWork, Meteojob, APEC, ...) and of employers who post directly, so one search covers most of the
French market. Endpoints:
- search ``GET https://candidat.francetravail.fr/offres/recherche?motsCles=<kw>&lieux=<INSEE commune>
  &offresPartenaires=true&rayon=10&tri=1&emission=<days>[&range=20-39]`` - server-rendered HTML, newest
  first, 20 cards per page (``li[data-id-offre]``: id, title, company and place, a ~200 character teaser,
  the contract, a relative date "Publié il y a 2 jours" and the origin logo). A page carries a link
  "Afficher les 20 offres suivantes" while more follow. ``lieux`` is the INSEE code of the profile's city
  (``_INSEE``; a city not in the table searches the whole country), ``emission`` the look-back in days
  (1, 3, 7, 14 or 31: the smallest that covers ``since``). It is always sent: a keyword that is a known
  job title ("comptable") is otherwise redirected to a fixed page that drops the partner ads and the
  ``range`` paging;
- description ``GET https://candidat.francetravail.fr/api-descriptifoffre/offre/<id>`` - the JSON that the
  ad page's own description component loads for a logged-out visitor (the page itself carries no text):
  ``descriptif`` (the ad), ``descriptionEntreprise``, ``etablissement.libelleEnseigne`` (the employer; an
  anonymous ad says "Enseigne non disponible"), ``lieuTravail``. No contact data is read or kept (the
  reuse licence excludes it). The ad's link is its page, ``/offres/recherche/detail/<id>``.

A card whose title is not on topic for the profile's keywords (``on_topic``) costs no description request,
nor does an id in ``known_ids`` (a ``seen_only`` record). A keyword reads pages while the next link is
there, at most ``max_pages_per_keyword`` (default 3). ``posted_at`` is the card's relative date, accurate
to the day (the JSON only has a last-modified date). A 403 or 429 (after the session's backoff) is
pushback: it is recorded with ``record_pushback`` and the run stops.

Terms: https://www.francetravail.fr/informations/informations-legales-et-conditio/conditions-generales-dutilisatio.html
(checked 2026-10-31) - no clause on bots, scraping or text-and-data mining; "Ces offres pourront être
réutilisées pour tout usage et notamment être rediffusées sur des sites tiers" (contact data excepted).
No TDM-Reservation header, no ``/.well-known/tdmrep.json``, no TDM meta tag.
robots.txt (checked 2026-10-31) disallows ``*motsCles=*`` for every agent; it is reported, not a gate
(``http_client.OBEY_ROBOTS``).
"""

import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from door.scrapers.sdk import (
    FEED_DELAY, JobPosting, PROBE_TIMEOUT_S, PoliteSession, ProbeResult, city_names, log_keyword_results,
    make_job_id, on_topic, record_answered, record_error, record_pushback, report, run_probe, topic_terms,
)

_SITE = "francetravail"
_BASE = "https://candidat.francetravail.fr"
_MAX_PAGES = 3
_PAGE_SIZE = 20
_RADIUS_KM = 10

# Pause between requests: the employer feeds' (one host, one at a time).
_MIN_DELAY, _MAX_DELAY = FEED_DELAY

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}
_JSON_HEADERS = {"Accept": "application/json", "Accept-Language": _HEADERS["Accept-Language"]}

# Hosts of this board: a link here is an ad on the board, never an employer's own site (`ats_detect.is_job_board`).
JOB_BOARD_HOSTS = ("francetravail.", "pole-emploi.")

# The city (as written in `i18n/country/fr.toml`) -> its INSEE commune code, which the search's `lieux` takes.
_INSEE: dict[str, str] = {
    "paris": "75056", "lyon": "69123", "toulouse": "31555", "marseille": "13055", "lille": "59350",
    "bordeaux": "33063", "nantes": "44109", "nice": "06088", "strasbourg": "67482", "rennes": "35238",
    "grenoble": "38185", "montpellier": "34172",
}
_EMISSIONS = (1, 3, 7, 14)
_MAX_EMISSION = 31
_MONTHS = {m: n for n, m in enumerate(
    ["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre", "octobre", "novembre", "decembre"], 1)}
_AGO = re.compile(r"il y a\s+(\d+)\s+jour", re.I)
_LONG_DATE = re.compile(r"(\d{1,2})(?:er)?\s+([a-zéûè]+)\s+(\d{4})", re.I)
_NUM_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_ANONYMOUS = "enseigne non disponible"


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text or "") if unicodedata.category(c) != "Mn").lower()


def _insee_code(location: str | None) -> str | None:
    """The INSEE commune code of the city a `location` names (its suburbs and districts included),
    or None: an unknown place searches the whole country. Pure."""
    if not location:
        return None
    names = {n.lower() for n in city_names(location)}
    for city, code in _INSEE.items():
        if city in names:
            return code
    return None


def _emission_days(since: datetime | None, now: datetime) -> int:
    """The smallest look-back the search offers (1, 3, 7, 14 or 31 days) that covers `since`; 31 without one. Pure."""
    if since is None:
        return _MAX_EMISSION
    if since.tzinfo is not None:
        since = since.astimezone().replace(tzinfo=None)
    days = max(1, -(-int((now - since).total_seconds()) // 86400))
    return next((d for d in _EMISSIONS if days <= d), _MAX_EMISSION)


def _search_url(keyword: str, insee: str | None, emission: int, page: int) -> str:
    url = f"{_BASE}/offres/recherche?motsCles={quote_plus(keyword)}"
    if insee:
        url += f"&lieux={insee}&offresPartenaires=true&rayon={_RADIUS_KM}"
    else:
        url += "&offresPartenaires=true"
    url += f"&tri=1&emission={emission}"
    if page > 1:
        url += f"&range={(page - 1) * _PAGE_SIZE}-{page * _PAGE_SIZE - 1}"
    return url


def _ad_url(platform_id: str) -> str:
    return f"{_BASE}/offres/recherche/detail/{platform_id}"


def _detail_url(platform_id: str) -> str:
    return f"{_BASE}/api-descriptifoffre/offre/{platform_id}"


def _parse_published(text: str | None, today: datetime) -> datetime | None:
    """The day of "Publié aujourd'hui", "hier", "il y a N jours", "le 12 octobre 2026" or "le 05/10/2026"
    (naive, midnight), counted from `today`; None for anything else. Pure."""
    t = _fold(text or "")
    day = datetime(today.year, today.month, today.day)
    if "aujourd" in t:
        return day
    if "hier" in t:
        return day - timedelta(days=1)
    m = _AGO.search(t)
    if m:
        return day - timedelta(days=int(m.group(1)))
    m = _NUM_DATE.search(t)
    try:
        if m:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        m = _LONG_DATE.search(t)
        if m and m.group(2) in _MONTHS:
            return datetime(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)))
    except ValueError:
        return None
    return None


def _clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text or "").strip()


def _parse_cards(html: str) -> list[dict]:
    """The result cards of a search page: ``id``, ``url``, ``title``, ``company`` ("" for an anonymous ad),
    ``location`` ("75 - Paris 8e Arrondissement"), ``teaser``, ``origin`` (the board that listed it) and
    ``published`` (the relative date's text). Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    cards = []
    for li in soup.select("li[data-id-offre]"):
        pid = (li.get("data-id-offre") or "").strip()
        title = li.select_one(".media-heading-title")
        if not pid or title is None:
            continue
        sub = li.select_one("p.subtext")
        place = sub.find("span") if sub is not None else None
        company = ""
        if sub is not None and place is not None:
            company = re.sub(r"\s*-\s*$", "", _clean("".join(sub.find_all(string=True, recursive=False))))
        elif sub is not None:
            company = _clean(sub.get_text(" ", strip=True))
        logo = li.select_one("img[alt^='Origine']")
        origin = _clean(logo["alt"].split(":", 1)[-1]) if logo is not None else ""
        desc = li.select_one("p.description")
        date = li.select_one("p.date")
        cards.append({
            "id": pid,
            "url": _ad_url(pid),
            "title": _clean(title.get_text(" ", strip=True)),
            "company": company,
            "location": _clean(place.get_text(" ", strip=True)) if place is not None else "",
            "teaser": desc.get_text().strip() if desc is not None else "",
            "origin": origin,
            "published": _clean(date.get_text(" ", strip=True)) if date is not None else "",
        })
    return cards


def _has_more(html: str) -> bool:
    """Whether the page links to the next 20 offers. Pure."""
    return "afficherplusderesultats" in (html or "")


def _is_results_page(html: str) -> bool:
    """Whether a page is the search's answer: a result list, or the "no offers" answer. Pure."""
    h = html or ""
    return "result-list" in h or "data-id-offre" in h or "zone-resultats" in h


def _parse_detail(body: str) -> dict | None:
    """``description`` (plain text: the ad, then the employer's blurb), ``company`` ("" when the ad is
    anonymous) and ``location`` from a description JSON; None when it has no ad text. Pure."""
    try:
        data = json.loads(body or "")
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    text = str(data.get("descriptif") or "").strip()
    if not text:
        return None
    blurb = str(data.get("descriptionEntreprise") or "").strip()
    if blurb:
        text = f"{text}\n\n{blurb}"
    shop = data.get("etablissement")
    company = str((shop or {}).get("libelleEnseigne") or "").strip() if isinstance(shop, dict) else ""
    if company.lower() == _ANONYMOUS:
        company = ""
    place = data.get("lieuTravail")
    location = str((place or {}).get("syntheseLieuTravail") or "").strip() if isinstance(place, dict) else ""
    return {"description": text, "company": company, "location": location}


def _posting(card: dict, detail: dict, today: datetime, scraped_at: datetime) -> dict:
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
        posted_at=_parse_published(card["published"], today),
    ).model_dump(mode="json")


def _card_posting(card: dict, today: datetime, scraped_at: datetime) -> dict:
    """A posting from a search card alone (the probe's): its teaser is the description."""
    return _posting(card, {"description": card["teaser"], "company": "", "location": ""}, today, scraped_at)


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
    now = datetime.now()
    scraped_at = datetime.now(timezone.utc)
    insee = _insee_code(config.get("location") or "")
    emission = _emission_days(kwargs.get("since"), now)
    session = PoliteSession(min_delay=_MIN_DELAY, max_delay=_MAX_DELAY, timeout=20, headers=_HEADERS)
    seen: set[str] = set()
    out: list[dict] = []

    for keyword in keywords:
        start = len(out)
        for page in range(1, max_pages + 1):
            try:
                html = session.get(_search_url(keyword, insee, emission, page)).text
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
            if not cards:
                record_answered(_SITE)
            for card in cards:
                if card["id"] in seen or (topic and not on_topic(card["title"], topic)):
                    continue
                seen.add(card["id"])
                if card["id"] in known_ids:
                    out.append({"platform_id": card["id"], "seen_only": True})
                    continue
                report(f"'{keyword}' details", len(out) - start + 1, len(cards))
                try:
                    body = session.get(_detail_url(card["id"]), headers=_JSON_HEADERS).text
                    detail = _parse_detail(body)
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
                    record_error(_SITE, f"detail error ({card['id']}): no ad text in the answer")
                    continue
                out.append(_posting(card, detail, now, scraped_at))

            if not cards or not _has_more(html):
                break
        log_keyword_results(_SITE, keyword, [p for p in out[start:] if not p.get("seen_only")])
    return out


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: page 1 of the first keyword, no description requests.

    ``raw`` is the page's HTML. Never records errors; ``None`` when no keyword is configured.
    """
    keywords = config.get("search_keywords") or config.get("role_targets") or []
    if not keywords:
        return None
    session = PoliteSession(min_delay=_MIN_DELAY, max_delay=_MAX_DELAY, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)
    now = datetime.now()
    url = _search_url(keywords[0], _insee_code(config.get("location") or ""), _MAX_EMISSION, 1)

    def fetch() -> str:
        return session.get(url).text

    def parse(html: str):
        if not _is_results_page(html):
            return [], False, "no result list and no 'no offers' answer on the page"
        scraped_at = datetime.now(timezone.utc)
        return [_card_posting(c, now, scraped_at) for c in _parse_cards(html)], True, ""

    return run_probe(fetch, parse, "html")
