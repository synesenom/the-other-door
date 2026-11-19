#!/usr/bin/env python3
"""Scraper for The Hub (thehub.io).

The site moved from a JSON REST API to Nuxt.js server-side rendering — there
is no plain-JSON listing endpoint anymore. But the pages are server-rendered,
so a plain GET carries everything: the HTML holds ``window.__NUXT__=(function(
a,b,c,…){return {…}}(…))``, an IIFE that returns the page state. No browser is
needed: the script is cut out of the HTML (``_nuxt_script``) and run in an
embedded QuickJS engine (the ``quickjs`` package; only that expression, so
there is no DOM and no network inside the engine, with a time and memory
limit), and the object it returns is serialised to JSON (``_evaluate_nuxt``).

For each search keyword it loads ``thehub.io/jobs?search=...&countryCode=...
&page=<n>`` and reads ``state.jobs.jobs`` (``{total, limit, page, pages,
docs}``) for the listing page. The listing payload has no description, date or
external-URL field, so for each new (not yet seen) job it also fetches
``thehub.io/jobs/<id>`` and reads ``state.jobs.job`` for the full
description/date and the company's own job page (``link``, stored as
``apply_url``). Requests go through ``PoliteSession`` (``http_client.FEED_DELAY``
between them), so the scraper runs in ``_scrape_core``'s pool next to the
other boards.

Parsing (``_parse_listing_payload``, ``_parse_detail_payload``, ``_job_url``,
``_location_text``, ``_parse_date``) is kept pure and
separate from the network so it can be unit/fixture tested offline.

The Hub is a Nordic startup job board; only its Danish listings are searched.

Terms: https://thehub.io/terms — personal, non-commercial use; nothing on
scraping. robots.txt disallows only its job-list widget.
"""

import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

from door.scrapers import sdk
from door.scrapers.sdk import (
    FEED_DELAY, JobPosting, PoliteSession, PROBE_TIMEOUT_S, ProbeResult, log_keyword_results, make_job_id, record_answered, record_error,
    report, run_probe, strip_html,
)

_JOB_BASE_URL = "https://thehub.io/jobs"
_MAX_PAGES = 5

# Pause between requests: the employer feeds' (one host, one at a time).
_MIN_DELAY, _MAX_DELAY = FEED_DELAY

# The countries The Hub is registered for (`core.sites.SITES["thehub"].countries`; a test pins them).
_SERVED = ("dk",)

# Limits for the embedded engine: a page's state script runs in a few milliseconds.
_JS_TIME_LIMIT_S = 5
_JS_MEMORY_LIMIT = 128 * 1024 * 1024

# Hosts of this board: a link here is an ad on the board, never an employer's own site (`ats_detect.is_job_board`).
JOB_BOARD_HOSTS = ("thehub.",)


def _country_code(config: dict) -> str:
    """The Hub's ``countryCode`` for the profile's `location`: its country (from
    `src/door/i18n/country/`) when the site is registered for it, else the
    first country it is registered for."""
    return sdk.country(config, _SERVED)


