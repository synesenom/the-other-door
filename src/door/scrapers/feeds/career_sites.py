#!/usr/bin/env python3
"""Employer career sites, read through their sitemaps and schema.org JobPosting
markup (issue #232).

Most career-site platforms (iCIMS, Phenom, Paradox, Pinpoint, Easycruit, HR-ON,
Signatur, an employer's own CMS; not Emply, whose ads carry no markup: `feeds/emply.py`) publish a sitemap of their job pages and
mark each page up with schema.org ``JobPosting`` JSON-LD, because Google for
Jobs requires both. This reads exactly what is published for search engines:

1. the ``Sitemap:`` lines of the site's robots.txt (else ``/sitemap.xml``),
   preferring the ones named for jobs, through sitemap indexes;
2. the job pages among their URLs (by name, or every URL of a job sitemap), new
   since the cutoff when ``lastmod`` says so, newest first (a sitemap without
   ``lastmod`` from its end, where new jobs are usually appended); those whose path
   names the profile's area (its city, its country's cities) and a content word of its
   search keywords come first, then the local, then the on-topic ones (`_rank_urls`), then at most ``_MAX_PAGES`` per run
   and, for pages ordered by ``lastmod``, until ``_OLD_RUN`` in a row predate the cutoff;
3. each page's ``<script type="application/ld+json">`` ``JobPosting`` objects.

Two fallbacks cover sites that publish neither (docs/job-sites.md): a Workday tenant's sitemaps
stop at 100 jobs, so its own job list (``/wday/cxs/<tenant>/<site>/jobs``, the one its career page
uses) adds the rest; and an entry that is a listing page (``https://host/path/to/jobs``, as
``follow`` records when it finds no sitemap or markup) is read by its links to job ads, each ad built
from its title and main text when it carries no JobPosting markup.

Configured by ``career_sites``: the career sites' URLs or hosts. robots.txt is
honoured on every request (``PoliteSession``). A site behind a bot challenge is
left alone with a recorded reason, never worked around. Sites on platforms whose
own terms forbid robots on their systems are refused (Oracle Cloud has its own feed, `oracle_hcm`); Workday
tenants are read like any other site, from the sitemaps their robots.txt lists.

An entry is a career-site URL or host, e.g. ``careers.publicissapient.com`` or a
Workday tenant (``velux.wd3.myworkdayjobs.com/Velux_Commercial``).

Terms: https://schema.org/JobPosting — the markup sites publish for search
engines; each employer's own terms and robots.txt apply, read at run time.
"""

import gzip
import hashlib
import html as _html
import json
import re
import unicodedata
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

from door.scrapers.sdk import (
    FEED_DELAY, JobPosting, PoliteSession, PROBE_TIMEOUT_S, ProbeResult, RobotsBlocked, ad_links,
    career_apply_words, career_nav_words, career_path_stems, career_site_words, followed_name, generic_host_labels, tld_labels, host_of, keep_local, local_names, location_filter,
    log_keyword_results, make_job_id, map_by_group, name_pattern, parse_iso_date, probe_failure, record_entry_error,
    record_non_local, report, split_urls, squash, topic_words, workers,
)
from door.scrapers.sdk import Detection, parts

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("myworkdayjobs.com", "myworkdaysite.com", "icims.com", "talentbrew.com")

_SITE = "career_sites"
_MAX_PAGES = 200          # job pages fetched per site per run
_MAX_SITEMAPS = 20        # sitemap files read per site per run
_LASTMOD_GRACE = timedelta(days=60)  # a lastmod this much before the cutoff is trusted to mean "old"
_OLD_RUN = 10             # this many pages in a row posted before the cutoff end a site
_HEADERS = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

_MAX_WORKDAY_REQUESTS = 50  # job-list requests (20 jobs each) per Workday site per run
_TEXT_PROBE = 3             # pages in a row without markup (none with) before a site is read from page text
_MIN_TEXT = 200             # characters of main text that make a page a job ad when it has no markup
_NOISE_TAGS = ("script", "style", "nav", "header", "footer", "aside", "noscript", "svg", "iframe", "button", "select")
_LD_JSON = re.compile(r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)
_CHALLENGE = re.compile(r"just a moment|cf-challenge|attention required|authenticating\.\.\.|captcha", re.IGNORECASE)
# A script tag that loads a CAPTCHA widget (a contact or apply form's reCAPTCHA): not a challenge page.
_CAPTCHA_SCRIPT = re.compile(r"<script[^>]*\bsrc=[\"'][^\"']*(?:recaptcha|hcaptcha)[^>]*>", re.IGNORECASE)

# Platforms whose own terms forbid robots on the systems they run for their
# customers, and whose customers' career sites door therefore stays off (see
# docs/job-sites.md). Workday is not one of them: its tenants' robots.txt allows
# their career pages and lists their job sitemaps, which is all that is read.
_RESERVED_PLATFORMS = {
    "oraclecloud.com": "Oracle Cloud",
}


class _Challenged(Exception):
    """The site answered with a bot challenge."""


