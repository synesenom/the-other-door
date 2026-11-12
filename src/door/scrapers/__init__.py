"""Shared helpers for all scrapers."""

import html as _html
import re
import threading
from datetime import datetime, timezone
from typing import Any, NotRequired, TypedDict

from door.core import progress as _progress

PROBE_TIMEOUT_S = 10  # per-request timeout for every scraper probe


class ProbeResult(TypedDict):
    """What a scraper's side-effect-free ``probe(config)`` returns (issue #178).

    ``raw`` is the unparsed page-1 response (saved by ``doctor`` when the
    probe flags drift), ``ext`` its file extension, ``postings`` the page-1
    results mapped to JobPosting dicts without any detail fetch, and
    ``structure_ok`` whether the expected results structure was found. A
    probe fetches page 1 only, never calls ``record_error``, never writes,
    and returns ``None`` when the site cannot be probed (nothing configured).
    ``wall`` (login/bot challenge) and ``unreachable`` (network failure) make
    the result a warning, never drift. ``robots`` is robots.txt's verdict on
    the URL probed (issue #226): ``"allowed"`` once a page came back,
    ``"disallowed"`` when the request was never sent.
    """

    raw: str
    ext: str  # "html" | "json" | "xml"
    postings: list[dict]
    structure_ok: bool
    reason: NotRequired[str]
    wall: NotRequired[bool]
    unreachable: NotRequired[bool]
    robots: NotRequired[str]  # "allowed" | "disallowed"

def parse_iso_date(s: Any) -> datetime | None:
    """Parse an ISO 8601 date (``Z`` suffix allowed); None when missing, not a string, or unparseable."""
    if not isinstance(s, str) or not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


# Per-source error accounting (issue #132). Scrapers report every error line
# as they hit it with `report()` (so live output stays useful); this
# module-level dict additionally captures those same messages so `_scrape_core` can tell
# a genuinely quiet day (count == 0, no errors) from a broken scraper
# (count == 0, errors present) after `scrape(config)` returns.
_errors: dict[str, list[str]] = {}
_errors_lock = threading.Lock()  # sites scrape concurrently (issue #254)


def record_error(source: str, message: str) -> None:
    """Record *message* for *source*, accumulating until `drain_errors()`.

    Called alongside (not instead of) each scraper's `report(...)` of the
    same error, so the message shows live and survives in the scrape result.
    Safe to call from any thread.
    """
    with _errors_lock:
        _errors.setdefault(source, []).append(message)


def drain_errors(source: str | None = None) -> dict[str, list[str]]:
    """Return and clear the accumulated errors: *source*'s only, or all of them.

    `_scrape_core` drains each site's own errors when that site finishes
    (``drain_errors(site)``), so sites scraping side by side never see one
    another's; a site's `outcome` is computed from its own errors alone.
    """
    with _errors_lock:
        if source is None:
            drained = dict(_errors)
            _errors.clear()
        else:
            drained = {source: _errors.pop(source)} if source in _errors else {}
    return drained


_entry_errors: dict[str, dict[str, dict[str, str]]] = {}


def record_entry_error(source: str, entry: str, message: str, *, blocked: bool = False) -> None:
    """`record_error(source, message)`, and remember which feed *entry* it was (issue #437): `collect`
    shows an employer whose feed could not be read, and why. *blocked* is a refusal (bot protection, a
    login wall) rather than a failure. Safe to call from any thread."""
    record_error(source, message)
    with _errors_lock:
        _entry_errors.setdefault(source, {})[entry] = {"outcome": "blocked" if blocked else "failed", "reason": message}


def drain_entry_errors(source: str) -> dict[str, dict[str, str]]:
    """Return and clear *source*'s entry errors: ``{entry: {"outcome": "failed" | "blocked", "reason"}}``."""
    with _errors_lock:
        return _entry_errors.pop(source, {})


_pushback: set[str] = set()


