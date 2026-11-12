#!/usr/bin/env python3
"""Scraper for EURAXESS (euraxess.ec.europa.eu), the European Commission's researcher job portal (issue #431).

Universities, institutes and research agencies post positions there (postdocs, assistant and associate
professorships, PhD posts), among them ads of universities whose own portals The other door cannot reach (the
University of Copenhagen). There is no API or feed: the job search is a Drupal page, server-rendered:

  GET https://euraxess.ec.europa.eu/jobs/search?f[0]=job_country:<id>&sort[name]=created&sort[direction]=DESC&page=<n>

``job_country`` is the country facet (``757`` Denmark, ``748`` Hungary, ``770`` Sweden, ``793`` France, ``771``
United Kingdom; each narrowed the list to its country on 2026-11-04, #601). The server has ignored it before and
returned the newest offers worldwide, so `_card_is_local` still keeps only the profile's country: a card whose
work-location country is another costs no job page and is counted with `record_non_local`. ``page`` counts from 0, ten offers a page, newest first. The text search does not narrow a
list (``keywords=`` and ``keys=`` are ignored next to a facet), so the list is read page by page,
the freshness cutoff stops the paging, and an offer is kept when its
title, its research field or its teaser is on topic for the profile (`sdk.on_topic`): an academic title
often names only a rank. Each card carries the organisation, ``Posted on``, the title and link
(``/jobs/<id>``), a teaser, the work locations, the research field and the researcher profile. The job page
(read only for an offer not seen before) holds the full ``Offer Description`` after the ``Job Information``
block. Offers of ``PhD-Jobs.NET`` and the like are aggregators' ads for non-academic posts and fall to the
topic check.

At most ``_MAX_PAGES`` (10) listing pages are read, newest first. The host answers HTTP 429 after a run of
requests (#579): a request that gets one is waited out once (``Retry-After``, else a minute) and retried; a second
429 is pushback (`record_pushback`: the run stops, the site rests, ``Site.cooldown_hours``), not an error.

Terms: the Commission's legal notice (https://commission.europa.eu/legal-notice_en, the site links to it):
content is reusable under CC BY 4.0 with credit, third-party content such as the offers needs the owner's
rights cleared for reuse; nothing bans automated reading. robots.txt disallows admin paths and, for
``/*?`` queries, search pages are not named for bots in a way that gates here (robots.txt is not a gate,
`http_client.OBEY_ROBOTS`).
"""

import re
import time
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from door.scrapers import sdk
from door.scrapers.sdk import (
    FEED_DELAY, JobPosting, PoliteSession, PROBE_TIMEOUT_S, ProbeResult, log_keyword_results, make_job_id,
    record_error, record_non_local, record_pushback, report, run_probe,
)

_BASE = "https://euraxess.ec.europa.eu"
_SEARCH = f"{_BASE}/jobs/search"
_SITE = "euraxess"
_MAX_PAGES = 10
_REST_S = 60.0   # how long a 429 is waited out (a Retry-After wins, up to this) before the one retry
_MIN_DELAY, _MAX_DELAY = FEED_DELAY

# The countries registered for (`core.sites.SITES["euraxess"].countries`; a test pins them) and the
# `job_country` facet id of each on the site.
_SERVED = ("dk", "hu", "se", "fr", "gb")
_COUNTRY_FACETS = {"dk": 757, "hu": 748, "se": 770, "fr": 793, "gb": 771}

# A link here is an ad on the board, never an employer's own site (`ats_detect.is_job_board`).
JOB_BOARD_HOSTS = ("euraxess.",)

_NUMBER_OF_OFFERS = re.compile(r"^\s*Number of offers:\s*\d+\s*,?\s*", re.IGNORECASE)


def _params(country: str, page: int) -> dict:
    """The query of one listing page: the country facet, newest first, *page* counted from 0. Pure."""
    params = {"f[0]": f"job_country:{_COUNTRY_FACETS[country]}", "sort[name]": "created", "sort[direction]": "DESC"}
    if page:
        params["page"] = page
    return params


