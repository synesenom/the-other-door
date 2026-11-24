"""Step 5, `match`: filter, dedup, condense and score what the other steps wrote, then pick the matches.

First the passes over today's postings and any earlier recent day's unscored ones (`door.commands.scrape._scrape_passes`: the exclusion
pre-filter, cross-site dedup, the language pass, condense and the offline prescreen), once for
everything `search` and `collect` wrote; then `door.commands.match._match_core` scores every
unscored posting of the recent days with Haiku (so an interrupted run is resumed); then the matches
at or above ``min_score`` are selected, as `list` does, and the ones this run scored are its new
matches (a match an earlier run found is not new again); the employers of every match are
stamped ``last_relevant`` in `profile/companies.json` (see `door.pipeline.collect`'s retirement).
"""

from __future__ import annotations

import time
from datetime import date, datetime, timezone
from pathlib import Path

from door import pipeline
from door.commands import _common as common
from door.commands import match as match_cmd
from door.commands import scrape as scrape_cmd
from door.core import cv_read, lock, profile_loader
from door.core.employers import companies as store
from door.core.jobs import tracker as tracker_mod
from door.core import workspace
from door.core.jobs.selection import select_matches


def _summary(block: dict) -> str:
    text = f"{block['scored']} scored, {block['above_threshold']} above {block['min_score']:g}"
    text += f", {len(block['failed'])} failed" if block["failed"] else ""
    return text + (f", {block['waiting']} waiting" if block.get("waiting") else "")


def _stamp_relevant(matches: list[dict], profile_dir: Path) -> None:
    """An employer with a posting at or above ``min_score`` is relevant: stamp its ``last_relevant``
    (so `collect` does not retire it). Employers not on the list are ignored."""
    pairs = {(str(m.get("company") or ""), str(m.get("id") or "")) for m in matches}
    if not pairs:
        return
    items = common._company_items(profile_dir)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if any([store.mark_relevant_posting(items, name, job_id, now) for name, job_id in pairs]):
        store.save(profile_dir, items)


def _merge(into: dict | None, other: dict | None):
    """Add one day's block of a pass to the running total (counts add, dicts merge by key)."""
    if into is None or other is None:
        return into if other is None else other
    out = dict(into)
    for key, value in other.items():
        have = out.get(key)
        if isinstance(value, dict) and isinstance(have, dict):
            out[key] = _merge(have, value)
        elif have is None:
            out[key] = value
        elif isinstance(value, (int, float)) and isinstance(have, (int, float)):
            out[key] = have + value
        else:
            out[key] = value
    return out


def _unscored_ids(jobs_dir: Path, config: dict) -> set[str]:
    """The ids of the recent postings not scored yet: the ones this run scores (a posting's file is
    ``<job_id>.json``)."""
    days = match_cmd._recent_candidates_dirs(jobs_dir, config.get("max_age_days", common._DEFAULT_MAX_AGE_DAYS))
    return {path.stem for day in days for path in match_cmd._find_unscored(day)}


def _run_passes(today: Path, jobs_dir: Path, config: dict, profile_dir: Path) -> dict:
    """The passes over today's directory and over every earlier recent day that still holds an
    unscored posting, oldest first (a run that crosses midnight leaves its postings in yesterday's
    directory; the passes leave a decided posting alone, and a day with none unscored is skipped)."""
    days = [d for d in match_cmd._recent_candidates_dirs(
        jobs_dir, config.get("max_age_days", common._DEFAULT_MAX_AGE_DAYS))
        if d != today and match_cmd._find_unscored(d)]
    total: dict = {}
    for day in [*days, today]:
        for key, block in scrape_cmd._scrape_passes(day, config, profile_dir).items():
            total[key] = _merge(total.get(key), block)
    return total


CV_UNREAD = "Claude could not read your CV, so the new jobs were not scored; they will be on the next run."


def _skipped_block(jobs_dir: Path, config: dict, threshold: float, started: float) -> dict:
    """The block of a step that scored nothing because the CV could not be read: the postings stay unscored, so the next
    run (which reads the CV again) scores them."""
    pipeline.skipped("match", CV_UNREAD)
    elapsed = time.monotonic() - started
    return {
        "step": "match", "skipped": CV_UNREAD, "summary": CV_UNREAD, "passes": {}, "min_score": threshold,
        "new_above_threshold": [], "top": [], "scored": 0, "failed": [], "above_threshold": 0,
        "unscored_before": len(_unscored_ids(jobs_dir, config)), "scoring_s": 0.0, "elapsed_s": elapsed,
    }


@lock.locked("match")
def _match_step_core(
    *, jobs_dir: Path | None = None, profile_dir: Path | None = None, progress=None,
) -> dict:
    """Run the passes, score the unscored postings and select the matches. Never prints.

    Args:

    Returns:
        ``{"step": "match", "passes": {"prefilter", "dedup", "language", "condense", "prescreen"},
        "min_score", "new_above_threshold": [job_id, ...] (the matches this run scored), "top": [{"id",
        "score", "title", "title_en", "company", "location"}, ...] (the top 10 of them), "elapsed_s" (the whole step), "scoring_s", "summary"}`` plus
        `_match_core`'s keys (``candidates_dir``, ``unscored_before``, ``scored``, ``failed``,
        ``above_threshold``, ``model``).

    Raises:
        ConfigError / FileNotFoundError: the profile config is missing or invalid.
    """
    jobs_dir = workspace.JOBS_DIR if jobs_dir is None else jobs_dir
    profile_dir = workspace.PROFILE_DIR if profile_dir is None else profile_dir
    config = profile_loader.load_profile_config(profile_dir)
    threshold = config.get("min_score", common._DEFAULT_MIN_SCORE)
    started = time.monotonic()

    try:
        common._cv_reading(config, profile_dir)  # once, here: every day folder's passes after it find the reading cached
    except cv_read.CvReadError:
        return _skipped_block(jobs_dir, config, threshold, started)

    today = workspace.day_dir(jobs_dir, date.today().isoformat())
    today.mkdir(parents=True, exist_ok=True)  # a run that wrote nothing still has a day to score
    with pipeline.running("match") as step:
        unscored = _unscored_ids(jobs_dir, config)
        passes = _run_passes(today, jobs_dir, config, profile_dir)
        # `None`: every recent jobs/postings/<date>/ directory, so postings an earlier run left unscored are scored now.
        scored = match_cmd._match_core(jobs_dir=jobs_dir, profile_dir=profile_dir)

        app_tracker = tracker_mod.ApplicationTracker(jobs_dir / "applications.json")
        matches = common._drop_stale(
            select_matches(jobs_dir, app_tracker, threshold),
            config.get("max_age_days", common._DEFAULT_MAX_AGE_DAYS),
        )
        _stamp_relevant(matches, profile_dir)
        new = [m for m in matches if m.get("id") in unscored]
        block = {
            **scored, "step": "match", "passes": passes, "min_score": threshold,
            "new_above_threshold": [m.get("id") for m in new],
            "top": [{"id": m.get("id"), "score": m.get("score"), "title": m.get("title"),
                     "title_en": m.get("title_en"), "company": m.get("company"), "location": m.get("location")}
                    for m in new[:10]],
        }
        block["summary"] = step.summary = _summary(block)
    block["scoring_s"], block["elapsed_s"] = block["elapsed_s"], time.monotonic() - started
    return block
