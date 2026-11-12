"""`find`'s second stage: score unscored postings with `claude -p` (Haiku, in parallel)."""

import json
import time
from pathlib import Path

from door.commands import _common as common
from door.core import progress as progress_mod
from door.core import selection
from door.core import workspace
from door.core import utils
from door.matching import integrity


def _newest_candidates_dir(jobs_dir: Path) -> Path | None:
    """Return the most recent `jobs_dir/postings/<YYYY-MM-DD>/` directory, or None.

    Only date-named directories under `postings/` are considered (`selection.date_dirs`).
    """
    dirs = selection.date_dirs(jobs_dir)
    return dirs[-1] if dirs else None


def _recent_candidates_dirs(jobs_dir: Path, max_age_days: int | None, today=None) -> list[Path]:
    """Every `jobs_dir/postings/<YYYY-MM-DD>/` directory dated within `max_age_days` of
    today (all of them when `None`), oldest first.

    Matching scores the unscored postings in all of them, so a run that was interrupted or hit the usage limit yesterday leaves no
    orphans behind — scored postings cost nothing to walk past.
    """
    from datetime import date, timedelta

    today = today or date.today()
    cutoff = today - timedelta(days=max_age_days) if max_age_days is not None else None
    dirs = []
    for d in selection.date_dirs(jobs_dir):
        if cutoff is not None:
            try:
                if date.fromisoformat(d.name) < cutoff:
                    continue
            except ValueError:
                continue
        dirs.append(d)
    return dirs


MAX_FAILURES = 20  # failures kept with their reason in the run record


def _find_unscored(candidates_dir: Path) -> list[Path]:
    """Return posting JSON paths under `candidates_dir/<site>/` that still need scoring.

    A posting with an existing `score` (of any value, including a hard
    zero from `prefilter` or `prescreen`) is skipped — it has already been
    through matching and re-sending it would waste an LLM call.
    """
    candidates_dir = Path(candidates_dir)
    if not candidates_dir.exists():
        return []

    found: list[Path] = []
    for site_dir in sorted(candidates_dir.iterdir()):
        if not site_dir.is_dir():
            continue
        for json_path in sorted(site_dir.glob("*.json")):
            try:
                data = json.loads(json_path.read_text())
            except (json.JSONDecodeError, OSError):
                continue

            if data.get("score") is None:
                found.append(json_path)

    return found


