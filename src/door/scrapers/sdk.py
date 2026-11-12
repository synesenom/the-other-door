"""The one module a site scraper imports `door` code from.

A site module (`src/door/scrapers/<site>.py`, every module in `core.sites.SITES`) has no
other `door` import; `tests/scrapers/test_scraper_imports_unit.py` enforces it. The SDK is
thin: re-exports of what `door.scrapers` already provides, and named wrappers that call the
defining module at call time (so a test patching `title_fit` or `i18n` still reaches them).
A refactor of matching or i18n changes this file, not every scraper.

Models
    `JobPosting`, `make_job_id`: the posting schema and its stable id.

HTTP
    `PoliteSession` (per-host pacing, robots, retries), `USER_AGENT`, `RobotsBlocked`,
    the delays `FEED_DELAY`/`PROBE_TIMEOUT_S`, `host_of`, `workers`, `map_by_group`.

Reporting (scrapers never `print`)
    `report`, `record_error`, `record_pushback`, `record_non_local`, `record_answered`
    (read the site's own "no hits" answer: a quiet day, not a changed site), `tracked`,
    `log_keyword_results`.

Probing
    `ProbeResult`, `run_probe`, `probe_failure`.

Feed helpers
    `scrape_feeds`, `strip_html`, `parse_iso_date`.

Feed platforms (the detection half of a per-company feed site, issue #282)
    A feed site's module also says how its feed is found, in plain functions that
    `core/ats_detect.py` (a dispatcher over `ats_detect.PRECEDENCE`) and `commands/companies.py`
    call; none is required except the first two:
    `detect_url(url) -> Detection | None` (a careers or job link on the platform, with the entry
    it names, or `entry=None` when the link names no account),
    `feed_url(entry) -> str | None` (the endpoint that confirms a detected entry by listing jobs;
    `None` when the link's shape is proof enough) with `FEED_KEY` (the JSON key the list is under),
    `detect_cname(host, target, where) -> Detection | None` (a CNAME target, `where` the evidence text), `detect_html(html, url) -> Detection | None`
    (page signatures), `name_probes(slug) -> list[Probe]` (the public endpoints to try for a
    company name), and `resolve(...)` for a platform that needs more than a link.
    `resolve(session, det, url) -> Detection` reads further after a detection (a link into an inactive site, a
    front end whose pages name the system behind it); a platform that cannot be followed but whose link names the employer
    returns its detection with `employer` (and `site`) set, and `follow` then tries that name and site like any queued
    employer's (Visma Recruit, #526); `follow_link(session, url)` is the hook a module
    offers for such a link found on another platform's pages, and `tenant_probe(session, slug) -> Detection | None` the
    tenant named like an employer whose own website `follow` found (Workday's, from its robots.txt, #566). `name_page(entry, link) -> str` names the page
    that holds the employer's name when `link` is not it (an ad page, titled by the job).
    `Detection`, `Probe`, `parts`, `first`, `NOT_ACCOUNTS` and `unfollowable` build them. A platform
    The other door knows but does not follow has no `Site`: it is a detect-only module in `scrapers/feeds/` (`hr_on`, `phenom`, `ponty`, `jobaffinity`, `icims`).

Matching and i18n
    Wrappers over `title_fit`, `locality`, `ats_detect` and `i18n`; see each docstring.

Discovery sources (`core/discovery_sources.py`, issue #280)
    A module that tells `discover` which employers hire (LinkedIn) exposes `NAME`, `COUNTRIES`,
    `CONFIG_KEY`, `run(config, **kwargs) -> DiscoveryResult` and the optional hooks `enabled`,
    `extras(queue)` and `skip_employer(emp, state, now)`. `DiscoveryResult` and `Employer` describe
    what `run` returns; `name_key`, `is_job_board` and `awaiting_job_page` serve the hooks.

Context the engine puts in `config` (runtime keys, not declared in `Profile`)
    `_mode`: `"search"` or `"collect"`, which step is calling.
    `_country`: the profile `location`'s country as a lowercase ISO 3166 code, or `None`
    (resolved once by `_scrape_core`); read it through `country(config, served)`.
    `_names`: `{config_key: {entry: name}}`, the followed employers' names from `companies.json`
    (collect only); read it through `followed_name(config, config_key, entry, fallback)`.
    The freshness cutoff arrives as the `since=` keyword, not in `config`; turn it into a
    "last N days" filter with `look_back_days`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TypedDict
from datetime import datetime

from door import i18n
from door.core import ats_detect, freshness
from door.core.ats_detect import Detection
from door.core.models import JobPosting, make_job_id, normalize_platform_id, tenant_platform_id
from door.matching import locality, prefilter, title_fit
from door.scrapers import (
    PROBE_TIMEOUT_S, ProbeResult, log_keyword_results, parse_iso_date, probe_failure, record_entry_error,
    record_answered, record_error, record_non_local, record_pushback, report, run_probe, scrape_feeds, strip_html,
    tracked,
)
from door.scrapers._parallel import host_of, map_by_group, workers
from door.scrapers.http_client import FEED_DELAY, USER_AGENT, PoliteSession, RobotsBlocked

# Documentation for re-exports that carry no docstring of their own.
_DOCS: dict[str, str] = {
    "JobPosting": "The posting schema (id, title, company, location, url, description, posted_at, source).",
    "USER_AGENT": "The browser-like User-Agent every request carries.",
    "FEED_DELAY": "(min, max) seconds a PoliteSession pauses between requests to one host.",
    "PROBE_TIMEOUT_S": "Per-request timeout, in seconds, of a scraper's probe.",
    "Detection": "What a link, CNAME or page shows: `platform`, the feed `entry` (None when it names no followable "
                 "account) and the `evidence`; `config_key` is the key the scraper reads its entry under.",
    "NOT_ACCOUNTS": "Subdomains and first path segments that are never an account name (www, careers, jobs, ...).",
}

__all__ = [
    "JobPosting", "make_job_id", "normalize_platform_id", "tenant_platform_id", "PoliteSession", "USER_AGENT", "RobotsBlocked", "FEED_DELAY", "PROBE_TIMEOUT_S",
    "report", "record_error", "record_entry_error", "record_pushback", "record_answered", "record_non_local", "tracked", "log_keyword_results",
    "ProbeResult", "run_probe", "probe_failure", "scrape_feeds", "strip_html", "parse_iso_date",
    "host_of", "map_by_group", "workers",
    "on_topic", "topic_terms", "topic_words", "keywords", "squash", "name_pattern",
    "location_filter", "split_urls", "keep_local", "is_remote", "local_names", "country_is_non_local",
    "career_site_words", "generic_host_labels", "tld_labels", "career_nav_words", "career_apply_words", "career_path_stems", "city_names", "compile_words",
    "seniority_words", "stop_words", "transliteration", "word_pattern", "country_name",
    "ad_links", "from_url", "country", "look_back_days", "followed_name",
    "name_key", "is_job_board", "awaiting_job_page", "Employer", "DiscoveryResult",
    "Detection", "Probe", "parts", "first", "NOT_ACCOUNTS", "unfollowable", "follow_link", "career_links", "slug_candidates",
]


# --- matching ---------------------------------------------------------------------------

def on_topic(title: str, terms: list[str]) -> bool:
    """Whether a posting title mentions any content word of `terms` (synonyms included)."""
    return title_fit.on_topic(title, terms)


def topic_terms(config: dict) -> list[str]:
    """The search terms a title must fit, from the profile's keywords."""
    return title_fit.topic_terms(config)


