#!/usr/bin/env python3
"""Scraper for Talentsoft career sites (Cegid Talentsoft, issue #559), a French recruiting system.

Kind: a per-company feed (an HTML list plus an RSS feed), no login, no key. About a hundred and thirty French
employers have a career site on ``<tenant>-career.talent-soft.com`` or ``<tenant>-recrute.talent-soft.com``, many
of them on the employer's own host (``recrutement.<employer>.fr``); the entry is the host. All of them serve:

  GET https://<host>/offre-de-emploi/liste-offres.aspx[?page=N]
      The list of every open ad, ten cards a page: the ad link (``/offre-de-emploi/emploi-<slug>_<id>.aspx``),
      title, reference, publication day (``dd/mm/yyyy``), department and place; "Nombre de résultats : N
      offre(s)" gives the total, and the ``<title>`` starts with the employer's name. A page past the last one
      repeats the first, so the walk stops at the total or at a page that adds nothing.
  GET https://<host>/handlers/offerRss.ashx
      RSS 2.0 of the newest twenty ads only (no size or page parameter: ``page``, ``nbItems`` and the like are
      ignored): ``title`` (``<reference> - <title>``), ``link`` (``.../Pages/Offre/detailoffre.aspx?idOffre=<id>``),
      ``category`` (the contract, then the place), ``pubDate`` and ``description`` (the ad's text, HTML).
  GET https://<host>/offre-de-emploi/emploi-<slug>_<id>.aspx
      The ad page (no JSON-LD), read only for an ad the feed does not hold and that is not in ``known_ids``: the
      text is the blocks of ``#contenu-ficheoffre`` from "Description du poste" to the place.

The list fixes the ads and their places, the feed gives most of their text in one request, and the ad page the
rest. No language parameter is sent (``LCID``): the site answers in its own default.

Configured by ``talentsoft_hosts`` in the employer list: the career host (``agrica-career.talent-soft.com``) or
any link on it. `follow` detects a tenant host, a link whose path is Talentsoft's (``/offre-de-emploi/…aspx``,
``/handlers/offerRss.ashx``, ``/Pages/Offre/detailoffre.aspx``), a career page that links them, or a CNAME for
``*.talent-soft.com``.

Terms: per employer; there is no vendor-wide clause on reading a public job list. AGRICA's mention légale
(https://agrica-career.talent-soft.com/) bans only commercial collection of its content, which a personal job
search is not; the career site offers its RSS feed itself. robots.txt of a tenant was not found to disallow the
list, the feed or the ad pages. Checked 2026-11-01.
"""

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

from door.scrapers.sdk import (
    Detection, JobPosting, NOT_ACCOUNTS, PROBE_TIMEOUT_S, PoliteSession, ProbeResult, RobotsBlocked, followed_name,
    host_of, keep_local, make_job_id, parts, record_entry_error, record_error, record_pushback, report, run_probe,
    scrape_feeds, strip_html, tenant_platform_id, workers,
)

# The platform's own domain: a host on it is a customer's, never the employer's name.
PLATFORM_DOMAINS = ("talent-soft.com",)

_SITE = "talentsoft"
_KEY = "talentsoft_hosts"
_SUFFIX = ".talent-soft.com"
_LIST_PATH = "/offre-de-emploi/liste-offres.aspx"
_RSS_PATH = "/handlers/offerRss.ashx"
_NOT_TENANTS = NOT_ACCOUNTS | {"cdn", "support", "help", "docs", "static", "img", "mail", "status"}
_PUSHBACK = (401, 403, 429)
_MAX_PAGES = 60   # 600 ads: a safety stop for a list that never ends
_AD_ID = re.compile(r"(?:_|idOffre=)(\d+)(?:\.aspx|&|$)", re.IGNORECASE)
_TOTAL = re.compile(r"(\d+)\s+offres?", re.IGNORECASE)
_DAY = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_REF = re.compile(r"^R[ée]f\.?\s*:\s*(.*)$", re.IGNORECASE)
# The paths only a Talentsoft site has, whatever its host.
_OWN_PATHS = ("handlers/offerrss.ashx", "pages/offre/detailoffre.aspx", "offre-de-emploi/liste-offres.aspx")
_OWN_AD = re.compile(r"^offre-de-emploi/emploi-.+_\d+\.aspx$", re.IGNORECASE)


