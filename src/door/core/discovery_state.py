"""State of employer discovery, one file per source: ``jobs/discovery/<source>.json``.

(LinkedIn's was ``jobs/linkedin_discovery.json``; `load` copies it to the new place the first time, and
leaves the old file alone. The helpers below are generic; the wording speaks of LinkedIn, the first source.)


``{"last_run": iso, "pushback_at": iso?, "seen": {company_lower: {"outcome": "easy_apply", "at": iso}},
"pace": {"budget", "factor", "clean_runs"}, "history": [<one observation per run>], "mode"?,
"rotation"?, "searched"?}``.
(Employers seen on search cards but not yet read wait in ``jobs/candidates.json``.) ``last_run`` moves only when a
run finished without a stop, so the next one reaches back over what a stopped run missed;
``pushback_at`` rests discovery for a day (`REST_HOURS`); ``seen`` keeps employers already
looked at from being fetched again for `RETRY_DAYS`.

The pace adapts to what LinkedIn tolerates: a run may make ``pace.budget`` requests (search pages
and job pages together), pausing ``BASE_PAUSE`` times ``pace.factor`` between two. A refusal halves
the budget (to `MIN_BUDGET`) and doubles the factor (to `MAX_FACTOR`); `CLEAN_RUNS_TO_RECOVER`
runs in a row that were not refused double the budget (to `DEFAULT_BUDGET`) and halve the factor
again. Every run that made a request is logged in ``history`` (the last `HISTORY_KEEP`): when,
mode, requests, pause, outcome (``ok``, ``budget``: the budget was spent, ``refused``, ``error``, ``cancelled``),
and for a refusal ``first_429`` (``after_requests``, ``after_s``), so the real limit can be read
later. ``mode`` (optional) overrides `SEARCH_MODE`; ``rotation`` and ``searched`` serve the
``rotate`` mode (one query per keyword, round-robin: the keywords a run's budget did not reach come
first next time, each searched back to its own last time).
Pure helpers over a dict, plus the atomic load/save. The caller holds the ledger lock while it writes.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from door.core import freshness, utils

DIR = "discovery"
LEGACY = {"linkedin": "linkedin_discovery.json"}  # a source's file before the per-source layout
REST_HOURS = 24
RETRY_DAYS = 90
_OVERLAP = timedelta(days=1)

SEARCH_MODE = "rotate"  # "rotate": one quoted query per keyword, the union read; "combined": one boolean OR search (returns fewer cards)
MODES = ("combined", "rotate")
DEFAULT_BUDGET = 150  # requests a run (search pages + job pages); a 429 came after ~110-130 at this pace, 2026-10-14
WINDOW_DAYS = 7  # discovery reaches back at most this far: it looks for who is hiring now
MIN_BUDGET = 10
BASE_PAUSE = (2.0, 4.0)  # seconds between two requests, at factor 1
MAX_FACTOR = 4
CLEAN_RUNS_TO_RECOVER = 3
HISTORY_KEEP = 30


def path(jobs_dir: Path, source: str) -> Path:
    return Path(jobs_dir) / DIR / f"{source}.json"


def _read(file: Path) -> dict | None:
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load(jobs_dir: Path, source: str) -> dict:
    """The *source*'s state, or an empty one when the file is missing or unreadable. A source with a
    legacy file and no new one is migrated by copy (the old file stays)."""
    new = path(jobs_dir, source)
    data = _read(new) if new.exists() else None
    if data is None and not new.exists() and source in LEGACY:
        data = _read(Path(jobs_dir) / LEGACY[source])
        if data is not None:
            utils.write_json_atomic(new, data)
    state = data if data is not None else {}
    if not isinstance(state.get("seen"), dict):
        state["seen"] = {}
    return state


def save(jobs_dir: Path, source: str, state: dict) -> None:
    utils.write_json_atomic(path(jobs_dir, source), state)


def _window(max_age_days: int | None) -> int:
    return WINDOW_DAYS if max_age_days is None else min(WINDOW_DAYS, max_age_days)


def since(state: dict, max_age_days: int | None, now: datetime) -> datetime | None:
    """The oldest posting date to look at: the last run minus a day, at most `WINDOW_DAYS` (and
    *max_age_days*) back."""
    cap = now - timedelta(days=_window(max_age_days))
    last = freshness._parse_dt(state.get("last_run"))
    if last is None:
        return cap
    return max(last - _OVERLAP, cap)


def resting_until(state: dict, now: datetime, source: str) -> datetime | None:
    """When discovery may ask *source* again after a refusal; None when it is not resting."""
    return freshness.resting_until(source, REST_HOURS, {source: state}, now)


def known(state: dict, now: datetime) -> set[str]:
    """Lowercase names of the employers seen less than `RETRY_DAYS` ago."""
    out = set()
    for name, entry in state["seen"].items():
        at = freshness._parse_dt(entry.get("at")) if isinstance(entry, dict) else None
        if at is not None and now - at < timedelta(days=RETRY_DAYS):
            out.add(name)
    return out


def record(state: dict, company: str, outcome: str, now: datetime) -> None:
    state["seen"][company.lower()] = {"outcome": outcome, "at": now.isoformat()}


def finish(state: dict, now: datetime) -> None:
    """A run that was not stopped: stamp it and forget an old refusal."""
    state["last_run"] = now.isoformat()
    state.pop("pushback_at", None)


def refused(state: dict, now: datetime) -> None:
    state["pushback_at"] = now.isoformat()


def search_mode(state: dict) -> str:
    """``combined`` or ``rotate``: the state's ``mode`` when it names one, else `SEARCH_MODE`."""
    mode = state.get("mode")
    return mode if mode in MODES else SEARCH_MODE