def topic_words(config: dict) -> list[str]:
    """The content words of the profile's keywords."""
    return title_fit.topic_words(config)


def keywords(config: dict) -> list[str]:
    """The profile's search keywords (`search_keywords`, else `role_targets`)."""
    return title_fit.keywords(config)


def squash(text: str) -> str:
    """`text` lowercased with everything but letters and digits removed, for name comparison."""
    return title_fit.squash(text)


def name_pattern(names: list[str]) -> re.Pattern | None:
    """A compiled pattern matching any of the names, or `None` for none."""
    return title_fit.name_pattern(names)


def location_filter(facets, config: dict) -> tuple[str, list[str]] | None:
    """The `(facet, values)` that selects the profile country's jobs in a Workday facet answer."""
    return locality.location_filter(facets, config)


def split_urls(urls: list[str], config: dict) -> tuple[list[str], int]:
    """`(kept urls, dropped count)`: drops URLs whose path names only another country's place."""
    return locality.split_urls(urls, config)


def keep_local(postings: list[dict], config: dict, site: str) -> list[dict]:
    """`postings` without those whose `location` names only another country's place or ISO code (remote
    and location-less ones stay), the drops counted with `record_non_local(site, n)`."""
    kept, dropped = locality.split_postings(postings, config)
    if dropped:
        record_non_local(site, dropped)
    return kept


