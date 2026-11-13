#!/usr/bin/env python3
"""Scraper for Platsbanken (arbetsformedlingen.se), the Swedish Public Employment Service's job board, through
its open JobSearch API (JobTech).

A keyword board: one JSON request per page of one keyword, no key or account.

  GET https://jobsearch.api.jobtechdev.se/search?q=<keyword>&municipality=<id>&sort=pubdate-desc&limit=100&offset=<n>

q is the profile's keyword as it is (the API reads Swedish and English alike; no language is asked for, the
language pass decides afterwards). municipality (repeatable) is the taxonomy concept id of the profile
location's municipality and of the towns around it that i18n/country/se.toml lists for the city
(_MUNICIPALITIES, read from the JobTech taxonomy, taxonomy.api.jobtechdev.se); a place the table does
not know searches all of Sweden. published-after carries the freshness cutoff (the ads' dates are Stockholm
local time, and so is the cutoff sent). limit is at most 100 and offset at most 2000; the answer holds
total.value and hits. A hit has the whole ad (description.text), so no detail request is made:
id, headline, webpage_url (the Platsbanken page), employer.name, workplace_address(es),
publication_date, workplace_model, removed. Staffing agencies post here too, so the same job can come
from several employers.

TLS: the API's certificate chain ends in Telia Root CA v2. requests verifies it with certifi; a system
store without that root (macOS's curl) refuses it, and the error says so.

Terms: https://jobsearch.api.jobtechdev.se/ - the API's own description (its OpenAPI license) reads "Ads are
licensed under CC0" (https://creativecommons.org/publicdomain/zero/1.0/deed.sv), and the open-data portal
https://data.arbetsformedlingen.se/ defines open data as free for anyone to use and share for any purpose; nothing
bans automated reading. JobTech says JobSearch is for searching rather than bulk download (the bulk feed is
JobStream), which a search per keyword and municipality is. robots.txt: none for the API host. Checked 2026-10-31.
"""

import json
import unicodedata
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

import requests

from door.scrapers import sdk
from door.scrapers.sdk import (
    FEED_DELAY, JobPosting, PoliteSession, PROBE_TIMEOUT_S, ProbeResult, log_keyword_results, make_job_id, record_answered, record_error,
    record_pushback, report, run_probe,
)

_SITE = "arbetsformedlingen"
_API = "https://jobsearch.api.jobtechdev.se/search"
_PAGE_SIZE = 100
_MAX_PAGES = 5
_MIN_DELAY, _MAX_DELAY = FEED_DELAY

# Hosts of this board: a link here is an ad on the board, never an employer's own site ().
JOB_BOARD_HOSTS = ("arbetsformedlingen.se", "platsbanken")

_STOCKHOLM = ZoneInfo("Europe/Stockholm")

_TLS_HELP = (
    "TLS certificate verification failed: the API's chain ends in Telia Root CA v2, which the system trust store "
    "lacks (requests verifies it with certifi); update certifi or the system's root certificates"
)