def _platform_reservation(host: str) -> str | None:
    """The platform name when *host* runs on one whose terms forbid automated access. Pure."""
    host = host.lower()
    return next((name for domain, name in _RESERVED_PLATFORMS.items() if host == domain or host.endswith("." + domain)), None)


def _base(entry: str) -> str:
    entry = entry.strip()
    parsed = urlparse(entry if "://" in entry else f"https://{entry}")
    return f"{parsed.scheme or 'https'}://{parsed.netloc.lower()}"


def _page_id(url: str) -> str:
    """A page's stable id: its URL, hashed. Pure."""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_sitemap(xml: str) -> tuple[str, list[tuple[str, datetime | None]]]:
    """``("index" | "urlset", [(loc, lastmod or None)])`` for a sitemap file; an
    unreadable one is an empty urlset. Pure."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return "urlset", []
    kind = "index" if _strip_ns(root.tag) == "sitemapindex" else "urlset"
    entries = []
    for node in root:
        fields = {_strip_ns(child.tag): (child.text or "").strip() for child in node}
        if fields.get("loc"):
            entries.append((fields["loc"], _parse_lastmod(fields.get("lastmod"))))
    return kind, entries


def _parse_lastmod(raw: str | None) -> datetime | None:
    value = parse_iso_date(raw or "")
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


@lru_cache(maxsize=1)
def _job_words() -> re.Pattern:
    stems = sorted(career_path_stems(), key=len, reverse=True)
    return re.compile("|".join(re.escape(s) for s in stems), re.IGNORECASE)


def _looks_like_job(url: str) -> bool:
    """Whether a URL's path names a job page (a job-word stem from the language data). Pure."""
    return bool(_job_words().search(urlparse(url).path))


def _load_json(raw: str):
    """JSON-LD as sites write it: JavaScript ``\\xHH`` escapes are tolerated."""
    try:
        return json.loads(raw, strict=False)
    except ValueError:
        return json.loads(re.sub(r"\\x([0-9a-fA-F]{2})", r"\\u00\1", raw), strict=False)


def _is_job_posting(node) -> bool:
    kind = node.get("@type") if isinstance(node, dict) else None
    kinds = kind if isinstance(kind, list) else [kind]
    return "JobPosting" in kinds


def _job_postings_from_html(html: str) -> list[dict]:
    """Every schema.org JobPosting object in a page's JSON-LD (top level, lists, ``@graph``). Pure."""
    found = []
    for match in _LD_JSON.finditer(html or ""):
        try:
            data = _load_json(match.group(1).strip())
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        for node in stack:
            if not isinstance(node, dict):
                continue
            if _is_job_posting(node):
                found.append(node)
            graph = node.get("@graph")
            if isinstance(graph, list):
                found.extend(n for n in graph if _is_job_posting(n))
    return found


def _text(value) -> str:
    if isinstance(value, dict):
        value = value.get("name") or ""
    return re.sub(r"\s+", " ", _html.unescape(str(value or ""))).strip()


def _country_text(country) -> str:
    """A country given as text, a ``{"name"}`` or only an ``{"@id"}``/``{"value"}`` code."""
    if isinstance(country, dict):
        return _text(country) or _text(country.get("@id") or country.get("value"))
    return _text(country)


def _place_text(place) -> str:
    if isinstance(place, str):
        return _text(place)
    address = (place or {}).get("address") if isinstance(place, dict) else None
    if isinstance(address, str):
        return _text(address)
    if not isinstance(address, dict):
        return _text(place) if isinstance(place, dict) else ""
    region = _text(address.get("addressRegion"))
    parts = [_text(address.get("addressLocality")), "" if region.lower() in ("others", "other") else region,
             _country_text(address.get("addressCountry"))]
    if not parts[0]:
        street = _text(address.get("streetAddress"))
        if street:
            return street
    return ", ".join(p for p in parts if p)


def _requirements_text(value) -> str:
    """``applicantLocationRequirements`` (one place or a list) as text, ``"; "`` apart. Pure."""
    items = value if isinstance(value, list) else [value]
    return "; ".join(t for t in (_place_text(i) for i in items) if t)


def _location_text(job: dict) -> str:
    """Locations from ``jobLocation`` (one place or a list), else from ``applicantLocationRequirements``;
    ``Remote`` for a telecommute job. Pure."""
    places = job.get("jobLocation")
    texts = [t for t in (_place_text(p) for p in (places if isinstance(places, list) else [places])) if t]
    text = "; ".join(texts)
    text = text or _requirements_text(job.get("applicantLocationRequirements"))
    if str(job.get("jobLocationType") or "").upper() == "TELECOMMUTE":
        return f"Remote, {text}" if text else "Remote"
    return text


def _company(job: dict, host: str) -> str:
    """``hiringOrganization``'s name, without a trailing "Careers"/"Jobs"; else the host. Pure."""
    name = _text(job.get("hiringOrganization"))
    words = "|".join(re.escape(w) for w in sorted(career_site_words(), key=len, reverse=True))
    return re.sub(rf"\s+(?:{words})$", "", name, flags=re.IGNORECASE).strip() or host


