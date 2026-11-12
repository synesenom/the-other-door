"""Scraper for KÖZSZOLGÁLLÁS (kozszolgallas.ksz.gov.hu), the Hungarian government's public-service job portal.

Kind: a keyword board, plain HTTP, no login, no API key. It carries the calls for applications of Hungary's
public sector (a statutory duty, Korm. rendelet 716/2021): hospitals and the ambulance service, municipalities
and government offices, social care institutes, school districts, universities. Those employers mostly have
no applicant-tracking feed, so the board is the route. The site's old address, ``kozigallas.gov.hu``,
redirects to ``kozszolgallas.ksz.gov.hu``. All ads are Hungarian (the site's English switch only
translates its interface). Endpoints (an ASP.NET MVC site, server-rendered HTML fragments):
- search ``POST https://kozszolgallas.ksz.gov.hu/JobAd/ListGridAsync`` with a JSON body
  ``{"page": 1, "pagesize": 20, "sort": "Created DESC", "keyword": "ápoló"}`` (what the page's own script
  posts; no token or cookie needed) - the answer is the cards (``div.jobaditemelement#<id>``: title and the
  institution's reference number, employer, place, application deadline) and hidden fields with
  ``ListInfo.TotalCount`` and ``List.PageCount``. The keyword searches title, employer and ad text, newest
  first; there is no date in a card, so ``since`` is left to the engine;
- ad ``GET https://kozszolgallas.ksz.gov.hu/JobAd/Info/<id>`` - the whole call in the ``#jobAd`` block (tasks,
  employment, place, conditions, how to apply), with ``Munkavégzés helye`` (place) and, mostly,
  ``Publikálás tervezett időpontja`` (the day it goes live: ``posted_at``).

A card whose title is not on topic for the profile's keywords (``on_topic``) costs no ad request, nor does an
id in ``known_ids`` (a ``seen_only`` record). A keyword reads pages while ``List.PageCount`` says there are
more, at most ``max_pages_per_keyword`` (default 3). A 403 or 429 (after the session's backoff) is pushback:
it is recorded with ``record_pushback`` and the run stops.

TLS: the host's certificate chain ends at Microsec's "e-Szigno RSA TLS Root CA 2025", which certifi does
not carry yet, so the session verifies against the operating system's trust store (``system_trust``);
verification stays on.

Terms: https://kozszolgallas.ksz.gov.hu/listarticlebycategory/Jogok ("Jogok és felhasználási feltételek",
checked 2026-11-12) - the portal's operator is the Prime Minister's Office (Miniszterelnökség); the terms
cover registered services and say "A KÖZSZOLGÁLLÁS oldalait bárki szabadon böngészheti" (anyone may browse
the pages freely). No clause on bots, scraping or text-and-data mining; each ad says the Office publishes it
and the advertising body answers for its content.
robots.txt (checked 2026-11-12): ``Allow: /$`` and ``Disallow: /``, i.e. everything but the front page; it
does not gate requests (`http_client.OBEY_ROBOTS`), the terms are the bar.
"""

import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

import json

from door.scrapers.sdk import (
    FEED_DELAY, JobPosting, PROBE_TIMEOUT_S, PoliteSession, ProbeResult, log_keyword_results, make_job_id,
    on_topic, record_answered, record_error, record_pushback, report, run_probe, topic_terms,
)

_SITE = "kozigallas"
_BASE = "https://kozszolgallas.ksz.gov.hu"
_LIST_URL = _BASE + "/JobAd/ListGridAsync"
_PAGE_SIZE = 20
_MAX_PAGES = 3

# Pause between requests: the employer feeds' (one host, one at a time).
_MIN_DELAY, _MAX_DELAY = FEED_DELAY

_HEADERS = {
    "Accept": "text/html, */*; q=0.01",
    "Accept-Language": "hu-HU,hu;q=0.9,en;q=0.8",
    "X-Requested-With": "XMLHttpRequest",
}
_JSON = {"Content-Type": "application/json; charset=utf-8"}