# Municipality concept ids of the JobTech taxonomy (type ), keyed by the name without accents,
# for the places  names (cities, their towns and commute areas).
_MUNICIPALITIES = {
    "botkyrka": "CCVZ_JA7_d3y",
    "burlov": "64g5_Lio_aMU",
    "danderyd": "E4CV_a5E_ucX",
    "ekero": "magF_Gon_YL2",
    "enkoping": "HGwg_unG_TsG",
    "eslov": "gfCw_egj_1M4",
    "gnesta": "os8Y_RUo_U3u",
    "goteborg": "PVZL_BQT_XtL",
    "haninge": "Q7gp_9dT_k2F",
    "harryda": "dzWW_R3G_6Eh",
    "huddinge": "g1Gc_aXK_EKu",
    "jarfalla": "qm5H_jsD_fUF",
    "jonkoping": "KURg_KJF_Lwc",
    "kavlinge": "5ohg_WJU_Ktn",
    "knivsta": "KALq_sG6_VrW",
    "kungalv": "ZkZf_HbK_Mcr",
    "kungsbacka": "3JKV_KSK_x6z",
    "landskrona": "Yt5s_Vf9_rds",
    "lerum": "yHV7_2Y6_zQx",
    "lidingo": "FBbF_mda_TYD",
    "linkoping": "bm2x_1mr_Qhx",
    "lomma": "naG4_AUS_z2v",
    "lund": "muSY_tsR_vDZ",
    "malmo": "oYPt_yRA_Smm",
    "molndal": "mc45_ki9_Bv3",
    "nacka": "aYA7_PpG_BqP",
    "norrkoping": "SYty_Yho_JAF",
    "norrtalje": "btgf_fS7_sKG",
    "nykvarn": "mBKv_q3B_SK8",
    "nynashamn": "37UU_T7x_oxG",
    "ockero": "Zjiv_rhk_oJK",
    "orebro": "kuMn_feU_hXx",
    "osteraker": "8gKt_ZsV_PGj",
    "partille": "CCiR_sXa_BVW",
    "sigtuna": "8ryy_X54_xJj",
    "sodertalje": "g6hK_M1o_hiU",
    "sollentuna": "Z5Cq_SgB_dsB",
    "solna": "zHxw_uJZ_NJ8",
    "staffanstorp": "vBrj_bov_KEX",
    "stockholm": "AvNB_uwa_6n6",
    "strangnas": "shnD_RiE_RKL",
    "sundbyberg": "UTJZ_zHH_mJm",
    "svedala": "n6r4_fjK_kRr",
    "taby": "onpA_B5a_zfv",
    "tyreso": "sTPc_k2B_SqV",
    "umea": "QiGt_BLu_amP",
    "upplands vasby": "XWKY_c49_5nv",
    "upplands-bro": "w6yq_CGR_Fiv",
    "uppsala": "otaF_bQY_4ZD",
    "vallentuna": "K4az_Bm6_hRV",
    "varmdo": "15nx_Vut_GrH",
    "vasteras": "8deT_FRF_2SP",
    "vaxholm": "9aAJ_j6L_DST",
    "vellinge": "Tcog_5sH_b46",
    "gothenburg": "PVZL_BQT_XtL",
}


class _Pushback(Exception):
    """The API refused the request (403 or 429)."""


def _plain(text: str) -> str:
    """*text* lowercased without accents or a trailing *, for the municipality table."""
    return unicodedata.normalize("NFKD", text.rstrip("*").lower()).encode("ascii", "ignore").decode()


def _municipalities(config: dict) -> list[str]:
    """Concept ids of the profile location's municipality first, then of the towns around it that the city's
    country data lists. [] for a place the table does not know (all of Sweden is searched). Pure."""
    location = (config.get("location") or "").strip()
    if not location:
        return []
    names = [location.split(",")[0], *sdk.city_names(location)]
    ids: list[str] = []
    for name in names:
        found = _MUNICIPALITIES.get(_plain(name))
        if found and found not in ids:
            ids.append(found)
    return ids


def _parse_date(raw: Any) -> datetime | None:
    """A publication_date (Stockholm local time, no offset) as an aware UTC datetime; None when unreadable."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_STOCKHOLM)
    return parsed.astimezone(timezone.utc)


def _params(keyword: str, municipalities: list[str], offset: int, since: datetime | None) -> dict:
    """The query of one page. Pure."""
    params: dict = {"q": keyword, "limit": _PAGE_SIZE, "offset": offset, "sort": "pubdate-desc"}
    if municipalities:
        params["municipality"] = list(municipalities)
    if since is not None:
        local = (since if since.tzinfo else since.replace(tzinfo=timezone.utc)).astimezone(_STOCKHOLM)
        params["published-after"] = local.strftime("%Y-%m-%dT%H:%M:%S")
    return params


def _url(params: dict) -> str:
    return f"{_API}?{urlencode(params, doseq=True, quote_via=quote)}"


def _parse_response(text: str) -> tuple[list[dict], int]:
    """(hits, total) of a JobSearch answer. ValueError when the text is not one. Pure."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"not JSON: {exc}") from exc
    hits = data.get("hits") if isinstance(data, dict) else None
    if not isinstance(hits, list):
        raise ValueError("no  list in the JobSearch answer")
    total = (data.get("total") or {}).get("value")
    return [h for h in hits if isinstance(h, dict)], total if isinstance(total, int) else len(hits)


def _is_live(hit: dict) -> bool:
    return not hit.get("removed")