def record_pushback(source: str) -> None:
    """Mark that *source* refused door this run (429, a block, a login wall).

    Called with the `record_error` of the same stop. `_scrape_core` drains it when
    the site finishes and, for a site with a `cooldown_hours`, rests the site that
    long before asking it again. Safe to call from any thread.
    """
    with _errors_lock:
        _pushback.add(source)


def drain_pushback(source: str) -> bool:
    """Whether *source* pushed back since the last drain; clears it."""
    with _errors_lock:
        if source in _pushback:
            _pushback.discard(source)
            return True
        return False


_answered: set[str] = set()


def record_answered(source: str) -> None:
    """Mark that *source* read a recognised results page with no hits this run.

    A scraper that can tell "the search found nothing" from "the page is not what I know" calls it
    for the first. `_scrape_core` drains it when the site finishes: no postings, no errors and this
    signal is a quiet day (`ok`), not an `empty` site that may have changed. Safe to call from any thread.
    """
    with _errors_lock:
        _answered.add(source)


def drain_answered(source: str) -> bool:
    """Whether *source* answered with a recognised zero-hit page since the last drain; clears it."""
    with _errors_lock:
        if source in _answered:
            _answered.discard(source)
            return True
        return False


_non_local: dict[str, int] = {}


def record_non_local(source: str, count: int) -> None:
    """Add *count* to the postings *source* left unread this run because they are not local to the
    profile (dropped before any detail fetch). `_scrape_core` drains it when the site finishes. Safe
    to call from any thread."""
    with _errors_lock:
        _non_local[source] = _non_local.get(source, 0) + max(int(count), 0)


def drain_non_local(source: str) -> int:
    """How many postings *source* skipped as non-local since the last drain; clears it."""
    with _errors_lock:
        return _non_local.pop(source, 0)


def report(
    message: str,
    done: int | None = None,
    total: int | None = None,
    *,
    site: str | None = None,
    stage: str | None = None,
    outcome: str | None = None,
) -> None:
    """Report progress (issue #202); scrapers never print.

    Thin door to `door.core.progress.report`. Inside `_scrape_core` the
    current site is already in scope, so ``site`` is only needed elsewhere.
    A no-op when nothing listens. Pair it with `record_error` for anything the
    user must act on, since events are ephemeral.
    """
    _progress.report(message, done, total, site=site, stage=stage, outcome=outcome)


_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_BLOCK_BREAK = re.compile(r"(?i)<br\s*/?>|<li[^>]*>|</(p|li|h\d|div|ul|ol|tr)>")
_TAG = re.compile(r"<[^>]+>")
_INVISIBLE = re.compile("[​-‏⁠﻿]")
_SPACES = re.compile(r"[ \t\r\f\v]+")