# Hosts of this board: a link here is an ad on the board, never an employer's own site (`ats_detect.is_job_board`).
JOB_BOARD_HOSTS = ("kozszolgallas.", "kozigallas.")

_DATE = re.compile(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})")
_PAGE_COUNT = re.compile(r'name="List\.PageCount"[^>]*value="(\d+)"')
_TOTAL_COUNT = re.compile(r'name="ListInfo\.TotalCount"[^>]*value="(\d+)"')


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def _clean_title(raw: str) -> str:
    """A card's title without the institution's reference number after it ("ápoló - 90/Sz/2026."): the
    last " - " part when it is one word holding a digit. Pure."""
    text = _clean(raw)
    head, sep, tail = text.rpartition(" - ")
    if sep and head and " " not in tail and re.search(r"\d", tail):
        return head.strip()
    return text


def _parse_date(text: str | None) -> datetime | None:
    """The day of "2026.11.11." or "2026.12.03. 00:00" (naive, midnight); None for anything else. Pure."""
    m = _DATE.search(text or "")
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _search_body(keyword: str, page: int) -> str:
    return json.dumps({"page": page, "pagesize": _PAGE_SIZE, "sort": "Created DESC", "keyword": keyword}, ensure_ascii=False)


def _parse_cards(html: str) -> list[dict]:
    """The result cards of a list answer: ``id``, ``url``, ``title`` (without the reference number), ``company``,
    ``location``, ``deadline`` (the date's text). A card without an id or title is skipped. Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    cards = []
    for card in soup.select("div.jobaditemelement"):
        pid = (card.get("id") or "").strip()
        heading = card.select_one("h4")
        title = _clean_title(heading.get_text(" ", strip=True)) if heading is not None else ""
        if not pid or not title:
            continue
        orgs = card.select("ul.jobOrg h5")
        highlight = card.select_one("ul.jobHighlight li:last-child")
        cards.append({
            "id": pid,
            "url": f"{_BASE}/JobAd/Info/{pid}",
            "title": title,
            "company": _clean(orgs[0].get_text(" ", strip=True)) if orgs else "",
            "location": _clean(orgs[1].get_text(" ", strip=True)) if len(orgs) > 1 else "",
            "deadline": _clean(highlight.get_text(" ", strip=True)) if highlight is not None else "",
        })
    return cards


def _page_count(html: str) -> int | None:
    """The number of result pages the answer says there are, or None when it does not say. Pure."""
    m = _PAGE_COUNT.search(html or "")
    return int(m.group(1)) if m else None


def _is_results_page(html: str) -> bool:
    """Whether an answer is the search's: result cards, or the (empty) list with its totals. Pure."""
    h = html or ""
    return "jobaditemelement" in h or bool(_TOTAL_COUNT.search(h))


def _no_hits(html: str) -> bool:
    """Whether an answer says the search found nothing (``ListInfo.TotalCount`` 0). Pure."""
    m = _TOTAL_COUNT.search(html or "")
    return bool(m) and int(m.group(1)) == 0


def _fields(soup) -> list[tuple[str, str]]:
    """The ad page's ``(label, text)`` lines: each ``div.col-12`` of its blocks, a label being its bold start
    ("Munkavégzés helye"); bullets have an empty label."""
    lines = []
    for div in soup.select("#jobAd div.row.my-3 div.col-12"):
        label_tag = div.find("b")
        label = _clean(label_tag.get_text(" ", strip=True)).rstrip(":") if label_tag is not None else ""
        text = _clean(div.get_text(" ", strip=True))
        if text:
            lines.append((label, text))
    return lines


def _parse_detail(page: str) -> dict | None:
    """``description`` (plain text of the call, one line per field), ``company``, ``location``, ``posted_at``
    (Publikálás tervezett időpontja) and ``deadline`` from an ad page; None when it has no ad text. Pure."""
    soup = BeautifulSoup(page or "", "html.parser")
    if soup.select_one("#jobAd") is None:
        return None
    lines = _fields(soup)
    description = "\n".join(text for _label, text in lines)
    if not description:
        return None

    def field(prefix: str) -> str:
        for label, text in lines:
            if label.startswith(prefix):
                return _clean(text[len(label) + 1:] if text.startswith(label) else text).lstrip(": ").strip()
        return ""

    head = soup.select_one("#jobAd h3 + br + div")
    return {
        "description": description,
        "company": _clean(head.get_text(" ", strip=True)) if head is not None else "",
        "location": field("Munkavégzés helye"),
        "posted_at": _parse_date(field("Publikálás tervezett időpontja")),
        "deadline": _parse_date(field("A pályázat benyújtásának határideje")),
    }


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
        posted_at=detail["posted_at"],
    ).model_dump(mode="json")