def _parse_date(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _location_text(node: dict) -> str:
    loc = node.get("location") or {}
    address = (loc.get("address") or "").strip()
    locality = (loc.get("locality") or "").strip()
    country = (loc.get("country") or "").strip()
    if address:
        text = address
    elif locality and country:
        text = f"{locality}, {country}"
    elif locality or country:
        text = locality or country
    else:
        text = ""
    if node.get("isRemote"):
        text = f"{text} (Remote)" if text else "Remote"
    return text


def _job_url(job_id: str) -> str:
    """Canonical thehub.io detail-page URL for a job id.

    The Nuxt SSR payload no longer exposes an ``absoluteJobUrl`` field, and
    the old ``key``-slug URL 404s — the URL is always built from the id.
    """
    return f"{_JOB_BASE_URL}/{job_id}"


def _listing_url(keyword: str, country_code: str, page: int) -> str:
    """Build a The Hub jobs search URL for *keyword*/*country_code*/*page*."""
    return f"{_JOB_BASE_URL}?search={quote_plus(keyword)}&countryCode={country_code}&page={page}"


def _parse_listing_payload(jobs_obj: dict) -> tuple[list[dict], bool]:
    """Parse ``window.__NUXT__.state.jobs.jobs`` into (docs, has_next_page)."""
    docs = jobs_obj.get("docs") or []
    page = jobs_obj.get("page") or 0
    pages = jobs_obj.get("pages") or 0
    return docs, page < pages


def _parse_detail_payload(job_obj: dict | None) -> dict | None:
    """Parse ``window.__NUXT__.state.jobs.job`` into JobPosting-ready fields.

    Returns ``None`` when the job object is missing/empty (e.g. the detail
    page failed to load or the job was removed) so the caller can skip it.
    """
    if not job_obj or not job_obj.get("id"):
        return None

    title = (job_obj.get("title") or "").strip()
    company = ((job_obj.get("company") or {}).get("name") or "").strip()
    description_raw = job_obj.get("description") or ""
    description = strip_html(description_raw) if "<" in description_raw else description_raw

    return {
        "id": job_obj.get("id"),
        "key": job_obj.get("key"),
        "title": title,
        "company": company,
        "location": _location_text(job_obj),
        "description": description,
        "posted_at": _parse_date(job_obj.get("publishedAt")),
        # The company's own job page; empty for ads applied to by email.
        "apply_url": (job_obj.get("link") or "").strip() or None,
    }


_NUXT_START = "window.__NUXT__="


def _nuxt_script(html: str) -> str | None:
    """The expression assigned to ``window.__NUXT__`` in the page, or None. Pure."""
    start = html.find(_NUXT_START)
    if start < 0:
        return None
    start += len(_NUXT_START)
    end = html.find("</script>", start)
    if end < 0:
        return None
    return html[start:end].strip().rstrip(";").strip()


def _evaluate_nuxt(expression: str) -> dict:
    """Run the ``window.__NUXT__`` expression in an embedded QuickJS engine and return the object.

    Only the expression is evaluated, in a fresh context with no DOM and no network, under a
    time and memory limit. Raises ValueError when the script throws, runs too long or does not
    return an object.
    """
    import quickjs

    context = quickjs.Context()
    context.set_time_limit(_JS_TIME_LIMIT_S)
    context.set_memory_limit(_JS_MEMORY_LIMIT)
    try:
        text = context.eval(f"JSON.stringify({expression})")
    except Exception as exc:  # noqa: BLE001 - quickjs.JSException, InternalError, limits
        raise ValueError(f"window.__NUXT__ failed to evaluate: {exc}") from exc
    try:
        data = json.loads(text) if isinstance(text, str) else None
    except ValueError as exc:
        raise ValueError(f"window.__NUXT__ is not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("window.__NUXT__ did not evaluate to an object")
    return data


def _nuxt_state(html: str, path: tuple[str, ...]) -> dict | None:
    """Evaluate the page's ``window.__NUXT__`` and walk *path* (e.g. ``("state", "jobs", "jobs")``).

    None when *path* does not lead to an object; ValueError when the page has no
    ``window.__NUXT__`` or it cannot be evaluated.
    """
    script = _nuxt_script(html)
    if script is None:
        raise ValueError("no window.__NUXT__ in the page")
    node: Any = _evaluate_nuxt(script)
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node if isinstance(node, dict) else None


def _get_state(session: PoliteSession, url: str, path: tuple[str, ...]) -> dict | None:
    return _nuxt_state(session.get(url).text, path)


def scrape(config: dict, known_ids: frozenset[str] = frozenset(), **kwargs) -> list[dict]:
    """Return a list of JobPosting-compatible dicts from The Hub."""
    role_targets: list[str] = config.get("role_targets", [])
    # search_keywords broadens retrieval; fall back to role_targets when absent or empty.
    search_keywords: list[str] = config.get("search_keywords") or role_targets
    country_code = _country_code(config)
    scraped_at = datetime.now(timezone.utc)

    # The Hub needs no authentication; PoliteSession checks robots.txt (when obeyed) and paces.
    session = PoliteSession(min_delay=_MIN_DELAY, max_delay=_MAX_DELAY)
    seen_ids: set[str] = set()
    postings: list[dict] = []

    for keyword in search_keywords:
        keyword_start = len(postings)
        for page_num in range(1, _MAX_PAGES + 1):
            url = _listing_url(keyword, country_code, page_num)
            try:
                jobs_obj = _get_state(session, url, ("state", "jobs", "jobs"))
                if jobs_obj is None:
                    raise ValueError("missing/malformed window.__NUXT__.state.jobs.jobs")
            except Exception as exc:
                report(f"listing error (keyword={keyword!r}, page={page_num}): {exc}")
                record_error("thehub", f"listing error (keyword={keyword!r}, page={page_num}): {exc}")
                break

            docs, has_next = _parse_listing_payload(jobs_obj)
            if not docs and page_num == 1:
                record_answered("thehub")

            for doc in docs:
                platform_id = str(doc.get("id") or "")
                if not platform_id or platform_id in seen_ids:
                    continue
                seen_ids.add(platform_id)

                detail_url = _job_url(platform_id)
                try:
                    parsed = _parse_detail_payload(_get_state(session, detail_url, ("state", "jobs", "job")))
                except Exception as exc:
                    report(f"detail error ({detail_url}): {exc}")
                    record_error("thehub", f"detail error ({detail_url}): {exc}")
                    continue

                if parsed is None:
                    report(f"detail error ({detail_url}): empty/missing job payload")
                    record_error("thehub", f"detail error ({detail_url}): empty/missing job payload")
                    continue

                job_id = make_job_id("thehub", platform_id)
                posting = JobPosting(
                    id=job_id,
                    title=parsed["title"],
                    company=parsed["company"],
                    location=parsed["location"],
                    url=detail_url,
                    description=parsed["description"],
                    source="thehub",
                    scraped_at=scraped_at,
                    platform_id=platform_id,
                    posted_at=parsed["posted_at"],
                    apply_type="external" if parsed["apply_url"] else None,
                    apply_url=parsed["apply_url"],
                )
                postings.append(posting.model_dump(mode="json"))

            if not has_next:
                break
        log_keyword_results("thehub", keyword, postings[keyword_start:])

    return postings


def _listing_to_posting(doc: dict, scraped_at: datetime) -> dict:
    """Map one listing doc (no description/date in the listing payload) to a JobPosting dict."""
    platform_id = str(doc.get("id") or "")
    title = (doc.get("title") or "").strip()
    company = ((doc.get("company") or {}).get("name") or "").strip()
    posting = JobPosting(
        id=make_job_id("thehub", platform_id),
        title=title,
        company=company,
        location=_location_text(doc),
        url=_job_url(platform_id),
        description="",
        source="thehub",
        scraped_at=scraped_at,
        platform_id=platform_id,
    )
    return posting.model_dump(mode="json")


def probe(config: dict) -> ProbeResult | None:
    """Side-effect-free health check: listing page 1 of the first keyword, no detail fetches.

    ``raw`` is the page's HTML. Never records errors; ``None`` when no keyword is configured.
    """
    keywords = config.get("search_keywords") or config.get("role_targets") or []
    if not keywords:
        return None
    url = _listing_url(keywords[0], _country_code(config), 1)
    session = PoliteSession(min_delay=_MIN_DELAY, max_delay=_MAX_DELAY, timeout=PROBE_TIMEOUT_S, max_retries=0)

    def parse(html: str):
        jobs_obj = _nuxt_state(html, ("state", "jobs", "jobs"))
        if jobs_obj is None:
            return [], False, "missing/malformed window.__NUXT__.state.jobs.jobs"
        docs, _ = _parse_listing_payload(jobs_obj)
        scraped_at = datetime.now(timezone.utc)
        return [_listing_to_posting(d, scraped_at) for d in docs if d.get("id")], True, ""

    return run_probe(lambda: session.get(url).text, parse, "html")
