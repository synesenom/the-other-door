#!/usr/bin/env python3
"""Employer discovery from HelloWork (France's large job board, hellowork.com), read logged out.

HelloWork is not a job source for door and not a `Site`: its terms (CGU art. 8.2, https://www.hellowork-group.com/fr/legal/cgu-hellowork/)
ban "l'utilisation de systemes automatises ou de logiciels pour extraire des donnees du Site ... a quelques
fins que ce soit, commerciales ou non" (art. 9.3 adds an extraction ban on the database), so no posting is
stored, scored or tailored from it. What it is good for is telling WHICH employers hire for the user's
keywords. `discover` reads a few search pages, keeps the employers whose ad title is on topic, and queues
them with the ad link; `follow` then looks for each employer's own feed by name (an ad link on a job board
is never an employer's careers page, `ats_detect.is_job_board`). That is the same use LinkedIn gets
(`door.scrapers.discovery.linkedin`) and profession.hu (`door.scrapers.discovery.profession`) and it stays
small and slow:

- plain HTTP, logged out: no login, no cookies kept (a fresh session per run), no account, no
  headless browser, `sdk.USER_AGENT` like every other request;
- one search per keyword of the rotation, ``/fr-fr/emploi/recherche.html?k=<keyword>&l=<city>[&p=<n>]``,
  at most `_PAGE_CAP` pages of `_FULL_PAGE` ads, a short page being the last; at most `_MAX_BUDGET`
  requests a run with at least `_MIN_PAUSE` seconds between two, whatever the engine hands over;
- the first 429 or 403, a redirect to a login page or off the listing, or a wall page (a captcha, a
  consent page, `sdk.wall_page`) where the results should be, stops the run and rests the
  source for a day (`record_pushback`); a 5xx or a failed load is tried once more, then stops;
- no ad text is read or kept, no job page is opened: a card gives the id, title, employer, place and
  link, and only the employer, the title and the link are handed on. The employer's own apply link sits
  behind the ad page and is not needed.

Terms (https://www.hellowork-group.com/fr/legal/cgu-hellowork/, read 2026-10-31): art. 8.2 and 9.3 as quoted above; a verdict of `unsure`.
robots.txt (checked 2026-10-31) disallows any URL with a query and ``/fr-fr/emploi/recherche.html``
for ``User-agent: *``; it is reported here and does not gate requests (`http_client.OBEY_ROBOTS`).

Markup (checked 2026-10-31): each ad is an ``li[data-id-storage-item-id]`` (the id) holding hidden
inputs ``title`` and ``company`` (the hide-offer form), the ad link ``a[data-cy=offerTitle]``
(``/fr-fr/emplois/<id>.html``, the heading ``h3`` repeating title and employer) and the place in
``[data-cy=localisationCard]`` (``"Paris 2e - 75"``). A page lists 30 ads; ``p=2`` gives the next 30.

Parsing is pure and separate from the network, so fixtures test it offline.
"""

import re
from urllib.parse import urlencode, urlsplit

from bs4 import BeautifulSoup

from door.scrapers import sdk

# The discovery-source contract (`door.core.employers.discovery_sources`).
NAME = "hellowork"
COUNTRIES: tuple[str, ...] = ("fr",)
CONFIG_KEY = "hellowork_discovery"
LABEL = "HelloWork"  # how the engine names it in a skip reason
VERDICT = "unsure"  # the terms forbid automated access: runs only once the user turned it on
TERMS_URL = "https://www.hellowork-group.com/fr/legal/cgu-hellowork/"
TERMS_SUMMARY = "its terms (CGU art. 8.2 and 9.3) ban automated systems and software that extract data from the site"

_HOST = "www.hellowork.com"
_BASE = "https://" + _HOST
_PAGE_CAP = 3  # pages read for one keyword
_FULL_PAGE = 30  # ads a full result page lists; a page with fewer is the last one
_MAX_BUDGET = 30  # requests a run, whatever the engine allows
_MIN_PAUSE = (3.0, 6.0)  # seconds between two requests, at least
_LISTING_PATH = re.compile(r"^/fr-fr/emplois?(/|\.|$)")  # where a search or an ad lives; anything else is a wall


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #

def _collapse(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _city(location: str) -> str:
    """The city of a profile's `location` (``"Paris, France"`` gives ``"Paris"``). Pure."""
    return _collapse((location or "").split(",")[0])


def _search_url(keyword: str, page: int, config: dict) -> str:
    query = {"k": keyword.strip()}
    if city := _city(config.get("location") or ""):
        query["l"] = city
    if page > 1:
        query["p"] = str(page)
    return f"{_BASE}/fr-fr/emploi/recherche.html?{urlencode(query)}"


def _is_wall(url: str) -> bool:
    """Whether a final URL is not a listing or an ad of HelloWork (a login page, another host). Pure."""
    parts = urlsplit(url)
    return parts.netloc != _HOST or not _LISTING_PATH.match(parts.path)


def _parse_cards(html: str) -> list[dict]:
    """The ads of a result page as ``{platform_id, title, company, location, url}``, in page order. An ad
    listed twice counts once; one without an id, a title or an employer is skipped. The URL has no query. Pure."""
    cards: list[dict] = []
    seen: set[str] = set()
    for item in BeautifulSoup(html, "html.parser").select("li[data-id-storage-item-id]"):
        platform_id = _collapse(item.get("data-id-storage-item-id"))
        title_input = item.select_one('input[name="title"]')
        company_input = item.select_one('input[name="company"]')
        spans = item.select("h3 span")
        title = _collapse(title_input.get("value") if title_input is not None else spans[0].get_text() if spans else "")
        company = _collapse(company_input.get("value") if company_input is not None else spans[1].get_text() if len(spans) > 1 else "")
        if not platform_id or not title or not company or platform_id in seen:
            continue
        seen.add(platform_id)
        place = item.select_one('[data-cy="localisationCard"]')
        anchor = item.select_one('a[data-cy="offerTitle"]')
        path = urlsplit(anchor.get("href") or "").path if anchor is not None else ""
        cards.append({
            "platform_id": platform_id, "title": title, "company": company,
            "location": _collapse(place.get_text()) if place is not None else "",
            "url": f"{_BASE}{path}" if path.startswith("/") else "",
        })
    return cards


# --- the discovery-source contract ----------------------------------------------------------

def run(config: dict, **kwargs) -> "sdk.DiscoveryResult":
    """The shared paged crawl (`sdk.paged_discovery`) over this source's URLs and cards."""
    return sdk.paged_discovery(
        config, name=NAME, search_url=_search_url, parse_cards=_parse_cards, is_wall=_is_wall,
        page_cap=_PAGE_CAP, full_page=_FULL_PAGE, max_budget=_MAX_BUDGET, min_pause=_MIN_PAUSE, **kwargs)