def strip_html(raw: str | None, *, encoded: bool = False) -> str:
    """Plain text from an ad's HTML: one line per block, entities, comments and invisible
    characters gone, blank lines dropped. ``encoded`` for markup that is itself entity-encoded
    (``&lt;p&gt;``), as Greenhouse, Teamtailor and SuccessFactors send it. Pure."""
    text = _html.unescape(raw or "") if encoded else raw or ""
    text = _BLOCK_BREAK.sub("\n", _COMMENT.sub("", text))
    text = _INVISIBLE.sub("", _html.unescape(_TAG.sub(" ", text))).replace("\xa0", " ")
    lines = (_SPACES.sub(" ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def log_keyword_results(source: str, keyword: str, postings: list) -> None:
    """Report the number of results found for *keyword*.

    Always reports so the user can see per-keyword counts and distinguish
    genuine zero results from scraper errors (which are reported separately
    when the HTTP request or parse step raises).
    """
    report(f"'{keyword}': {len(postings)} results", site=source, stage="keyword")


def tracked(entries, label=str):
    """Iterate *entries* (a feed's employers, one request group each), reporting when each one
    starts and ends (stage ``entry_start`` / ``entry_end``, message ``label(entry)``), so `find`'s
    display counts employers done and shows the ones in flight. Yields the entries unchanged."""
    current = None
    try:
        for entry in entries:
            current = label(entry)
            report(current, stage="entry_start")
            yield entry
            report(current, stage="entry_end")
            current = None
    finally:
        if current is not None:  # a break or an error left the entry open
            report(current, stage="entry_end")


def scrape_feeds(site: str, entries, fetch, *, key=lambda p: p["platform_id"], label=str,
                 group=None, max_workers: int = 1, headers: dict | None = None) -> list[dict]:
    """The loop of a per-company feed: ``fetch(session, entry, scraped_at) -> [JobPosting dict]``
    for each of *entries*, on one feed-paced session, keeping the first posting of each ``key``
    in entry order (one with an empty key is skipped).

    With *group* (an entry's host) and *max_workers* above 1, entries on different hosts are
    fetched side by side (`_parallel.map_by_group`); the output never depends on timing.
    An entry that raises is reported and recorded as an error of *site*, and the rest go on;
    each entry's count is reported like a keyword's.
    """
    from door.scrapers._parallel import map_by_group
    from door.scrapers.http_client import FEED_DELAY, PoliteSession

    session = PoliteSession(min_delay=FEED_DELAY[0], max_delay=FEED_DELAY[1], timeout=30, headers=headers)
    scraped_at = datetime.now(timezone.utc)

    def safe_fetch(entry) -> list[dict] | None:
        try:
            return fetch(session, entry, scraped_at)
        except Exception as exc:  # noqa: BLE001 - one bad entry never stops the feed
            message = f"error fetching {label(entry)!r}: {exc}"
            report(message)
            record_entry_error(site, label(entry), message)
            return None

    fetched = map_by_group(entries, group or label, safe_fetch, max_workers if group else 1)
    seen: set = set()
    postings: list[dict] = []
    for entry, found in zip(entries, fetched):
        if found is None:
            continue
        fresh = []
        for posting in found:
            if key(posting) and key(posting) not in seen:
                seen.add(key(posting))
                fresh.append(posting)
        log_keyword_results(site, label(entry), fresh)
        postings.extend(fresh)
    return postings


def probe_failure(exc: Exception, ext: str) -> ProbeResult:
    """A probe result for a failed fetch: robots.txt disallowing it is
    ``robots: "disallowed"``, 401/403/429 a wall, anything else unreachable.

    None is ever drift: the site did not answer with a page whose structure
    could be judged.
    """
    from door.scrapers.http_client import RobotsBlocked

    status = getattr(getattr(exc, "response", None), "status_code", None)
    reason = f"{type(exc).__name__}: {exc}"
    result: ProbeResult = {"raw": "", "ext": ext, "postings": [], "structure_ok": False, "reason": reason}
    if isinstance(exc, RobotsBlocked):
        result["robots"] = "disallowed"
    elif status in (401, 403, 429):
        result["wall"] = True
    else:
        result["unreachable"] = True
    return result


def run_probe(fetch, parse, ext: str) -> ProbeResult:
    """Shared probe skeleton: ``fetch() -> raw text`` then ``parse(raw) -> (postings, structure_ok, reason)``.

    A fetch exception becomes a wall/unreachable result; a parse exception
    becomes ``structure_ok=False`` (the page arrived but cannot be read).
    """
    try:
        raw = fetch()
    except Exception as exc:  # noqa: BLE001 - any failure is reported, not raised
        return probe_failure(exc, ext)
    try:
        postings, ok, reason = parse(raw)
    except Exception as exc:  # noqa: BLE001
        postings, ok, reason = [], False, f"parse failed: {type(exc).__name__}: {exc}"
    result: ProbeResult = {"raw": raw, "ext": ext, "postings": postings, "structure_ok": ok, "robots": "allowed"}
    if reason:
        result["reason"] = reason
    return result