def is_remote(text: str) -> bool:
    """Whether `text` holds a remote, hybrid or home-based word (any supported language)."""
    return locality.is_remote(text)


def local_names(config: dict) -> list[str]:
    """The names of the profile country's places."""
    return locality.local_names(config)


def country_is_non_local(country: str | None, config: dict, *, remote: bool = False) -> bool:
    """Whether a posting in `country` is outside the profile's country (a remote one never is)."""
    return locality.country_is_non_local(country, config, remote=remote)


# --- i18n -------------------------------------------------------------------------------

def career_site_words() -> list[str]:
    """Words naming a career site ("careers", "karriere", ...) in the supported languages."""
    return i18n.career_site_words()


def generic_host_labels() -> list[str]:
    """Host labels that name no employer ("www", "careers", "karrier") in the supported countries."""
    return i18n.generic_host_labels()


def tld_labels() -> list[str]:
    """Domain endings of the supported countries and the global ones ("hu", "dk", "com", "io")."""
    return i18n.tld_labels()


def career_nav_words() -> list[str]:
    """Words of career navigation links in the supported languages."""
    return i18n.career_nav_words()


def career_path_stems() -> list[str]:
    """URL path stems of career pages in the supported languages."""
    return i18n.career_path_stems()


def career_apply_words() -> list[str]:
    """Link or button texts that start an application ("apply now", "ansøg") in the supported languages."""
    return i18n.career_apply_words()


def known_city(location: str) -> str | None:
    """The known city that `location` names (by its name or an alias), or None."""
    return i18n.known_city(location)


def location_fits(posting_location: str, config: dict) -> bool:
    """Whether a posting's free-text location suits the profile: it names the profile's city or a town
    of its commute area, is empty, remote or names no known place; or the profile accepts remote work
    or abroad. The match step's location pre-filter, for a board that cannot filter by place."""
    return prefilter._is_location_compatible(posting_location, config)


def city_names(location: str) -> list[str]:
    """The names a `location` goes by (its city and aliases)."""
    return i18n.city_names(location)


def compile_words(words: list[str]) -> re.Pattern:
    """One case-insensitive whole-word pattern matching any of `words`."""
    return i18n.compile_words(words)


def seniority_words() -> dict[str, str]:
    """Seniority words of the supported languages, mapped to their level."""
    return i18n.seniority_words()


def stop_words() -> list[str]:
    """Filler words of job titles in the supported languages."""
    return i18n.stop_words()


def transliteration() -> dict[int, str]:
    """A `str.translate` table spelling non-ASCII letters in ASCII (æ to ae)."""
    return i18n.transliteration()


def word_pattern(words: list[str]) -> str:
    """The regex source matching any of `words` as whole words."""
    return i18n.word_pattern(words)


def country_name(code: str) -> str:
    """The English name of the ISO country `code`, or the upper-cased code when unknown."""
    pack = i18n.countries().get(code.lower())
    return pack.name if pack is not None else code.upper()


# --- feeds, country, freshness ----------------------------------------------------------

def ad_links(html: str, page_url: str, limit: int = 300) -> list[str]:
    """The job-ad links on a listing page."""
    return ats_detect.ad_links(html, page_url, limit)


def from_url(url: str):
    """The ATS (platform and id) a URL belongs to, or `None`."""
    return ats_detect.from_url(url)


def country(config: dict, served: tuple[str, ...]) -> str:
    """The upper-case ISO code of the country to search: the profile's (`config["_country"]`,
    else resolved from `location` when the key is absent) if it is in `served`, else the first."""
    if "_country" in config:
        code = config["_country"]
    else:
        pack = i18n.country_for_location(config.get("location") or "")
        code = pack.code if pack is not None else None
    return (code if code in served else served[0]).upper()


