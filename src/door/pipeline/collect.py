"""Step 4, `collect`: every followed employer's own job feed.

`profile/companies.json` says which employers are followed and on which platform; nothing needs
listing anywhere else. The shared engine (`door.commands.scrape._scrape_core`, mode
``collect``) runs one scraper per platform that has a followed employer, each fetching its
employers' feeds (different hosts side by side, at most `PER_PROVIDER` of one provider's, each
host paced). ``--company NAME ...`` collects just those employers.

Before reading, the employers that yielded nothing relevant for ``retire_after_days`` (default 90)
are made ``dormant`` and skipped (`door.core.companies.retire_idle`; an employer added by hand is
never retired; a dormant one seen again with an on-topic ad is followed again by `follow`).
After reading, the employers whose new postings have an on-topic title are stamped ``last_relevant``
(`match` stamps those with a posting at or above ``min_score``). The retirement runs here, at the start of
the step, because it is the step that reads the employers; the summary says how many were retired.

Only a posting whose title is on topic for the keywords (`door.matching.title_fit.on_topic`: any
content word of ``search_keywords``/``role_targets``, synonyms included) is written: a feed lists
every job the employer has, most of them unrelated. The others are remembered in the history, so
they are not checked again, and counted (``off_topic``).

Freshness differs from the boards': a posting is new when The other door has not seen it before (the
history in `jobs/history.json`), whatever its ``posted_at``. A cutoff by date dropped long-open
jobs that LinkedIn and others re-advertise as recent.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from door import pipeline
from door.commands import _common as common
from door.commands import scrape as scrape_cmd
from door.core import companies as store
from door.core import utils, workspace
from door.core.sites import FEED_SITES
from door.matching import title_fit


def _failed(sites: list[dict]) -> int:
    """Employers (or whole platforms) that did not load: each recorded error, plus a platform that errored."""
    return sum(len(e.get("errors") or []) + (1 if e["outcome"] == "error" else 0) for e in sites)


def _summary(block: dict) -> str:
    if not block["employers"]:
        text = "no followed employers"
    else:
        text = f"{block['employers']} employers, {block['postings']:,} postings"
        text += f", {block['failed']} failed" if block["failed"] else ""
    text += f", {block['non_local']:,} non-local skipped" if block["non_local"] else ""
    text += f", {block['off_topic']:,} off-topic skipped" if block["off_topic"] else ""
    return text + (f", {len(block['retired'])} retired" if block["retired"] else "")


def _retire(profile_dir: Path, config: dict) -> list[str]:
    """Make the idle employers dormant (saved); returns their names."""
    items = common._company_items(profile_dir)
    retired = store.retire_idle(items, config.get("retire_after_days", common._DEFAULT_RETIRE_AFTER_DAYS))
    if retired:
        store.save(profile_dir, items)
    return [c.name for c in retired]


def _stamp_relevant(paths, profile_dir: Path, config: dict) -> None:
    """Stamp ``last_relevant`` on the employers of the written postings (*paths*) with an on-topic title,
    and write each posting's ``employer`` (the list entry it belongs to) into its file."""
    terms = title_fit.topic_terms(config)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    items = common._company_items(profile_dir)
    touched = False
    for path in paths:
        try:
            posting = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(posting, dict):
            continue
        company, job_id = str(posting.get("company") or ""), str(posting.get("id") or "")
        employer = store.employer_of(items, company, job_id)
        if employer and posting.get("employer") != employer:
            posting["employer"] = employer
            utils.write_json_atomic(Path(path), posting)
        if title_fit.on_topic(str(posting.get("title") or ""), terms):
            touched = store.mark_relevant_posting(items, company, job_id, now) or touched
    if touched:
        store.save(profile_dir, items)