def _description(job: dict) -> str:
    raw = _html.unescape(_html.unescape(str(job.get("description") or "")))
    text = re.sub(r"(?i)<br\s*/?>|</(p|li|h\d|div)>", "\n", raw)
    text = _html.unescape(re.sub(r"<[^>]+>", " ", text)).replace("\xa0", " ")
    lines = (re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def _is_challenge(html: str, headers) -> bool:
    """A bot-challenge page or a ``cf-mitigated`` header. Pure."""
    if any(k.lower() == "cf-mitigated" for k in (headers or {})):
        return True
    return bool(_CHALLENGE.search(_CAPTCHA_SCRIPT.sub("", (html or "")[:5000])))


def _to_posting(job: dict, page_url: str, host: str, scraped_at: datetime, name: str = "") -> dict:
    title = _text(job.get("title"))
    company = name or _company(job, host)
    platform_id = _page_id(page_url)
    apply = job.get("url") if isinstance(job.get("url"), str) and job.get("url", "").startswith("http") else page_url
    posting = JobPosting(
        id=make_job_id(_SITE, platform_id),
        title=title,
        company=company,
        location=_location_text(job),
        url=page_url,
        description=_description(job),
        source=_SITE,
        scraped_at=scraped_at,
        platform_id=platform_id,
        posted_at=parse_iso_date(_text(job.get("datePosted"))),
        apply_type="external",
        apply_url=apply,
    )
    return posting.model_dump(mode="json")


def _squash_space(text: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(text or "")).strip()


def _page_title(soup: BeautifulSoup) -> str:
    """A job page's title without markup: its first real ``<h1>``, else ``og:title``, else the ``<title>``
    up to its first separator; a leading "Careers:"-style word is dropped. Pure."""
    generic = {w.lower() for w in career_nav_words()} | {w.lower() for w in career_site_words()} | {"cookies", "cookie"}
    title = ""
    for h1 in soup.find_all("h1"):
        text = _squash_space(h1.get_text(" ", strip=True))
        if text and text.lower() not in generic and len(text) <= 200:
            title = text
            break
    if not title:
        og = soup.find("meta", attrs={"property": "og:title"})
        if og is not None and og.get("content"):
            title = _squash_space(og["content"])
    if not title and soup.title is not None:
        title = re.split(r"\s+[|\u2013\u2014]\s+| - ", _squash_space(soup.title.get_text()))[0].strip()
    words = "|".join(re.escape(w) for w in sorted(career_site_words(), key=len, reverse=True))
    return re.sub(rf"^(?:{words})\s*:\s*", "", title, flags=re.IGNORECASE).strip()


def _page_company(soup: BeautifulSoup, host: str) -> str:
    """The employer a job page names: ``og:site_name``, else the part of its ``<title>`` after the
    separator ("... | Careers at Aegir Insights"), else the host's own label. Pure."""
    og = soup.find("meta", attrs={"property": "og:site_name"})
    if og is not None and og.get("content"):
        return _squash_space(og["content"])
    parts = re.split(r"\s+[|\u2013\u2014]\s+| - ", _squash_space(soup.title.get_text()) if soup.title else "")
    if len(parts) > 1:
        words = "|".join(re.escape(w) for w in sorted(career_site_words(), key=len, reverse=True))
        tail = re.sub(rf"^(?:{words})\s+(?:at|hos|i)\s+", "", parts[-1].strip(), flags=re.IGNORECASE)
        tlds = "|".join(re.escape(t) for t in tld_labels())
        tail = re.sub(rf"\.(?:{tlds})$", "", tail, flags=re.IGNORECASE)
        if tail:
            return tail
    skip = {*generic_host_labels(), *(part for t in tld_labels() for part in t.split("."))}
    labels = [l for l in host.lower().split(".") if l not in skip]
    return (labels[-1] if labels else host).capitalize()


def _main_text(soup: BeautifulSoup) -> str:
    """The text of a page's main part (``<main>``/``<article>`` when it holds enough, else the body)
    without navigation, header and footer, one line per block. Pure."""
    for tag in soup.find_all(_NOISE_TAGS):
        tag.decompose()
    best = ""
    for root in (soup.find("main"), soup.find("article"), soup.body or soup):
        if root is None:
            continue
        lines = (re.sub(r"[ \t\r\f\v\xa0]+", " ", line).strip() for line in root.get_text("\n").split("\n"))
        text = "\n".join(line for line in lines if line)
        if len(text) >= _MIN_TEXT:
            return text
        best = best or text
    return best


def _has_job_signals(soup: BeautifulSoup, page_url: str) -> bool:
    """Whether a page shows it is a job ad: a job word in its URL path, or a link or button that
    starts an application ("Apply now", "Ansøg"). A people profile or an article has neither. Pure."""
    if _looks_like_job(page_url):
        return True
    words = {w.lower() for w in career_apply_words()}
    return any(_squash_space(tag.get_text(" ", strip=True)).lower() in words for tag in soup.find_all(["a", "button"]))


def _text_posting(html: str, page_url: str, host: str, scraped_at: datetime, name: str = "",
                  require_job_signals: bool = False) -> dict | None:
    """A posting built from a job page that carries no JobPosting markup: its title, its employer
    (the followed *name* when given), its main text and, when the page states one, its publication
    date. None when the page has no title or too little text to be an ad, or, with
    *require_job_signals*, shows no sign of being a job ad (`_has_job_signals`). Pure."""
    soup = BeautifulSoup(html or "", "html.parser")
    if require_job_signals and not _has_job_signals(soup, page_url):
        return None
    title = _page_title(soup)
    company = name or _page_company(soup, host)
    published = None
    for meta in (soup.find("meta", attrs={"property": "article:published_time"}), soup.find("meta", attrs={"name": "date"})):
        if meta is not None and meta.get("content"):
            published = parse_iso_date(meta["content"])
            break
    if published is None:
        time_tag = soup.find("time", attrs={"datetime": True})
        published = parse_iso_date(time_tag["datetime"]) if time_tag is not None else None
    text = _main_text(soup)
    if not title or len(text) < _MIN_TEXT:
        return None
    platform_id = _page_id(page_url)
    posting = JobPosting(
        id=make_job_id(_SITE, platform_id), title=title, company=company, location="",
        url=page_url, description=text, source=_SITE, scraped_at=scraped_at, platform_id=platform_id,
        posted_at=published, apply_type="external", apply_url=page_url,
    )
    return posting.model_dump(mode="json")


_WORKDAY_NOT_SITES = {"refreshfacet", "wday"}  # robots.txt paths of a Workday tenant that name no career site


def _workday_roots(sitemap_urls, base: str, disallowed=()) -> dict[str, str]:
    """``{site: URL prefix of its job pages}`` for the Workday sites a robots.txt lists sitemaps for:
    ``<tenant host>/<Site>/siteMap.xml`` or the shared ``myworkdaysite.com/recruiting/<tenant>/<Site>/siteMap.xml``.
    A robots.txt with no such line (Novonesis, Thermo Fisher) names its sites only in its *disallowed*
    paths, ``/<Site>/``; those are read instead (``/refreshFacet/`` is no site). Pure."""
    host, tenant = urlparse(base).netloc.lower(), urlparse(base).netloc.lower().split(".")[0]
    roots: dict[str, str] = {}
    for url in sitemap_urls:
        p = urlparse(url)
        direct = re.fullmatch(r"/([^/]+)/siteMap\.xml", p.path, re.IGNORECASE) if p.netloc.lower() == host else None
        shared = re.fullmatch(rf"/recruiting/{re.escape(tenant)}/([^/]+)/siteMap\.xml", p.path, re.IGNORECASE)
        if direct:
            roots.setdefault(direct.group(1), f"{base}/{direct.group(1)}")
        elif shared:
            roots.setdefault(shared.group(1), f"{p.scheme}://{p.netloc}/recruiting/{tenant}/{shared.group(1)}")
    if not roots:
        for path in disallowed:
            site = re.fullmatch(r"/([^/*$]+)/?", path)
            if site and site.group(1).lower() not in _WORKDAY_NOT_SITES:
                roots.setdefault(site.group(1), f"{base}/{site.group(1)}")
    return roots


def _workday_sites(sitemap_urls, base: str, disallowed=()) -> list[str]:
    """The names of a Workday tenant's career sites, from the sitemap (else disallow) lines of its robots.txt. Pure."""
    return list(_workday_roots(sitemap_urls, base, disallowed))


def _workday_urls(session: PoliteSession, base: str, sitemap_urls, config: dict | None = None,
                  disallowed=()) -> list[str]:
    """The job pages of a Workday tenant's own job list (``/wday/cxs/<tenant>/<site>/jobs``, the JSON its
    career page loads): its sitemaps stop at 100 jobs, the list does not. Twenty jobs a request, only the
    first answer states the total. A failing site is reported and skipped.

    With a *config* whose location names a known country the list is asked for that country's jobs only:
    the first, unfiltered answer carries the location facets (`locality.location_filter` picks the
    country's values), the paging restarts with them applied, and the jobs left out are recorded as
    non-local. Without a facet to filter on, or a country, the whole list is read."""
    tenant = urlparse(base).netloc.lower().split(".")[0]
    urls: list[str] = []
    for site, prefix in _workday_roots(sitemap_urls, base, disallowed).items():
        api = f"{base}/wday/cxs/{tenant}/{site}/jobs"
        offset, total, applied, decided, all_jobs = 0, None, {}, config is None, None
        for _ in range(_MAX_WORKDAY_REQUESTS):
            try:
                data = session.post(api, json={"appliedFacets": applied, "limit": 20, "offset": offset, "searchText": ""},
                                    headers={"Accept": "application/json"}).json()
            except (requests.RequestException, RobotsBlocked, ValueError) as exc:
                report(f"{api}: {exc}")
                break
            jobs = data.get("jobPostings") if isinstance(data, dict) else None
            if not decided:
                decided = True
                chosen = location_filter(data.get("facets"), config) if isinstance(data, dict) else None
                if chosen is not None:
                    all_jobs = data["total"] if isinstance(data.get("total"), int) else None
                    if not chosen[1]:                      # the tenant has no local location at all
                        record_non_local(_SITE, all_jobs or 0)
                        break
                    applied = {chosen[0]: chosen[1]}
                    continue                               # ask again, for the local jobs only
            if not jobs:
                break
            urls += [prefix + j["externalPath"] for j in jobs if isinstance(j, dict) and j.get("externalPath")]
            if offset == 0 and isinstance(data.get("total"), int):
                total = data["total"]
                if applied and all_jobs is not None:
                    record_non_local(_SITE, all_jobs - total)
            offset += len(jobs)
            if total is not None and offset >= total:
                break
    return list(dict.fromkeys(urls))


def _listing_entry(entry: str) -> str | None:
    """The entry as a listing page's URL when it names one (a path or a query beyond the host); None
    for a bare host and for Workday tenants (whose paths name a site, read through their job list). Pure."""
    text = entry.strip()
    parsed = urlparse(text if "://" in text else f"https://{text}")
    if parsed.netloc.lower().endswith((".myworkdayjobs.com", ".myworkdaysite.com")):
        return None
    if not parsed.path.strip("/") and not parsed.query:
        return None
    return parsed.geturl()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _get(session: PoliteSession, url: str) -> requests.Response:
    """GET through the paced session; a bot challenge raises `_Challenged`."""
    try:
        resp = session.get(url, headers=_HEADERS)
    except requests.HTTPError as exc:
        response = exc.response
        if response is not None and response.status_code in (401, 403, 429, 503) and _is_challenge(response.text, response.headers):
            raise _Challenged(url) from None
        raise
    if "charset" not in resp.headers.get("Content-Type", "").lower():
        resp.encoding = "utf-8"  # requests would guess Latin-1 for text/* without a charset
    if _is_challenge(resp.text, resp.headers) and not _job_postings_from_html(resp.text):
        raise _Challenged(url)
    return resp


def _sitemap_text(resp: requests.Response) -> str:
    content = resp.content
    if content[:2] == b"\x1f\x8b":
        content = gzip.decompress(content)
    return content.decode("utf-8", errors="replace")


def _job_urls(session: PoliteSession, base: str, since: datetime | None) -> list[str]:
    """The job pages a site's sitemaps list, newest first, new since *since* when ``lastmod`` says so."""
    return _dated_job_urls(session, base, since)[0]


def _dated_job_urls(session: PoliteSession, base: str, since: datetime | None) -> tuple[list[str], set[str]]:
    """`_job_urls` plus the URLs whose place in the order came from a sitemap ``lastmod``."""
    start = list(session.sitemaps(base + "/")) or [base + "/sitemap.xml"]
    queue = [u for u in start if _looks_like_job(u)] or start
    seen_maps: set[str] = set()
    found: dict[str, datetime | None] = {}
    order: list[str] = []  # undated pages, newest (last listed) first
    while queue and len(seen_maps) < _MAX_SITEMAPS:
        sitemap = queue.pop(0)
        if sitemap in seen_maps:
            continue
        seen_maps.add(sitemap)
        try:
            kind, entries = _parse_sitemap(_sitemap_text(_get(session, sitemap)))
        except (requests.RequestException, RobotsBlocked, OSError) as exc:
            report(f"{sitemap}: {exc}")
            continue
        if kind == "index":
            children = [loc for loc, _ in entries]
            queue.extend([c for c in children if _looks_like_job(c)] or children)
            continue
        job_map = _looks_like_job(urlparse(sitemap).path.rsplit("/", 1)[-1])
        for loc, lastmod in reversed(entries):
            if not (job_map or _looks_like_job(loc)) or loc.rstrip("/") == base:
                continue
            if since is not None and lastmod is not None and lastmod < since - _LASTMOD_GRACE:
                continue
            if loc not in found:
                found[loc] = lastmod
                order.append(loc)
    # A sitemap that dates every page the same day (the day it was generated) says nothing about age.
    informative = len({lm.date() for lm in found.values() if lm is not None}) > 2
    if not informative:
        return _dedupe_locales(order), set()
    dated = sorted((u for u in order if found[u] is not None), key=lambda u: found[u], reverse=True)
    ordered = _dedupe_locales(dated + [u for u in order if found[u] is None])
    return ordered, set(dated) & set(ordered)


_LOCALE_SEGMENT = re.compile(r"global|[a-z]{2}|[a-z]{2}[-_][a-z]{2,4}", re.IGNORECASE)


def _locale_key(url: str) -> tuple[str, str, str]:
    """``(host, path without its leading locale segments, query)``: the same job in another locale
    (``/global/en/job/52318/x``, ``/ca/fr/job/52318/x``) has the same key. Pure."""
    parsed = urlparse(url)
    segments = [s for s in parsed.path.split("/") if s]
    lead = 0
    while lead < 2 and lead < len(segments) - 1 and _LOCALE_SEGMENT.fullmatch(segments[lead]):
        lead += 1
    return parsed.netloc.lower(), "/".join(segments[lead:]).lower(), parsed.query


def _dedupe_locales(urls: list[str]) -> list[str]:
    """*urls* with the locale twins of one job reduced to one URL, the English one when there is a choice
    (else the first); the order of first appearances is kept. A URL with no twin is untouched. Pure."""
    groups: dict[tuple, list[str]] = {}
    for url in urls:
        groups.setdefault(_locale_key(url), []).append(url)

    def english(url: str) -> bool:
        return any(s.lower() in ("en", "global") or s.lower().startswith("en-") or s.lower().startswith("en_")
                   for s in urlparse(url).path.split("/")[1:3])

    chosen = {key: next((u for u in group if english(u)), group[0]) for key, group in groups.items()}
    return [chosen[key] for key in dict.fromkeys(_locale_key(u) for u in urls)]


# Shared with the title gate of `follow` and `collect` (`door.matching.title_fit`).
_squash = squash
_name_pattern = name_pattern


_area_names = local_names


_topic_words = topic_words


def _rank_urls(urls: list[str], config: dict) -> tuple[list[str], tuple[int, int, int, int]]:
    """*urls* in four tiers, each in its given order: path names the profile's area and a
    content word of its search keywords; the area only; a content word only; the rest. With
    the tier sizes. Pure."""
    area, topic = _name_pattern(_area_names(config)), _name_pattern(_topic_words(config))
    tiers: tuple[list[str], list[str], list[str], list[str]] = ([], [], [], [])
    for url in urls:
        path = _squash(unquote(urlparse(url).path))
        local, on_topic = bool(area and area.search(path)), bool(topic and topic.search(path))
        tiers[0 if local and on_topic else 1 if local else 2 if on_topic else 3].append(url)
    return [u for tier in tiers for u in tier], tuple(len(t) for t in tiers)  # type: ignore[return-value]


def _site_urls(session: PoliteSession, entry: str, base: str, since, config: dict | None = None) -> tuple[list[str], set[str], bool]:
    """The pages to read for one entry: its sitemaps' job pages (plus a Workday tenant's own job list),
    else, when the entry names a listing page, the ads that page links. With whether they came from a
    listing and the URLs whose order came from a ``lastmod``."""
    config = config or {}
    urls, dated = _dated_job_urls(session, base, since)
    urls, dropped = split_urls(urls, config)      # jobs whose path names only another country's place
    dated &= set(urls)
    if urlparse(base).netloc.lower().endswith(".myworkdayjobs.com"):
        have = set(urls)
        urls = urls + [u for u in _workday_urls(session, base, session.sitemaps(base + "/"), config,
                                                           session.disallowed(base + "/")) if u not in have]
    listing = _listing_entry(entry)
    if urls or listing is None:
        if dropped:
            record_non_local(_SITE, dropped)
        return urls, dated, False
    resp = _get(session, listing)
    links, dropped_links = split_urls(ad_links(resp.text, resp.url or listing), config)
    if dropped + dropped_links:
        record_non_local(_SITE, dropped + dropped_links)
    return links, set(), True


def _scrape_site(session: PoliteSession, entry: str, config: dict, known_ids: frozenset[str], since, scraped_at,
                 name: str = "") -> list[dict]:
    base = _base(entry)
    host = urlparse(base).netloc
    platform = _platform_reservation(host)
    if platform:
        message = f"{host}: skipped — {platform}'s terms forbid automated access to the sites it hosts"
        report(message)
        record_entry_error(_SITE, entry, message, blocked=True)
        return []
    postings: list[dict] = []
    warned = False
    old_in_a_row = 0
    marked = False                                     # a page with JobPosting markup was seen
    text_pages = bool(_listing_entry(entry))           # pages without markup are read from their text
    held: list[tuple[str, requests.Response]] = []     # unmarked pages, until text reading is decided
    try:
        all_urls, dated, from_listing = _site_urls(session, entry, base, since, config)
        text_pages = text_pages and from_listing
        # Pages of a sitemap read as text (no listing vouches for them) must show they are job ads.
        signals = not text_pages
        ranked, (n_both, n_local, n_topic, _) = _rank_urls([u for u in all_urls if _page_id(u) not in known_ids], config)
        urls = ranked[:_MAX_PAGES]
        report(f"{host}: {len(ranked)} pages, ranked first: {n_both} local and on topic, {n_local} local, "
               f"{n_topic} on topic; {max(len(ranked) - _MAX_PAGES, 0)} cut by the {_MAX_PAGES}-page cap")
        for i, url in enumerate(urls, 1):
            report(f"{host} pages", i, len(urls))
            try:
                resp = _get(session, url)
            except (requests.RequestException, RobotsBlocked) as exc:
                report(f"{url}: {exc}")
                continue
            page_url = resp.url or url
            jobs = _job_postings_from_html(resp.text)
            if not jobs and not warned:
                warned = True
                report(f"{host}: no JobPosting markup at {url}")
            raw = [_to_posting(job, page_url, host, scraped_at, name) for job in jobs[:1] if _text(job.get("title"))]
            new = keep_local(raw, config, _SITE)
            if jobs:
                marked = True
                held.clear()
            elif text_pages:
                new = [p for p in [_text_posting(resp.text, page_url, host, scraped_at, name, signals)] if p]
            elif not marked:
                held.append((page_url, resp))
                if len(held) >= _TEXT_PROBE:  # a site whose pages never carry markup: read them as text
                    text_pages = True
                    new = [p for p in (_text_posting(r.text, u, host, scraped_at, name, signals) for u, r in held) if p]
                    held.clear()
            postings.extend(new)
            # A page dropped as non-local still dates its place in the sitemap's order.
            dating = raw if jobs else new
            posted = parse_iso_date(dating[0]["posted_at"]) if dating and dating[0]["posted_at"] else None
            # Only a lastmod-ordered page says anything about those after it; an undated
            # sitemap (Workday) lists old and new jobs in no order, so only the cap ends it.
            if since is not None and posted is not None and url in dated:
                old_in_a_row = old_in_a_row + 1 if _aware(posted) < since else 0
                if old_in_a_row >= _OLD_RUN:
                    report(f"{host}: {_OLD_RUN} pages in a row older than the cutoff; stopping")
                    break
    except _Challenged as exc:
        message = f"{host}: bot protection; not attempted ({exc})"
        report(message)
        record_entry_error(_SITE, entry, message, blocked=True)
        return []
    except (requests.RequestException, RobotsBlocked) as exc:
        report(f"{host}: {exc}")
        record_entry_error(_SITE, entry, f"{host}: {exc}")
    return postings


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """The job postings of each configured career site, from its sitemaps and markup."""
    entries = [e for e in config.get("career_sites") or [] if e.strip()]
    if not entries:
        return []
    scraped_at = datetime.now(timezone.utc)
    since = kwargs.get("since")
    session = PoliteSession(min_delay=FEED_DELAY[0], max_delay=FEED_DELAY[1], timeout=30, headers=_HEADERS)

    # Sites on different hosts are crawled side by side (each host's pages still one at a
    # time, paced by the session); the dedup below is in config order, whatever the timing.
    scraped = map_by_group(
        entries, lambda e: host_of(_base(e)),
        lambda e: _scrape_site(session, e, config, known_ids, since, scraped_at,
                               followed_name(config, "career_sites", e)), workers(config),
    )
    postings: list[dict] = []
    seen: set[str] = set()
    for entry, found in zip(entries, scraped):
        site_postings = [p for p in found if p["platform_id"] not in seen and not seen.add(p["platform_id"])]
        log_keyword_results(_SITE, _base(entry), site_postings)
        postings.extend(site_postings)
    return postings


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: the first site's sitemaps and its newest job page.
    ``None`` when no site is configured."""
    entries = [e for e in config.get("career_sites") or [] if e.strip()]
    if not entries:
        return None
    base = _base(entries[0])
    host = urlparse(base).netloc
    session = PoliteSession(min_delay=0.2, max_delay=0.5, timeout=PROBE_TIMEOUT_S, max_retries=0, headers=_HEADERS)
    try:
        if _platform_reservation(host):
            raise RobotsBlocked(base)
        urls = _job_urls(session, base, None)
        listing = _listing_entry(entries[0])
        if not urls and listing:
            page = _get(session, listing)
            urls = ad_links(page.text, page.url or listing)
        if not urls:
            return {"raw": "", "ext": "html", "postings": [], "structure_ok": False, "robots": "allowed",
                    "reason": "no job pages in the site's sitemaps"}
        resp = _get(session, urls[0])
    except _Challenged as exc:
        return {"raw": "", "ext": "html", "postings": [], "structure_ok": False, "wall": True,
                "reason": f"bot protection ({exc})"}
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        return probe_failure(exc, "html")
    jobs = _job_postings_from_html(resp.text)
    scraped_at = datetime.now(timezone.utc)
    postings = [_to_posting(j, resp.url or urls[0], host, scraped_at) for j in jobs[:1]]
    if not jobs and listing:  # a listing entry is read from the ads' text
        postings = [p for p in [_text_posting(resp.text, resp.url or urls[0], host, scraped_at)] if p]
    result: ProbeResult = {"raw": resp.text, "ext": "html", "structure_ok": bool(postings), "robots": "allowed",
                           "postings": postings}
    if not postings:
        result["reason"] = f"no JobPosting markup at {urls[0]}"
    return result


# --- feed detection (issue #282): what `core/ats_detect.py` and `commands/companies.py` ask ---

_JOB_POSTING = re.compile(r"""["']@type["']\s*:\s*(\[[^\]]*)?["']JobPosting["']""")


def _workday(tenant_host: str, seen: str) -> Detection:
    """A Workday tenant: read as a career site, through the sitemaps its robots.txt lists."""
    return Detection("career_sites", f"https://{tenant_host}",
                     f"Workday career site {tenant_host} ({seen}), read through its sitemaps and job markup")


def detect_url(url: str) -> Detection | None:
    """A Workday tenant link (``<tenant>.wd3.myworkdayjobs.com``, or the shared ``myworkdaysite.com`` host)."""
    host, path, _query = parts(url.strip())
    if host.endswith(".myworkdayjobs.com") and host.count(".") == 3:
        return _workday(host, url)
    if host.endswith(".myworkdaysite.com") and len(path) >= 2 and path[0].lower() == "recruiting":
        # The shared host's robots.txt lists no sitemaps; the tenant's own host does.
        return _workday(f"{path[1].lower()}.{host.split('.')[0]}.myworkdayjobs.com", url)
    return None

def _workday_site(path: list[str]) -> str | None:
    """The career site a Workday link's path names: the segment before ``job``, else the first one that is no
    locale (``/en-US/Acme_Careers/job/...``, ``/Acme_Careers``). Pure."""
    lower = [p.lower() for p in path]
    if "job" in lower and lower.index("job") > 0:
        return path[lower.index("job") - 1]
    return next((p for p in path if not re.fullmatch(r"[a-z]{2}(-[A-Za-z]{2})?", p)), None)


def _workday_job_count(session: PoliteSession, base: str, tenant: str, site: str) -> int:
    """How many jobs a Workday site lists publicly: the ``total`` of its own job list, else the jobs of its
    ``siteMap.xml``; 0 when both are empty or unreadable."""
    try:
        data = session.post(f"{base}/wday/cxs/{tenant}/{site}/jobs", headers={"Accept": "application/json"},
                            json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}).json()
        total = data.get("total") if isinstance(data, dict) else None
        if isinstance(total, int) and total > 0:
            return total
    except (requests.RequestException, RobotsBlocked, ValueError):
        pass
    try:
        return len(re.findall(r"<loc>", session.get(f"{base}/{site}/siteMap.xml", headers={"Accept": "application/xml"}).text))
    except (requests.RequestException, RobotsBlocked):
        return 0