def look_back_days(since: datetime | None, now: datetime) -> int | None:
    """`since` as whole days before `now`, rounded up (at least 1), or `None` without a cutoff."""
    return freshness.days_back(since, now)


def followed_name(config: dict, config_key: str, entry: str, fallback: str = "") -> str:
    """The followed employer's name for *entry* (as written under *config_key*), else *fallback*:
    the feed's own guess stays only for a feed `collect` did not name."""
    from door.core import companies  # call-time: companies imports the sites registry, which imports scrapers

    name = ((config.get("_names") or {}).get(config_key) or {}).get(companies.entry_key(entry), "")
    return name.strip() or fallback


# --- discovery sources (#280) ---------------------------------------------------------

class Employer(TypedDict, total=False):
    """One employer a discovery source saw: ``company``, ``titles``, ``links`` (apply link first, if
    read), ``job_ids``, ``detailed`` (its job page was read), ``first_seen`` (iso)."""

    company: str
    titles: list[str]
    links: list[str]
    job_ids: list[str]
    detailed: bool
    first_seen: str


class DiscoveryResult(TypedDict, total=False):
    """What a source's ``run`` returns: ``employers``, ``requests``, ``pages``, ``details``,
    ``stopped`` (reason | None), ``pushback`` (a refusal: the source rests a day), ``outcome``
    (``ok``, ``budget``, ``refused``, ``error``, ``cancelled``), ``mode``, ``mode_switched``,
    ``searched``, ``search_complete``, ``first_429``, ``budget``, ``pause``, ``seconds``."""

    employers: list[Employer]
    requests: int
    pages: int
    details: int
    stopped: str | None
    pushback: bool
    outcome: str
    mode: str
    mode_switched: bool
    searched: list[str]
    search_complete: bool
    first_429: dict | None
    budget: int
    pause: list[float]
    seconds: float


def name_key(name: str) -> str:
    """The employer-name key two spellings of one employer share (case, suffixes, spacing)."""
    from door.core import companies  # call-time, like followed_name

    return companies.name_key(name)


def is_job_board(url: str) -> bool:
    """Whether *url* is on a job board or aggregator rather than an employer's own site."""
    return ats_detect.is_job_board(url)


def awaiting_job_page(entry: dict) -> bool:
    """A queued employer `follow` could not resolve by name, whose job page is still to be read."""
    from door.core import candidates

    return candidates.awaiting_job_page(entry)


# --- feed platforms (#282) --------------------------------------------------------------

NOT_ACCOUNTS = ats_detect.NOT_ACCOUNTS


@dataclass(frozen=True)
class Probe:
    """A public endpoint to try for a company name: it answers with a job list under `key`
    (None: a bare list), with the query `params` when given; `evidence` says what a hit is."""

    url: str
    key: str | None
    evidence: str
    params: dict | None = None


def parts(url: str) -> tuple[str, list[str], dict[str, str]]:
    """`(host, path segments, lower-cased query)` of a link; the host without port, in lower case."""
    return ats_detect.parts(url)


def first(path: list[str]) -> str | None:
    """The first path segment in lower case when it can be an account name, else `None`."""
    return ats_detect.first(path)


def unfollowable(platform: str, where: str, reason: str, refusal: str = "must_not") -> Detection:
    """A platform door recognises but does not follow: no entry, the `reason` in the evidence and the
    `refusal` kind: ``"must_not"`` (its terms or robots.txt rule it out) or ``"cant_yet"`` (no way in yet)."""
    return Detection(platform, None, f"{where}: {reason}", refusal)


def follow_link(session, url: str) -> Detection | None:
    """The detection for a link found on another platform's pages (a front end's apply link): an entry when the
    system behind it lists jobs publicly, else an entry-less detection saying why not; None for an unknown link."""
    return ats_detect.follow_link(session, url)


def career_links(html: str, base_url: str, limit: int = 6) -> list[str]:
    """The links of a page that look like its employer's careers pages, best first."""
    return ats_detect.career_links(html, base_url, limit)


def slug_candidates(name: str) -> list[str]:
    """The slugs a company name most likely has on a job platform (joined, hyphenated)."""
    return ats_detect.slug_candidates(name)