# --- pure helpers ---

def _base(entry: str) -> str:
    """``https://<host>`` for a ``talentsoft_hosts`` entry: a host or any link on it. Pure."""
    return f"https://{parts(entry.strip())[0]}"


def _ad_id(url: str) -> str:
    """The offer id of an ad link (``…_2286.aspx`` or ``…?idOffre=2286``), "" for any other link. Pure."""
    match = _AD_ID.search(url or "")
    return match.group(1) if match else ""


def _day(text: str) -> datetime | None:
    """A ``dd/mm/yyyy`` day as midnight UTC; ``None`` for anything else. Pure."""
    if not _DAY.match(text or ""):
        return None
    try:
        return datetime.strptime(text, "%d/%m/%Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _clean(text: str) -> str:
    return " ".join((text or "").replace("\xa0", " ").split())


def parse_list(html: str) -> tuple[int | None, str, list[dict]]:
    """``(total, employer, cards)`` of a list page: the "N offre(s)" total (``None`` when absent), the name the
    page title starts with, and each card ``{id, url, title, ref, posted_at, location}``. Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    found = soup.find(id=re.compile("TotalOffers$"))
    match = _TOTAL.search(found.get_text(" ")) if found is not None else None
    title = _clean(soup.title.get_text()) if soup.title is not None else ""
    name = title.split(" - ", 1)[0] if " - " in title else ""
    cards = []
    for link in soup.find_all("a", class_="ts-offer-card__title-link"):
        ad_id = _ad_id(link.get("href", ""))
        if not ad_id:
            continue
        card = link.find_parent("div", class_="ts-offer-card")
        cells = [_clean(li.get_text()) for li in card.find_all("li")] if card is not None else []
        ref = next((m.group(1) for c in cells if (m := _REF.match(c))), "")
        day = next((d for c in cells if (d := _day(c))), None)
        rest = [c for c in cells if not _REF.match(c) and not _DAY.match(c)]
        cards.append({
            "id": ad_id, "url": link["href"], "title": _clean(link.get_text()), "ref": ref, "posted_at": day,
            "location": rest[-1] if len(rest) > 1 else "",
        })
    return (int(match.group(1)) if match else None), name, cards


def parse_feed(xml_text: str) -> dict[str, dict]:
    """The RSS feed's ads by offer id: ``{id: {title, ref, contract, location, description, posted_at}}``.
    Raises ``ValueError`` when the text is no RSS feed (an HTML error page, a block page). Pure."""
    try:
        root = ElementTree.fromstring((xml_text or "").encode("utf-8"))
    except ElementTree.ParseError as exc:
        raise ValueError(f"not an RSS feed: {exc}") from exc
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise ValueError("no RSS channel in Talentsoft's answer")
    ads: dict[str, dict] = {}
    for item in channel.findall("item"):
        ad_id = _ad_id(item.findtext("link") or "")
        if not ad_id:
            continue
        ref, _, title = _clean(item.findtext("title") or "").partition(" - ")
        if not title:
            ref, title = "", ref
        categories = [_clean(c.text or "") for c in item.findall("category")]
        try:
            posted = parsedate_to_datetime((item.findtext("pubDate") or "").replace(" Z", " +0000"))
        except (TypeError, ValueError):
            posted = None
        ads[ad_id] = {
            "title": title, "ref": ref, "contract": categories[0] if categories else "",
            "location": categories[1] if len(categories) > 1 else "",
            "description": strip_html(item.findtext("description") or ""), "posted_at": posted,
        }
    return ads


def parse_detail(html: str) -> dict | None:
    """``{title, description, location}`` of an ad page: the blocks of the details from "Description du poste" up
    to the place; ``None`` when the page has no ad. Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    details = soup.find(id="contenu-ficheoffre")
    start = details.find("h2", class_="JobDescription") if details is not None else None
    if start is None:
        return None
    blocks = [str(start)]
    for sibling in start.find_next_siblings():
        if sibling.name == "h2":
            break
        blocks.append(str(sibling))
    place = details.find(id="fldlocation_joblocation")
    h1 = soup.find("h1", class_="ts-offer-page__title")
    return {
        "title": _clean(h1.get_text()) if h1 is not None else "",
        "description": strip_html("".join(blocks)),
        "location": _clean(place.get_text()) if place is not None else "",
    }


def _to_posting(card: dict, base: str, company: str, description: str, scraped_at: datetime,
                ad: dict | None = None) -> dict:
    """The posting of a list *card*, with the feed *ad*'s time and place where it has them."""
    platform_id = tenant_platform_id(base, card["id"])
    ad = ad or {}
    url = card["url"] if card["url"].startswith("http") else f"{base}{card['url']}"
    posting = JobPosting(
        id=make_job_id(_SITE, platform_id),
        title=card["title"] or ad.get("title", ""),
        company=company,
        location=card["location"] or ad.get("location", ""),
        url=url,
        description=description,
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=ad.get("posted_at") or card["posted_at"],
        apply_type="external",
        apply_url=url,
    )
    return posting.model_dump(mode="json")


def _status(exc: Exception) -> int | None:
    return getattr(getattr(exc, "response", None), "status_code", None)


# --- network ---

def _list_cards(session: PoliteSession, base: str) -> tuple[str, list[dict]]:
    """``(employer, every card)`` of a career site's list, page by page until the total is reached or a page
    adds nothing. Raises when the first page cannot be read or is no list; a later page that fails ends the walk
    with what was read."""
    name, cards, seen, total = "", [], set(), None
    for page in range(1, _MAX_PAGES + 1):
        url = f"{base}{_LIST_PATH}" + (f"?page={page}" if page > 1 else "")
        try:
            html = session.get(url).text
        except (requests.RequestException, RobotsBlocked) as exc:
            if page == 1:
                raise
            report_error = f"error fetching page {page} of {base}: {exc}"
            record_error(_SITE, report_error)
            break
        page_total, page_name, found = parse_list(html)
        if page == 1:
            if not found:
                raise ValueError(f"{url} lists no ads (is the career site gone or changed?)")
            name, total = page_name, page_total
        fresh = [c for c in found if c["id"] not in seen]
        if not fresh:
            break
        seen.update(c["id"] for c in fresh)
        cards.extend(fresh)
        if total is None or len(cards) >= total:
            break
    return name, cards


def _site_postings(session: PoliteSession, entry: str, scraped_at: datetime, known_ids: frozenset[str],
                   name: str) -> list[dict]:
    """One career site's postings. Raises when its list cannot be read; a refusal is recorded as pushback and
    ends the site."""
    base = _base(entry)
    try:
        employer, cards = _list_cards(session, base)
    except (requests.RequestException, RobotsBlocked) as exc:
        if _status(exc) in _PUSHBACK:
            record_pushback(_SITE)
        raise
    company = name or employer or entry
    cards = [c for c in cards if tenant_platform_id(base, c["id"]) not in known_ids]
    feed: dict[str, dict] = {}
    if cards:
        try:
            feed = parse_feed(session.get(f"{base}{_RSS_PATH}").text)
        except (requests.RequestException, RobotsBlocked, ValueError) as exc:
            message = f"error reading the RSS feed of {entry!r}: {exc}"   # the ads' pages hold the text, then
            report(message)
            record_error(_SITE, message)
    out: list[dict] = []
    for n, card in enumerate(cards, 1):
        ad = feed.get(card["id"])
        text = ad["description"] if ad and ad["description"] else ""
        if not text:
            report("detail", n, len(cards))
            try:
                page = parse_detail(session.get(card["url"] if card["url"].startswith("http") else f"{base}{card['url']}").text)
            except (requests.RequestException, RobotsBlocked) as exc:
                if _status(exc) in _PUSHBACK:
                    record_pushback(_SITE)
                    record_entry_error(_SITE, entry, f"{entry!r} refused ad {card['id']} ({_status(exc)}); stopped", blocked=True)
                    break
                record_error(_SITE, f"error fetching ad {card['id']} of {entry!r}: {exc}")
                continue
            if page is None:
                record_error(_SITE, f"ad {card['id']} of {entry!r} has no description")
                continue
            text = page["description"]
            ad = {**(ad or {}), "location": (ad or {}).get("location") or page["location"]}
        out.append(_to_posting(card, base, company, text, scraped_at, ad))
    return out


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Every open ad of each configured Talentsoft career site; an ad in *known_ids* is not read again."""
    entries = [e.strip() for e in config.get(_KEY) or [] if e.strip()]

    def fetch(session, entry, scraped_at):
        return _site_postings(session, entry, scraped_at, known_ids, followed_name(config, _KEY, entry, ""))

    return keep_local(scrape_feeds(_SITE, entries, fetch, group=lambda e: host_of(_base(e)),
                                   max_workers=workers(config)), config, _SITE)


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the first list page of the first configured site (one request). ``None``
    when none is set."""
    entries = [e for e in config.get(_KEY) or [] if e.strip()]
    if not entries:
        return None
    base = _base(entries[0])
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0)

    def fetch() -> str:
        return session.get(f"{base}{_LIST_PATH}").text

    def parse(text: str):
        _total, name, cards = parse_list(text)
        if not cards:
            return [], False, "no ad cards on the list page: the career site is gone or has changed"
        now = datetime.now(timezone.utc)
        return [_to_posting(c, base, name or entries[0], "", now) for c in cards], True, ""

    return run_probe(fetch, parse, "html")


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

