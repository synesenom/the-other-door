#!/usr/bin/env python3
"""Employer discovery from profession.hu (Hungary's largest job board), read logged out.

Terms (https://www.profession.hu/, the terms are linked from its footer): clause VI.1 bans scraping; a verdict of
`unsure`.

profession.hu is not a job source for door and not a `Site`: its terms (VI.1) ban scraping, so no
posting is stored, scored or tailored from it. What it is good for is telling WHICH employers hire for
the user's keywords: the employers whose ad title is on topic are queued with the ad link (without its
tracking query), for `follow` to look for their own feed. The crawl (pacing, budget, pushback, wall
pages) is `sdk.paged_discovery`'s.

URL: one search per keyword, ``/allasok/<page>,0,0,<keyword>``; `_PAGE_CAP` pages of `_FULL_PAGE` ads at
most, `_MAX_BUDGET` requests a run, `_MIN_PAUSE` between two.

Markup (checked 2026-10-28): each ad is an ``li.advertisement-result-list-item`` carrying
``data-item-id``, ``data-item-name`` (the title), ``data-item-brand`` (the employer) and
``data-link`` (the ad URL with a ``?keyword=...&hash=...`` query); the place is the ``title`` of the
element whose id ends ``details-location`` (``"Hibrid • Budapest IX.kerület"``, the work mode before
the dot, sometimes alone). Nested elements repeat the item attributes, which is why only the ``li`` is read.

Parsing is pure and separate from the network, so fixtures test it offline.
"""

import re
from urllib.parse import quote, urlsplit

from bs4 import BeautifulSoup

from door.scrapers import sdk

# The discovery-source contract (`door.core.employers.discovery_sources`).
NAME = "profession"
COUNTRIES: tuple[str, ...] = ("hu",)
CONFIG_KEY = "profession_discovery"
LABEL = "profession.hu"  # how the engine names it in a skip reason
VERDICT = "unsure"  # the terms forbid automated access: runs only once the user turned it on
TERMS_URL = "https://www.profession.hu/"
TERMS_SUMMARY = "its terms (VI.1) ban scraping"

_HOST = "www.profession.hu"
_BASE = "https://" + _HOST
_PAGE_CAP = 3  # pages read for one keyword
_FULL_PAGE = 20  # ads a full result page lists; a page with fewer is the last one
_MAX_BUDGET = 30  # requests a run, whatever the engine allows
_MIN_PAUSE = (3.0, 6.0)  # seconds between two requests, at least
_LISTING_PATH = re.compile(r"^/allas(ok)?(/|$)")  # where a search or an ad lives; anything else is a wall


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #

def _collapse(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _search_url(keyword: str, page: int, config: dict) -> str:
    return f"{_BASE}/allasok/{page},0,0,{quote(keyword.strip(), safe='')}"


def _is_wall(url: str) -> bool:
    """Whether a final URL is not a listing or an ad of profession.hu (a login page, another host). Pure."""
    parts = urlsplit(url)
    return parts.netloc != _HOST or not _LISTING_PATH.match(parts.path)


def _place(text: str) -> str:
    """The place of a card's location title: what follows the work mode (``"Hibrid • Budapest"``). Pure."""
    return _collapse(text.split("•")[-1])


def _parse_cards(html: str) -> list[dict]:
    """The ads of a result page as ``{platform_id, title, company, location, url}``, in page order. An ad
    listed twice counts once; one without an id, a title or an employer is skipped. The URL has no query. Pure."""
    cards: list[dict] = []
    seen: set[str] = set()
    for item in BeautifulSoup(html, "html.parser").select("li.advertisement-result-list-item"):
        platform_id = _collapse(item.get("data-item-id"))
        title = _collapse(item.get("data-item-name"))
        company = _collapse(item.get("data-item-brand"))
        if not platform_id or not title or not company or platform_id in seen:
            continue
        seen.add(platform_id)
        place = item.select_one('[id$="details-location"]')
        link = urlsplit(item.get("data-link") or "")
        cards.append({
            "platform_id": platform_id, "title": title, "company": company,
            "location": _place(place.get("title") or "") if place is not None else "",
            "url": f"{link.scheme}://{link.netloc}{link.path}" if link.netloc else "",
        })
    return cards


# --- the discovery-source contract ----------------------------------------------------------

def run(config: dict, **kwargs) -> "sdk.DiscoveryResult":
    """The shared paged crawl (`sdk.paged_discovery`) over this source's URLs and cards."""
    return sdk.paged_discovery(
        config, name=NAME, search_url=_search_url, parse_cards=_parse_cards, is_wall=_is_wall,
        page_cap=_PAGE_CAP, full_page=_FULL_PAGE, max_budget=_MAX_BUDGET, min_pause=_MIN_PAUSE, **kwargs)