def _stamp_problems(sites: list[dict], feeds: dict[str, list[str]], profile_dir: Path) -> None:
    """Stamp on each followed employer read this run why its feed could not be read (``collect_problem``:
    blocked or failed, from the site's ``entry_errors``, or the whole platform's error), and clear the stamp
    of those that loaded. A platform that was not run (resting, not configured) leaves its employers as they were."""
    by_site = {e["site"]: e for e in sites}
    items = common._company_items(profile_dir)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    touched = False
    for config_key, ids in feeds.items():
        site = next((s for s, key in FEED_SITES.items() if key == config_key), None)
        entry = by_site.get(site)
        if entry is None or entry["outcome"] not in ("ok", "empty", "failed", "error"):
            continue
        errors = {store.entry_key(k): v for k, v in (entry.get("entry_errors") or {}).items()}
        unattributed = len(entry.get("errors") or []) > len(errors)
        wanted = {store.entry_key(i) for i in ids}
        for company in items:
            if company.status != "followed" or company.feed is None or company.feed.platform != site:
                continue
            key = store.entry_key(company.feed.id)
            if key not in wanted:
                continue
            if entry["outcome"] == "error":
                problem = ("failed", str(entry.get("error") or "the platform's scraper failed"))
            elif key in errors:
                problem = (errors[key]["outcome"], errors[key]["reason"])
            elif entry["outcome"] == "failed" and unattributed:
                problem = ("failed", "; ".join(entry.get("errors") or [])[:300])
            else:
                problem = (None, "")
            before = company.collect_problem
            store.set_collect_problem(company, problem[0], problem[1], now)
            if before is not None and company.collect_problem is not None and (
                    before.outcome, before.reason) == (company.collect_problem.outcome, company.collect_problem.reason):
                company.collect_problem = before  # unchanged: keep the first time it was seen
            touched = touched or before != company.collect_problem
    if touched:
        store.save(profile_dir, items)


@common._locked("collect")
def _collect_core(
    *, companies: list[str] | None = None, late: bool = False,
    jobs_dir: Path | None = None, profile_dir: Path | None = None, progress=None,
) -> dict:
    """Read the feed of every followed employer (or just *companies*); write the new postings. Never prints.

    Args:
        companies: Names of followed employers to collect instead of all of them.
        late: A second pass for the employers followed late (`find`'s "late collect"): its progress
            events are ``late`` events, folded into the step's line.

    Returns:
        ``{"step": "collect", "employers", "run_date", "sites": [<per-platform outcome>],
        "postings", "failed", "non_local", "off_topic", "retired", "liveness", "elapsed_s", "summary"}`` — ``employers``
        is how many followed employers were read, ``failed`` the employers and platforms that errored,
        ``non_local`` the postings scrapers left unread because they name another country's place, ``off_topic``
        the new postings not written because their title is off topic, ``retired`` the names made dormant at the start.

    Raises:
        ConfigError / FileNotFoundError: the profile config or companies.json is invalid or missing.
        ValueError: a name in ``companies`` is not a followed employer.
    """
    jobs_dir = workspace.JOBS_DIR if jobs_dir is None else jobs_dir
    profile_dir = workspace.PROFILE_DIR if profile_dir is None else profile_dir
    config = common._load_config(profile_dir)
    retired = _retire(profile_dir, config) if not companies else []
    feeds = scrape_cmd._feed_config_for(profile_dir, companies)
    employers = sum(len(ids) for ids in feeds.values())

    started = time.monotonic()
    with pipeline.running("collect", total=employers or None, late=late) as step:
        result = scrape_cmd._scrape_core(None, jobs_dir=jobs_dir, profile_dir=profile_dir,
                                         mode="collect", companies=companies, passes=False)
        _stamp_relevant(result["written"], profile_dir, config)
        _stamp_problems(result["sites"], feeds, profile_dir)
        sites = result["sites"]
        block = {
            "step": "collect", "employers": employers, "run_date": result["run_date"],
            "sites": sites, "postings": sum(e.get("count", 0) for e in sites if e["outcome"] == "ok"),
            "failed": _failed(sites), "retired": retired,
            "non_local": sum(e.get("non_local", 0) for e in sites),
            "off_topic": sum(e.get("off_topic", 0) for e in sites), "liveness": result["liveness"], "candidates_dir": result["candidates_dir"],
        }
        block["summary"] = step.summary = _summary(block)
    block["elapsed_s"] = time.monotonic() - started
    return block