def rotation(state: dict, keywords: list[str], count: int) -> list[str]:
    """The next *count* keywords of the round-robin (wrapping), at most all of them."""
    if not keywords:
        return []
    start = state.get("rotation") if isinstance(state.get("rotation"), int) else 0
    n = min(count, len(keywords))
    return [keywords[(start + i) % len(keywords)] for i in range(n)]


def advance_rotation(state: dict, keywords: list[str], count: int) -> None:
    if keywords:
        start = state.get("rotation") if isinstance(state.get("rotation"), int) else 0
        state["rotation"] = (start + min(count, len(keywords))) % len(keywords)


def mark_searched(state: dict, keyword: str, now: datetime) -> None:
    state.setdefault("searched", {})[keyword.lower()] = now.isoformat()


def keyword_since(state: dict, keyword: str, max_age_days: int | None, now: datetime) -> datetime | None:
    """The oldest posting date to look at for one *keyword*: its last search minus a day, at most
    `WINDOW_DAYS` (and *max_age_days*) back (a keyword never searched reaches the whole window)."""
    cap = now - timedelta(days=_window(max_age_days))
    searched = state.get("searched")
    last = freshness._parse_dt(searched.get(keyword.lower())) if isinstance(searched, dict) else None
    if last is None:
        return cap
    return max(last - _OVERLAP, cap)


def _clamp(value, lo: int, hi: int, default: int) -> int:
    return max(lo, min(hi, value)) if isinstance(value, int) and not isinstance(value, bool) else default


def pace(state: dict) -> dict:
    """``{"budget", "factor", "pause": (lo, hi)}`` for the next run: the defaults until a refusal."""
    raw = state.get("pace") if isinstance(state.get("pace"), dict) else {}
    budget = _clamp(raw.get("budget"), MIN_BUDGET, DEFAULT_BUDGET, DEFAULT_BUDGET)
    factor = _clamp(raw.get("factor"), 1, MAX_FACTOR, 1)
    return {"budget": budget, "factor": factor, "pause": (BASE_PAUSE[0] * factor, BASE_PAUSE[1] * factor)}


def record_run(
    state: dict, now: datetime, *, mode: str, requests: int, pages: int, job_pages: int, outcome: str,
    seconds: float, first_429: dict | None = None,
) -> None:
    """Log a run's observation and adapt the pace (see the module doc). A run without a request
    says nothing about LinkedIn and is neither logged nor counted."""
    if requests <= 0:
        return
    used = pace(state)
    history = state.get("history") if isinstance(state.get("history"), list) else []
    history.append({"at": now.isoformat(), "mode": mode, "requests": requests, "pages": pages,
                    "job_pages": job_pages, "budget": used["budget"], "pause": list(used["pause"]),
                    "outcome": outcome, "seconds": round(seconds, 1), "first_429": first_429})
    state["history"] = history[-HISTORY_KEEP:]
    clean = state.get("pace", {}).get("clean_runs", 0) if isinstance(state.get("pace"), dict) else 0
    budget, factor = used["budget"], used["factor"]
    if outcome == "refused":
        budget, factor, clean = max(MIN_BUDGET, budget // 2), min(MAX_FACTOR, factor * 2), 0
    elif outcome in ("ok", "budget"):
        clean = clean + 1 if isinstance(clean, int) else 1
        if clean >= CLEAN_RUNS_TO_RECOVER:
            budget, factor, clean = min(DEFAULT_BUDGET, budget * 2), max(1, factor // 2), 0
    elif outcome != "cancelled":  # a run the user cut short says nothing about LinkedIn
        clean = 0
    state["pace"] = {"budget": budget, "factor": factor, "clean_runs": clean}