def _location_text(hit: dict) -> str:
    """The municipalities of the ad's workplaces (else city, else region), Remote in front for work from home."""
    addresses = hit.get("workplace_addresses") or [hit.get("workplace_address") or {}]
    places: list[str] = []
    for address in addresses:
        address = address or {}
        place = (address.get("municipality") or address.get("city") or address.get("region") or "").strip()
        if place and place.lower() not in (p.lower() for p in places):
            places.append(place)
    label = ((hit.get("workplace_model") or {}).get("label") or "").lower()
    if "distans" in label:
        places.insert(0, "Remote")
    return ", ".join(places)


def _to_posting(hit: dict, scraped_at: datetime) -> dict | None:
    platform_id = str(hit.get("id") or "").strip()
    if not platform_id:
        return None
    title = (hit.get("headline") or "").strip()
    company = ((hit.get("employer") or {}).get("name") or "").strip()
    return JobPosting(
        id=make_job_id(_SITE, platform_id),
        title=title,
        company=company,
        location=_location_text(hit),
        url=hit.get("webpage_url") or f"https://arbetsformedlingen.se/platsbanken/annonser/{platform_id}",
        description=((hit.get("description") or {}).get("text") or "").strip(),
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=_parse_date(hit.get("publication_date")),
    ).model_dump(mode="json")


def _fetch(session: PoliteSession, url: str) -> str:
    """The answer at *url*; a certificate failure comes back as an error that says what to do."""
    try:
        return session.get(url).text
    except requests.exceptions.SSLError as exc:
        raise RuntimeError(f"{_TLS_HELP} ({exc})") from exc


def _get(session: PoliteSession, url: str) -> str:
    """`_fetch`, with a refusal (403, 429) raised as `_Pushback`."""
    try:
        return _fetch(session, url)
    except requests.HTTPError as exc:
        status = getattr(exc.response, "status_code", 0)
        if status in (403, 429):
            raise _Pushback(f"HTTP {status}") from exc
        raise


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """JobPosting dicts from Platsbanken: each keyword's newest ads in the profile's municipality, page by page."""
    keywords = config.get("search_keywords") or config.get("role_targets") or []
    since: datetime | None = kwargs.get("since")
    municipalities = _municipalities(config)
    scraped_at = datetime.now(timezone.utc)
    session = PoliteSession(min_delay=_MIN_DELAY, max_delay=_MAX_DELAY, timeout=30)
    seen: set[str] = set()
    postings: list[dict] = []

    for keyword in keywords:
        start = len(postings)
        for page in range(_MAX_PAGES):
            offset = page * _PAGE_SIZE
            try:
                hits, total = _parse_response(_get(session, _url(_params(keyword, municipalities, offset, since))))
            except _Pushback as exc:
                report(f"{_SITE}: {exc}; stopping for this run")
                record_error(_SITE, f"{_SITE}: {exc} (keyword={keyword!r}); stopped for this run")
                record_pushback(_SITE)
                return postings
            except Exception as exc:  # noqa: BLE001 - a bad keyword never stops the others
                report(f"search error (keyword={keyword!r}, offset={offset}): {exc}")
                record_error(_SITE, f"search error (keyword={keyword!r}, offset={offset}): {exc}")
                break
            if not hits and offset == 0:
                record_answered(_SITE)
            for hit in hits:
                posting = _to_posting(hit, scraped_at) if _is_live(hit) else None
                if posting is None:
                    continue
                platform_id = posting["platform_id"]
                if platform_id in seen or platform_id in known_ids:
                    continue
                seen.add(platform_id)
                posted = _parse_date(hit.get("publication_date"))
                if since is not None and posted is not None and posted < (since if since.tzinfo else since.replace(tzinfo=timezone.utc)):
                    continue
                postings.append(posting)
            if len(hits) < _PAGE_SIZE or offset + len(hits) >= total:
                break
        log_keyword_results(_SITE, keyword, postings[start:])
    return postings


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the first keyword's first page, mapped as  maps it. None when no keyword."""
    keywords = config.get("search_keywords") or config.get("role_targets") or []
    if not keywords:
        return None
    url = _url(_params(keywords[0], _municipalities(config), 0, None))
    session = PoliteSession(min_delay=_MIN_DELAY, max_delay=_MAX_DELAY, timeout=PROBE_TIMEOUT_S, max_retries=0)

    def parse(text: str):
        hits, _total = _parse_response(text)
        now = datetime.now(timezone.utc)
        return [p for p in (_to_posting(h, now) for h in hits if _is_live(h)) if p], True, ""

    return run_probe(lambda: _fetch(session, url), parse, "json")
