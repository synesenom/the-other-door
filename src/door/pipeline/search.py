"""Step 1, `search`: the job boards, searched with the profile's keywords.

Drives `door.commands.scrape._scrape_core` (the shared engine) over the boards
(every board of the profile's country, or ``--boards``): new postings go to `jobs/postings/<date>/<board>/` as ever,
under the boards' freshness rule (the watermark, at most ``max_age_days`` back).
Each posting's employer and apply link also join the candidates queue (`jobs/candidates.json`),
unless the employer is already settled in `profile/companies.json`, for `follow` to look at.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from door import pipeline
from door.commands import _common as common
from door.commands import scrape as scrape_cmd
from door.core import candidates, freshness, sites, utils, workspace
from door.core import companies as store
from door.core.sites import BOARDS
from door.matching import title_fit


def queue_postings(paths, jobs_dir: Path, profile_dir: Path, now: datetime, terms=None) -> int:
    """Queue the employer and links of each posting file in *paths* whose title is on topic for *terms*
    (`title_fit.topic_terms` of the profile when None: any content word of ``search_keywords``, else ``role_targets``) and whose employer is not
    settled in the employer list: an employer none of whose ads fit is neither queued nor recorded.
    Returns how many employers are new to the queue. Unreadable files are skipped."""
    if terms is None:
        terms = title_fit.topic_terms(common._load_config(profile_dir))
    items = common._company_items(profile_dir)
    queue = candidates.load(jobs_dir)
    before = len(queue)
    for path in paths:
        try:
            posting = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        name = (posting.get("company") or "").strip() if isinstance(posting, dict) else ""
        if not name or not title_fit.on_topic(posting.get("title") or "", terms) or store.is_settled(items, name, now):
            continue
        links = [l for l in (posting.get("apply_url"), posting.get("url")) if l]
        candidates.add(queue, name, links=links, titles=[posting.get("title") or ""],
                       source=str(posting.get("source") or Path(path).parent.name), now=now)
    candidates.save(jobs_dir, queue)
    return len(queue) - before


def stamp_employers(paths, profile_dir: Path) -> int:
    """Write ``employer`` into each posting file in *paths* whose company is a name or alias on the employer
    list (a board names no feed, so no shared-feed fallback); other postings are left alone. Returns how many
    files changed. Unreadable files are skipped."""
    items = common._company_items(profile_dir)
    changed = 0
    for path in paths:
        try:
            posting = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        name = str(posting.get("company") or "").strip() if isinstance(posting, dict) else ""
        entry = store.find(items, name) if name else None
        if entry is not None and posting.get("employer") != entry.name:
            posting["employer"] = entry.name
            utils.write_json_atomic(Path(path), posting)
            changed += 1
    return changed


def _summary(block: dict) -> str:
    text = f"{block['postings']:,} postings from {len(block['sites'])} boards"
    return text + (f", {block['failed']} failed" if block["failed"] else "")


@common._locked("search")
def _search_core(
    *, boards: list[str] | None = None,
    jobs_dir: Path | None = None, profile_dir: Path | None = None, progress=None,
) -> dict:
    """Search the boards; queue the employers of what was found. Never prints.

    Args:
        boards: Boards to search instead of every board of the profile's country (names from
            `door.core.sites.BOARDS`).

    Returns:
        ``{"step": "search", "boards", "run_date", "sites": [<per-board outcome>],
        "postings", "queued", "failed", "liveness", "elapsed_s", "summary"}`` — ``queued`` is how
        many employers were new to the candidates queue, ``failed`` the boards that failed or errored.

    Raises:
        ConfigError / FileNotFoundError: the profile config is missing or invalid.
        ValueError: ``boards`` names an unknown board.
    """
    jobs_dir = workspace.JOBS_DIR if jobs_dir is None else jobs_dir
    profile_dir = workspace.PROFILE_DIR if profile_dir is None else profile_dir
    config = common._load_config(profile_dir)
    chosen = list(boards) if boards else sites.boards_for_location(config.get("location", ""))
    unknown = [b for b in chosen if b not in BOARDS]
    if unknown:
        raise ValueError(f"unknown board(s): {', '.join(unknown)}. Valid boards: {', '.join(BOARDS)}")

    started = time.monotonic()
    with pipeline.running("search") as step:  # its total is the boards it lists
        state, now = freshness.load_scrape_state(jobs_dir), datetime.now(timezone.utc)
        pipeline.items("search", [(b, sites.SITES[b].label) for b in chosen
                                  if scrape_cmd._held_back(b, state, now) is None])
        result = scrape_cmd._scrape_core(chosen, jobs_dir=jobs_dir, profile_dir=profile_dir,
                                         mode="search", passes=False)
        stamp_employers(result["written"], profile_dir)
        queued = queue_postings(result["written"], jobs_dir, profile_dir, datetime.now(timezone.utc))
        outcomes = result["sites"]
        ok = [e for e in outcomes if e["outcome"] == "ok"]
        block = {
            "step": "search", "boards": chosen, "run_date": result["run_date"], "sites": outcomes,
            "postings": sum(e.get("count", 0) for e in ok),
            "queued": queued,
            "failed": sum(1 for e in outcomes if e["outcome"] in ("error", "failed")),
            "liveness": result["liveness"],
            "candidates_dir": result["candidates_dir"],
        }
        block["summary"] = step.summary = _summary(block)
    block["elapsed_s"] = time.monotonic() - started
    return block
