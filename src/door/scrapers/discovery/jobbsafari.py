#!/usr/bin/env python3
"""Employer discovery from Jobbsafari (Sweden), read logged out.

Jobbsafari (jobbsafari.se, run by Duunitori) is not a job source for The other door and not a `Site`: its
terms ban scraping, so no posting is stored, scored or tailored from it. What it is good for is telling
WHICH employers hire for the user's keywords, and it gives the link to the employer's own application
page, which `follow` can resolve to the employer's feed. The employers whose ad title is on topic are
queued with that apply link (ads applied for by email have none; the tracking query is dropped). The crawl
(pacing, budget, pushback, wall pages) is `sdk.paged_discovery`'s.

URL: one search per keyword, ``/lediga-jobb?sok=<keyword>[&page=N]``; pages of `_FULL_PAGE` ads (the engine's page cap,
budget and pause). No `/jobb/<slug>` page is opened.

Terms (https://jobbsafari.se/compliance/allmanna-villkor, read 2026-10-31): "Användaren får inte lagra,
arkivera, skrapa eller på annat sätt systematiskt kopiera innehållet i Tjänsten" and may not use the
content commercially; the terms bind every user of the service. No clause names bots or text and data
mining. robots.txt: ``Allow: /``, ``Disallow: /api``; the ``ort=`` filter is disallowed, so it is never used.

Markup (checked 2026-10-31): the search page ``https://jobbsafari.se/lediga-jobb?sok=<keyword>`` (the
``/lediga-jobb?q=`` form redirects to it) embeds ``<script id="__NEXT_DATA__">`` whose
``props.pageProps.jobEntries.results`` lists 30 ads a page (``count`` is the total; ``&page=N`` for the
next one): ``pk``, ``title``, ``company.name``, ``locations[].name`` and ``apply`` (``{"method": "url",
"href": <the employer's application page, with utm_ tracking>}`` or ``{"method": "email", "href":
"mailto:..."}``).

Parsing is pure and separate from the network, so fixtures test it offline.
"""

import json
import re
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from door.scrapers import sdk

# The discovery-source contract (`door.core.employers.discovery_sources`).
NAME = "jobbsafari"
COUNTRIES: tuple[str, ...] = ("se",)
CONFIG_KEY = "jobbsafari_discovery"
LABEL = "Jobbsafari"  # how the engine names it in a skip reason
VERDICT = "unsure"  # the terms forbid automated access: runs only once the user turned it on
TERMS_URL = "https://jobbsafari.se/compliance/allmanna-villkor"
TERMS_SUMMARY = "its terms ban storing, scraping or systematically copying the content"

_HOST = "jobbsafari.se"
_BASE = "https://" + _HOST
_FULL_PAGE = 30  # ads a full result page lists; a page with fewer is the last one
_LISTING_PATH = re.compile(r"^/lediga-jobb(/|$)")  # where a search lives; anything else is a wall
JOB_BOARD_HOSTS = ("jobbsafari.",)


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #

def _collapse(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _search_url(keyword: str, page: int, config: dict) -> str:
    url = f"{_BASE}/lediga-jobb?sok={quote(keyword.strip(), safe='')}"
    return url if page <= 1 else f"{url}&page={page}"


def _is_wall(url: str) -> bool:
    """Whether a final URL is not a listing of Jobbsafari (a login page, another host). Pure."""
    parts = urlsplit(url)
    return parts.netloc not in (_HOST, "www." + _HOST) or not _LISTING_PATH.match(parts.path)


def _clean_link(href: str | None) -> str:
    """An apply link without its tracking (``utm_*``, ``_atxsrc``) query and fragment; ``""`` for an
    email application or anything but a web link. Pure."""
    parts = urlsplit((href or "").strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k != "_atxsrc"]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _next_data(html: str) -> dict:
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    try:
        data = json.loads(match.group(1)) if match else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _parse_cards(html: str) -> list[dict]:
    """The ads of a result page as ``{platform_id, title, company, location, url}``, in page order. An ad
    listed twice counts once; one without an id, a title or an employer is skipped. The url is the
    employer's apply link without tracking, ``""`` for an email application. Pure."""
    try:
        results = _next_data(html)["props"]["pageProps"]["jobEntries"]["results"]
    except (KeyError, TypeError):
        return []
    cards: list[dict] = []
    seen: set[str] = set()
    for entry in results if isinstance(results, list) else []:
        if not isinstance(entry, dict):
            continue
        platform_id = _collapse(str(entry.get("pk") or ""))
        title = _collapse(entry.get("title"))
        company = _collapse((entry.get("company") or {}).get("name"))
        if not platform_id or not title or not company or platform_id in seen:
            continue
        seen.add(platform_id)
        places = [_collapse(loc.get("name")) for loc in entry.get("locations") or [] if isinstance(loc, dict)]
        cards.append({
            "platform_id": platform_id, "title": title, "company": company,
            "location": ", ".join(p for p in places if p),
            "url": _clean_link((entry.get("apply") or {}).get("href")),
        })
    return cards


# --- the discovery-source contract ----------------------------------------------------------

def run(config: dict, **kwargs) -> "sdk.DiscoveryResult":
    """The shared paged crawl (`sdk.paged_discovery`) over this source's URLs and cards."""
    return sdk.paged_discovery(
        config, name=NAME, search_url=_search_url, parse_cards=_parse_cards, is_wall=_is_wall,
        full_page=_FULL_PAGE, **kwargs)