def _text(node) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node is not None else ""


def _posted(raw: str) -> datetime | None:
    match = re.search(r"(\d{1,2} [A-Za-z]+ \d{4})", raw or "")
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%d %B %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _location(text: str) -> str:
    """``City, Country`` from a card's work location (``Number of offers: 1, Denmark, Geus, Aarhus, 8000, Street 81``):
    the country first, then organisation, city, postcode and street; the country alone without a postcode. Pure."""
    offers = re.match(r"\s*Number of offers:\s*(\d+)", text or "", re.IGNORECASE)
    parts = [p.strip() for p in _NUMBER_OF_OFFERS.sub("", text or "").split(",") if p.strip()]
    if not parts:
        return ""
    country = parts[0]
    if offers and int(offers.group(1)) > 1:   # one card for several posts: the place of one is no place of the offer
        return country
    zip_at = next((i for i, p in enumerate(parts) if i >= 2 and re.fullmatch(r"\d{3,}", p)), None)
    return f"{parts[zip_at - 1]}, {country}" if zip_at else country


def parse_listing(html: str) -> tuple[list[dict], bool]:
    """``(cards, has_next)`` of a listing page; a card has ``id``, ``title``, ``company``, ``location``, ``url``,
    ``posted_at``, ``teaser``, ``research_field`` and ``profile``. Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    cards = []
    for article in soup.select("article.ecl-content-item"):
        link = article.select_one("h3 a[href]")
        match = re.search(r"/jobs/(\d+)", link["href"]) if link else None
        if not match:
            continue
        meta = article.select("li.ecl-content-block__primary-meta-item")
        field = article.select_one("div.id-Research-Field")
        profile = article.select_one("div.id-Researcher-Profile div.ecl-text-standard")
        where = article.select_one("div.id-Work-Locations div.ecl-text-standard")
        cards.append({
            "id": match.group(1),
            "title": _text(link),
            "company": _text(meta[0]) if meta else "",
            "posted_at": _posted(_text(meta[1])) if len(meta) > 1 else None,
            "url": f"{_BASE}/jobs/{match.group(1)}",
            "teaser": _text(article.select_one("div.ecl-content-block__description")),
            "research_field": ", ".join(_text(a) for a in field.select("a")) if field else "",
            "profile": _text(profile),
            "location": _location(_text(where)),
        })
    return cards, soup.select_one("li.ecl-pagination__item--next") is not None


def parse_detail(html: str) -> str:
    """The ``Offer Description`` of a job page as text; "" without one. Pure."""
    heading = BeautifulSoup(html or "", "html.parser").find(id="offer-description")
    if heading is None:
        return ""
    parts = []
    for sibling in heading.find_next_siblings():
        if sibling.name == "h2":
            break
        parts.append(sdk.strip_html(str(sibling)))
    return "\n".join(p for p in parts if p).strip()


def _card_is_local(card: dict, config: dict) -> bool:
    """Whether a card's country (the last part of its ``location``, ``City, Country`` or ``Country``) is the
    profile's country, by the country's names in ``i18n``. A card without a country is not. Pure."""
    parts = [p.strip() for p in (card.get("location") or "").split(",") if p.strip()]
    if not parts:
        return False
    code = sdk.country(config, _SERVED)
    names = {sdk.country_name(code), *sdk.local_names(config)}
    return parts[-1].casefold() in {n.casefold() for n in names}


def _relevant(card: dict, terms: list[str]) -> bool:
    """Whether an offer is on topic by its title, its research field or its teaser (every offer without *terms*). Pure."""
    if not terms:
        return True
    return any(sdk.on_topic(card.get(key) or "", terms) for key in ("title", "research_field", "teaser"))


def _to_posting(card: dict, description: str, scraped_at: datetime) -> dict:
    head = " ".join(f"{label}: {card[key]}." for label, key in (("Research field", "research_field"),
                                                                 ("Researcher profile", "profile")) if card.get(key))
    body = "\n\n".join(p for p in (head, description or card.get("teaser") or "") if p) or card["title"]
    posting = JobPosting(
        id=make_job_id(_SITE, card["id"]),
        title=card["title"],
        company=card["company"],
        location=card["location"],
        url=card["url"],
        description=body,
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=card["id"],
        posted_at=card["posted_at"],
        apply_type="external",
        apply_url=card["url"],
    )
    return posting.model_dump(mode="json")


def _is_429(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    return response is not None and response.status_code == 429


def _get(session, url: str, **kwargs):
    """A GET that waits out one 429 (``Retry-After`` capped at `_REST_S`, else `_REST_S`) and retries; a second 429
    is raised as it is. Other errors are raised at once."""
    try:
        return session.get(url, **kwargs)
    except Exception as exc:  # noqa: BLE001 - only a 429 is retried
        if not _is_429(exc):
            raise
        header = exc.response.headers.get("Retry-After", "")
        wait = min(float(header), _REST_S) if header.replace(".", "", 1).isdigit() else _REST_S
        report(f"{_SITE}: 429, waiting {wait:.0f}s")
        time.sleep(wait)
        return session.get(url, **kwargs)


def _pushback(message: str) -> None:
    report(f"{_SITE}: {message}; stopping for this run")
    record_pushback(_SITE)


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """The on-topic offers of the profile's country newer than the cutoff, the new ones with their full text."""
    country = sdk.country(config, _SERVED).lower()
    since = kwargs.get("since")
    terms = sdk.topic_terms(config)
    scraped_at = datetime.now(timezone.utc)
    session = PoliteSession(min_delay=_MIN_DELAY, max_delay=_MAX_DELAY, max_retries=0)
    postings: list[dict] = []
    seen: set[str] = set()
    for page in range(_MAX_PAGES):
        try:
            cards, has_next = parse_listing(_get(session, _SEARCH, params=_params(country, page)).text)
        except Exception as exc:
            if _is_429(exc):
                _pushback(f"429 on the listing (page={page})")
                break  # noqa: BLE001 - a bad page stops the paging, never the run
            message = f"listing error (page={page}): {exc}"
            report(message)
            record_error(_SITE, message)
            break
        reached_cutoff = stopped = False
        for card in cards:
            if since is not None and card["posted_at"] is not None and card["posted_at"] < since:
                reached_cutoff = True   # newest first, worldwide: any older card ends the list
                continue
            if not _card_is_local(card, config):   # the facet is ignored server-side: no detail request abroad
                if card["id"] not in seen:
                    seen.add(card["id"])
                    record_non_local(_SITE, 1)
                continue
            if card["id"] in seen or card["id"] in known_ids or not _relevant(card, terms):
                continue
            seen.add(card["id"])
            try:
                description = parse_detail(_get(session, card["url"]).text)
            except Exception as exc:  # noqa: BLE001 - the teaser stays when the page cannot be read
                if _is_429(exc):
                    _pushback(f"429 on {card['url']}")
                    stopped = True
                    break
                report(f"detail error ({card['url']}): {exc}")
                description = ""
            postings.append(_to_posting(card, description, scraped_at))
        if stopped or not has_next or reached_cutoff or not cards:
            break
    log_keyword_results(_SITE, country.upper(), postings)
    return postings


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: listing page 1 of the profile's country, no job pages."""
    country = sdk.country(config, _SERVED).lower()
    session = PoliteSession(min_delay=_MIN_DELAY, max_delay=_MAX_DELAY, timeout=PROBE_TIMEOUT_S, max_retries=0)

    def parse(html: str):
        cards, _ = parse_listing(html)
        if not cards:
            return [], False, "no offers on the EURAXESS listing page"
        scraped_at = datetime.now(timezone.utc)
        return [_to_posting(c, "", scraped_at) for c in cards], True, ""

    return run_probe(lambda: session.get(_SEARCH, params=_params(country, 0)).text, parse, "html")