def follow_link(session: PoliteSession, url: str) -> Detection | None:
    """A Workday link found on another platform's pages (Phenom's apply links): the career site
    ``https://<tenant>.wdN.myworkdayjobs.com/<Site>`` when its public job list is not empty, else a
    detection with no entry ("can't yet"); None for a link that is no Workday site (#438)."""
    host, path, _query = parts(url.strip())
    site = _workday_site(path) if host.endswith(".myworkdayjobs.com") and host.count(".") == 3 else None
    if site is None:
        return None
    count = _workday_job_count(session, f"https://{host}", host.split(".")[0], site)
    if count:
        return Detection("career_sites", f"https://{host}/{site}",
                         f"Workday site {host}/{site} lists {count} {'job' if count == 1 else 'jobs'} publicly")
    return Detection("career_sites", None, f"Workday site {host}/{site} lists no jobs publicly", "cant_yet")


# The Workday hosts a tenant named like an employer is tried on, most used first.
WORKDAY_DATA_CENTERS = ("wd3", "wd1", "wd5", "wd103")
_MAX_TENANT_SITES = 2   # career sites of one tenant whose job list is read


def tenant_probe(session: PoliteSession, slug: str) -> Detection | None:
    """The Workday tenant named *slug* (an employer whose own website was found, but whose careers pages are
    drawn by script, #566): ``https://<slug>.wdN.myworkdayjobs.com/<Site>``, the first career site its robots.txt
    names that lists jobs publicly. One robots.txt read per data center, a job list read per site; None when no
    tenant of that name answers."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug or ""):
        return None
    for dc in WORKDAY_DATA_CENTERS:
        host = f"{slug}.{dc}.myworkdayjobs.com"
        base = f"https://{host}"
        for site in _workday_sites(session.sitemaps(base + "/"), base, session.disallowed(base + "/"))[:_MAX_TENANT_SITES]:
            count = _workday_job_count(session, base, slug, site)
            if count:
                return Detection("career_sites", f"{base}/{site}",
                                 f"Workday site {host}/{site}, named like the employer, lists {count} "
                                 f"{'job' if count == 1 else 'jobs'} publicly")
    return None


def feed_url(entry: str) -> str | None:
    """None: a link to the site names the account, no feed check is needed."""
    return None


def detect_cname(host: str, target: str, where: str) -> Detection | None:
    """A career host on a Workday, TalentBrew or iCIMS tenant."""
    if target.endswith(".talentbrew.com") or target.endswith(".icims.com"):
        return Detection("career_sites", f"https://{host}", where)
    if target.endswith(".myworkdayjobs.com") and target.count(".") == 3:
        return _workday(target, where)
    return None


def detect_html(html: str, url: str) -> Detection | None:
    """A page that carries schema.org JobPosting markup is a career site."""
    if _JOB_POSTING.search(html):
        return Detection("career_sites", f"https://{urlparse(url).netloc.lower()}", f"{url} carries schema.org JobPosting markup")
    return None