def _card_posting(card: dict, scraped_at: datetime | None = None) -> dict:
    """A posting from a search card alone (the probe's): the title and the employer stand in for the text."""
    text = ". ".join(x for x in (card["title"], card["company"]) if x)
    detail = {"description": text, "company": "", "location": "", "posted_at": None}
    return _posting(card, detail, scraped_at or datetime.now(timezone.utc))


def _pushback(message: str) -> None:
    report(f"{_SITE}: {message}; stopping for this run")
    record_error(_SITE, f"{_SITE}: {message}; stopped for this run")
    record_pushback(_SITE)


def _refused(exc: requests.HTTPError) -> bool:
    return getattr(exc.response, "status_code", 0) in (403, 429)


def _session(timeout: float, max_retries: int = 3) -> PoliteSession:
    # system_trust: the host's root certificate (Microsec e-Szigno 2025) is not in certifi's bundle yet.
    return PoliteSession(min_delay=_MIN_DELAY, max_delay=_MAX_DELAY, timeout=timeout, max_retries=max_retries,
                         headers=_HEADERS, system_trust=True)


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """JobPosting dicts for the on-topic ads of every search keyword (``seen_only`` records for known ids)."""
    keywords: list[str] = config.get("search_keywords") or config.get("role_targets") or []
    max_pages = int(config.get("max_pages_per_keyword", _MAX_PAGES))
    topic = topic_terms(config)
    scraped_at = datetime.now(timezone.utc)
    session = _session(30)
    seen: set[str] = set()
    out: list[dict] = []

    for keyword in keywords:
        start = len(out)
        for page in range(1, max_pages + 1):
            try:
                html = session.post(_LIST_URL, data=_search_body(keyword, page).encode("utf-8"), headers=_JSON).text
            except requests.HTTPError as exc:
                if _refused(exc):
                    _pushback(f"HTTP {exc.response.status_code}")
                    return out
                record_error(_SITE, f"search error (keyword={keyword!r}, page={page}): {exc}")
                break
            except Exception as exc:  # noqa: BLE001 - one bad page never stops the run
                record_error(_SITE, f"search error (keyword={keyword!r}, page={page}): {exc}")
                break
            if not _is_results_page(html):
                record_error(_SITE, f"search (keyword={keyword!r}, page={page}): no result list in the answer (the site may have changed)")
                break
            if _no_hits(html):
                record_answered(_SITE)
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

            pages = _page_count(html)
            if not cards or (page >= pages if pages is not None else len(cards) < _PAGE_SIZE):
                break
        log_keyword_results(_SITE, keyword, [p for p in out[start:] if not p.get("seen_only")])
    return out


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: page 1 of the first keyword, no ad requests.

    ``raw`` is the answer's HTML. Never records errors; ``None`` when no keyword is configured.
    """
    keywords = config.get("search_keywords") or config.get("role_targets") or []
    if not keywords:
        return None
    session = _session(PROBE_TIMEOUT_S, max_retries=0)

    def fetch() -> str:
        return session.post(_LIST_URL, data=_search_body(keywords[0], 1).encode("utf-8"), headers=_JSON).text

    def parse(html: str):
        if not _is_results_page(html):
            return [], False, "no result cards and no list totals in the answer"
        cards = _parse_cards(html)
        if not cards and "jobaditemelement" in html:
            return [], False, "result cards without a title"
        scraped_at = datetime.now(timezone.utc)
        return [_card_posting(c, scraped_at) for c in cards], True, ""

    return run_probe(fetch, parse, "html")