FEED_KEY = None  # (no JSON feed to confirm an entry with: `feed_url` is None)


def _own_path(path: list[str]) -> bool:
    joined = "/".join(path).lower()
    return joined in _OWN_PATHS or bool(_OWN_AD.match(joined))


def detect_url(url: str) -> Detection | None:
    """A link on a Talentsoft career site: a ``*.talent-soft.com`` tenant host, or any host whose path is
    Talentsoft's own (the list, an ad, a detail link, the RSS handler). The entry is the host."""
    host, path, _query = parts(url.strip())
    if not host:
        return None
    if host.endswith(_SUFFIX):
        label = host[: -len(_SUFFIX)]
        if label and "." not in label and label not in _NOT_TENANTS:
            return Detection(_SITE, host, f"Talentsoft career site {host}")
        return None
    if _own_path(path):
        return Detection(_SITE, host, f"{url} has Talentsoft's paths: a Talentsoft career site on {host}")
    return None


def feed_url(entry: str) -> str | None:
    """None: the RSS feed is XML and capped at twenty ads, not the JSON list the confirmation reads; a link's
    shape vouches for the site, and `alive_url` drops a career site that does not exist."""
    return None


def alive_url(entry: str) -> str:
    """The first read of a career site: the list page; an unknown tenant answers a 4xx, which `companies add` reports."""
    return f"{_base(entry)}{_LIST_PATH}"


def name_probes(slug: str) -> list:
    """None to try: a company's name does not tell its tenant."""
    return []


def detect_cname(host: str, target: str, where: str) -> Detection | None:
    """A career host that is a CNAME for a ``*.talent-soft.com`` tenant (the entry is the tenant host)."""
    found = detect_url(f"https://{target}/")
    return Detection(_SITE, found.entry, where) if found and found.entry == target else None


def detect_html(html: str, url: str) -> Detection | None:
    """A career page on the employer's own host that links Talentsoft's list or RSS handler."""
    text = (html or "").lower()
    host = parts(url.strip())[0]
    if host and any(p in text for p in (_LIST_PATH.lstrip("/").lower(), _RSS_PATH.lstrip("/").lower())):
        return Detection(_SITE, host, f"{url} links Talentsoft's job list: a Talentsoft career site on {host}")
    return None