@common._with_progress
def _match_core(
    *,
    jobs_dir: Path | None = None,
    profile_dir: Path | None = None,
    paths: list[Path] | None = None,
    progress=None,
) -> dict:
    """Score unscored postings against the candidate profile via `claude -p`; return structured data.

    `find`'s second stage: scans every `jobs_dir/postings/<YYYY-MM-DD>/` directory
    within config's `max_age_days` (excluding `jobs_dir/output/`), so
    postings left unscored by an earlier, interrupted run are picked up too;
    builds the scoring system prompt from `.claude/agents/
    matcher.md` + the profile, runs `door.matching.scorer.score_postings`
    over every unscored posting, and writes each result back to its
    posting JSON atomically — as soon as it's available, not only once the
    whole run finishes, so an interrupted or rate-limited run keeps its
    progress. Scoring is a text comparison, so it always runs on
    `scorer.DEFAULT_MODEL` (Haiku) with the scorer's default parallelism.
    With the config key ``needs_work_permit`` an ad the scorer reads as
    ``no_sponsorship`` / ``permit_required`` is written with score 0.
    Never prints.

    Deliberately does not use `door.core.profile_loader.load_profile`
    (which requires the LaTeX template files referenced by `profile/
    config.json` to exist on disk): matching only needs the raw config
    dict and the CV text, the same subset `_scrape_core`'s condense pass
    already reads, so matching has no template-file dependency.

    Args:
        jobs_dir: Root directory for scraped postings (defaults to the
            module-level `JOBS_DIR`).
        profile_dir: Directory containing `config.json` (defaults to the
            module-level `PROFILE_DIR`).
        paths: Score only these posting files (those still unscored)
            instead of scanning the date directories — `add` scores the one
            posting it stored.
        progress: A `door.core.progress.Reporter` (or None) that receives
            "scoring" (0/total) and then "scored" (n/total) events as results
            are persisted.

    Returns:
        ``{"candidates_dir", "candidate_dirs", "unscored_before", "scored",
        "failed": [job_id, ...], "above_threshold", "model", "elapsed_s"}``
        — ``candidates_dir`` is the newest directory scanned,
        ``candidate_dirs`` all of them.

    Raises:
        ConfigError: `profile_dir/config.json` fails validation (issue #137), or the CV is still the example.
        FileNotFoundError: `profile_dir/config.json` is missing, or no
            recent `jobs_dir/postings/<YYYY-MM-DD>/` directory exists.
    """
    if jobs_dir is None:
        jobs_dir = workspace.JOBS_DIR
    if profile_dir is None:
        profile_dir = workspace.PROFILE_DIR

    config = common._load_config(profile_dir)
    common._require_own_cv(config, profile_dir)

    if paths is not None:
        candidate_dirs = sorted({Path(p).parent.parent for p in paths})
    else:
        candidate_dirs = _recent_candidates_dirs(jobs_dir, config.get("max_age_days", common._DEFAULT_MAX_AGE_DAYS))
    if not candidate_dirs:
        raise FileNotFoundError(f"no candidate directories found under {jobs_dir} (within max_age_days)")
    candidates_dir = candidate_dirs[-1]

    from door.matching import scorer

    cv_path = common._cv_path(config, profile_dir)
    if not cv_path.exists():
        cv_path = profile_dir / "cv.md"
    cv_md = cv_path.read_text() if cv_path.exists() else ""

    rubric_md = scorer.load_rubric_md()
    system_prompt = scorer.build_system_prompt(config, cv_md, rubric_md)

    if paths is not None:
        to_score_paths = [Path(p) for p in paths if json.loads(Path(p).read_text()).get("score") is None]
    else:
        to_score_paths = [p for d in candidate_dirs for p in _find_unscored(d)]
    unscored_before = len(to_score_paths)

    entries_by_id: dict[str, tuple[Path, dict]] = {}
    postings: list[dict] = []
    for path in to_score_paths:
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        job_id = data.get("id")
        if not job_id:
            continue
        if integrity.ensure(data):  # stored before the gate existed
            utils.write_json_atomic(path, data)
        entries_by_id[job_id] = (path, data)
        postings.append(data)

    min_score = config.get("min_score", common._DEFAULT_MIN_SCORE)
    needs_permit = bool(config.get("needs_work_permit", False))

    counters = {"scored": 0, "above_threshold": 0}

    def _persist(job_id: str, result: dict) -> None:
        entry = entries_by_id.get(job_id)
        if entry is None:
            return
        path, posting = entry
        updated = scorer.apply_result(posting, result, needs_work_permit=needs_permit)
        utils.write_json_atomic(path, updated)
        counters["scored"] += 1
        progress_mod.report("scored", counters["scored"], len(postings), stage="match")
        score = updated.get("score")
        if score is not None and score >= min_score:
            counters["above_threshold"] += 1

    if postings:
        progress_mod.report("scoring", 0, len(postings), stage="match")
    start = time.monotonic()
    errors: dict[str, str] = {}
    _results, failed = scorer.score_postings(
        postings,
        system_prompt=system_prompt,
        model=scorer.DEFAULT_MODEL,
        on_result=_persist,
        errors=errors,
    )
    elapsed_s = time.monotonic() - start

    return {
        "candidates_dir": str(candidates_dir),
        "candidate_dirs": [str(d) for d in candidate_dirs],
        "unscored_before": unscored_before,
        "scored": counters["scored"],
        "failed": failed,
        "failures": [{"id": i, "error": errors.get(i, "")} for i in failed[:MAX_FAILURES]],
        "above_threshold": counters["above_threshold"],
        "model": scorer.DEFAULT_MODEL,
        "elapsed_s": elapsed_s,
    }

