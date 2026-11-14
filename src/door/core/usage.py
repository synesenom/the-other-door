"""How much of the Claude plan goes where, and how much is left, in the terms a user cares about (#575).

What used the plan this week, as a share per activity a user knows ("Finding jobs",
"Preparing applications", "Everything else"; `week()`); how full the plan's 5-hour and 7-day
windows were after the latest call (`latest()`), as `claude` reports it in each call's
`rate_limit_event`; and about how many more finds and prepares fit (`room()`), from how much
of a window a unit of weight uses (`calibration()`) and how heavy a run is (`run_sizes()`).

Every `claude -p` call asks for a stream (`claude_cli.STREAM_ARGS`), whose result envelope
(`claude_cli.read_stream`) carries `total_cost_usd`, what the call would cost at API prices.
It is the weight that makes a cached, a Haiku and a Sonnet call comparable, and it is shown
as what each activity cost at API prices (`cost()`, #64): the same yardstick for everyone,
whatever their plan, an estimate from `claude`'s own price table and not a bill (the plan is
not charged per call). `record()` appends one line per call
to `jobs/usage.jsonl` (`LOG_NAME`): when, what for (a key of `FEATURES`), how many postings
it scored, that weight, the windows' readings (`u5`/`r5`/`u7`/`r7`/`status`) and, per model, its input, output,
cache-read and cache-write tokens (`m`; older lines lack it, and nothing shows it yet). It is
called by `claude_cli.run()` (so by `claude_cli.ask()`) and by `matching/scorer.py`,
`matching/language.py` and `core/scraper_fix.py`, which run `claude` themselves.

The log is append-only and this computer's: one short line per write under a process lock,
outside the ledger lock (an `ask` holds none), and left out of `data export` and Drive sync.
"""

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from door.core import workspace

LOG_NAME = "usage.jsonl"

BUCKETS = {
    "find": "Finding jobs",
    "prepare": "Preparing applications",
    "other": "Everything else",
}

# What each call is for, and the activity it counts towards. A call site names its key
# (`claude_cli.run`/`ask`'s `feature=`, or `record`); tests/core/test_usage_call_sites_unit.py
# checks every one does.
FEATURES = {
    "match_scoring": "find",
    "title_translation": "find",
    "careers_lookup": "find",
    "tailoring": "prepare",
    "tailoring_retry": "prepare",  # the one extra tailor run after the ATS read-back; not another application prepared
    "revise": "prepare",
    "draft_cv": "other",
    "draft_stories": "other",
    "infer_basics": "other",
    "keywords": "other",
    "suggest_titles": "other",
    "enrich": "other",
    "skill_gaps": "other",
    "market_aliases": "other",
    "salary": "other",
    "import_posting": "other",
    "ask": "other",
    "scraper_fix": "other",
}

# What each feature is called where a user reads the cost (`cost`); a test checks every feature has one.
FEATURE_LABELS = {
    "match_scoring": "Scoring postings",
    "title_translation": "Translating job titles",
    "careers_lookup": "Finding careers pages",
    "tailoring": "Tailoring the CV and letter",
    "tailoring_retry": "Tailoring again after the ATS check",
    "revise": "Revising materials",
    "draft_cv": "Drafting the CV",
    "draft_stories": "Drafting stories",
    "infer_basics": "Reading your details",
    "keywords": "Proposing search terms",
    "suggest_titles": "Suggesting job titles",
    "enrich": "Expanding the CV",
    "skill_gaps": "Skill-gap reports",
    "market_aliases": "Market report",
    "salary": "Salary estimates",
    "import_posting": "Adding a job",
    "ask": "Questions about your jobs",
    "scraper_fix": "Fixing a scraper",
}

# Before this computer has history, a find is sized as scoring this many postings and a
# prepare as scoring this many (a real run scored 40; a prepare weighed about 150 postings).
DEFAULT_POSTINGS_PER_RUN = 40
DEFAULT_PREPARE_WEIGHT = 150
WINDOW = 50  # the latest scoring calls the weight of one scored posting is averaged over
RUNS = 10  # the latest finds a find's size is averaged over
PREPARES = 20  # the latest prepares a prepare's size is averaged over

# Calibration (`calibration`): a segment is consecutive readings of one window with the same
# reset time and no gap over `SEGMENT_GAP`; the latest segments up to about
# `CALIBRATION_LINES` lines are read, and at least `MIN_LINES` lines and a total rise of
# `MIN_RISE` are needed, so the two-decimal rounding of `claude`'s figures does not dominate.
SEGMENT_GAP = timedelta(minutes=15)
CALIBRATION_LINES = 200
MIN_LINES = 20
MIN_RISE = 0.02

_write_lock = threading.Lock()


def _check(feature: str) -> str:
    try:
        return FEATURES[feature]
    except KeyError:
        raise ValueError(f"unknown usage feature {feature!r}") from None


def weight(stdout: str | None) -> float | None:
    """The `total_cost_usd` of a `claude -p` result envelope (`claude_cli.read_stream`'s; an
    error envelope's too: it drew on the plan), or None when `stdout` is no envelope or carries none."""
    try:
        env = json.loads(stdout or "")
    except (json.JSONDecodeError, TypeError):
        return None
    cost = env.get("total_cost_usd") if isinstance(env, dict) else None
    if isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0:
        return None
    return float(cost)


# A window's short name on a log line: `u5`/`r5` are the 5-hour window's fraction used and reset
# time (epoch seconds), `u7`/`r7` the 7-day window's (`claude_cli.read_stream`'s `limits`).
_WINDOW_KEYS = {"five_hour": "5", "seven_day": "7"}


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# A model's token counts on a log line: `i` input, `o` output, `cr` cache read, `cw` cache write
# (`modelUsage`'s `inputTokens`, `outputTokens`, `cacheReadInputTokens`, `cacheCreationInputTokens`).
_TOKEN_KEYS = {"inputTokens": "i", "outputTokens": "o", "cacheReadInputTokens": "cr",
               "cacheCreationInputTokens": "cw"}


def _models(stdout: str | None) -> dict:
    """`{model: {"i", "o", "cr", "cw"}}` from a result envelope's `modelUsage`: only the counts
    present and non-negative, a model with none left out; `{}` for anything unreadable. Never raises."""
    try:
        env = json.loads(stdout or "")
    except (json.JSONDecodeError, TypeError):
        return {}
    usage = env.get("modelUsage") if isinstance(env, dict) else None
    if not isinstance(usage, dict):
        return {}
    models = {}
    for model, figures in usage.items():
        if not isinstance(figures, dict):
            continue
        tokens = {short: int(figures[key]) for key, short in _TOKEN_KEYS.items()
                  if _number(figures.get(key)) and figures[key] >= 0}
        if tokens:
            models[str(model)] = tokens
    return models


def _readings(limits: dict | None) -> dict:
    """The `u5`/`r5`/`u7`/`r7`/`status` fields of a log line, from a call's `limits`."""
    fields = {}
    if not isinstance(limits, dict):
        return fields
    for window, short in _WINDOW_KEYS.items():
        reading = limits.get(window)
        if not isinstance(reading, dict):
            continue
        if _number(reading.get("used")):
            fields[f"u{short}"] = float(reading["used"])
        if _number(reading.get("resets_at")):
            fields[f"r{short}"] = int(reading["resets_at"])
    if isinstance(limits.get("status"), str):
        fields["status"] = limits["status"]
    return fields


def record(feature: str, stdout: str | None, *, units: int = 1, limits: dict | None = None,
           jobs_dir: Path | None = None) -> dict | None:
    """Append one call to the log; the line written, or None when the output carries neither a
    weight nor a reading of the plan, or the log cannot be written (never raises for that: an
    answer matters more than its bookkeeping). `units` is the postings a scoring call scored;
    `limits` is the call's reading of the plan (`claude_cli.read_stream`), written as
    `u5`/`r5`/`u7`/`r7`/`status`; the models it used and their tokens go under `m`
    (`{model: {i, o, cr, cw}}`, from the envelope's `modelUsage`). A refused call with no weight is still written: its
    `rejected` is what the user needs to see.

    Raises:
        ValueError: `feature` is not in `FEATURES`.
    """
    _check(feature)
    cost = weight(stdout)
    readings = _readings(limits)
    if cost is None and not readings:
        return None
    line = {"at": datetime.now(timezone.utc).isoformat(), "feature": feature, "units": max(0, int(units))}
    if cost is not None:
        line["weight"] = cost
    line.update(readings)
    models = _models(stdout)
    if models:
        line["m"] = models
    path = Path(jobs_dir or workspace.JOBS_DIR) / LOG_NAME
    try:
        with _write_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line) + "\n")
    except OSError:
        return None
    return line


def read(jobs_dir: Path | None = None) -> list[dict]:
    """Every readable line of the log, oldest first; lines of unknown features are left out."""
    try:
        text = (Path(jobs_dir or workspace.JOBS_DIR) / LOG_NAME).read_text(encoding="utf-8")
    except OSError:
        return []
    lines = []
    for raw in text.splitlines():
        try:
            line = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(line, dict) and line.get("feature") in FEATURES:
            lines.append(line)
    return lines


def _weight(line: dict) -> float:
    value = line.get("weight")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _units(line: dict) -> int:
    value = line.get("units")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _in_window(jobs_dir: Path | None, days: int, now: datetime | None) -> list[dict]:
    since = ((now or datetime.now(timezone.utc)) - timedelta(days=days)).isoformat()
    return [line for line in read(jobs_dir) if str(line.get("at", "")) >= since]


def _what_it_did(bucket: str, mine: list[dict]) -> tuple[int, str]:
    """What an activity's calls did: postings scored, applications prepared, or the calls."""
    if bucket == "find":
        return sum(_units(line) for line in mine if line["feature"] == "match_scoring"), "postings scored"
    if bucket == "prepare":
        return sum(1 for line in mine if line["feature"] == "tailoring"), "applications prepared"
    return len(mine), "other requests"


def week(jobs_dir: Path | None = None, *, days: int = 7, now: datetime | None = None) -> dict:
    """What used the plan in the last `days` days: each activity's share (0-1, largest first)
    with what it did (postings scored, applications prepared, other calls), and the heaviest.

    Returns:
        ``{"days", "activities": [{"activity", "label", "share", "count", "of"}], "heaviest"}``;
        no activities and `heaviest` None when nothing was recorded.
    """
    lines = _in_window(jobs_dir, days, now)
    total = sum(_weight(line) for line in lines)
    activities = []
    for bucket, label in BUCKETS.items():
        mine = [line for line in lines if FEATURES[line["feature"]] == bucket]
        if not mine:
            continue
        count, of = _what_it_did(bucket, mine)
        share = sum(_weight(line) for line in mine) / total if total else 0.0
        activities.append({"activity": bucket, "label": label, "share": round(share, 3), "count": count, "of": of})
    activities.sort(key=lambda a: -a["share"])
    return {"days": days, "activities": activities, "heaviest": activities[0]["activity"] if activities else None}


def cost(jobs_dir: Path | None = None, *, days: int = 7, records: list[dict] | None = None,
         now: datetime | None = None) -> dict | None:
    """What the calls of the last `days` days cost at API prices (`total_cost_usd`), per activity
    (largest first) and per feature within it (largest first), and what one find and one prepare
    cost (`run_sizes`); None before any call was weighed. `records` are the run records (read
    from `jobs/runs/` when not given).

    Returns:
        ``{"days", "usd", "activities": [{"activity", "label", "usd", "count", "of",
        "features": [{"feature", "label", "usd", "calls"}]}], "per_run": {"find", "prepare"}}``,
        dollars rounded to 4 places, `per_run` values None when there is nothing to size by.
    """
    jobs_dir = Path(jobs_dir or workspace.JOBS_DIR)
    every = read(jobs_dir)
    if not any(_weight(line) > 0 for line in every):
        return None
    lines = _in_window(jobs_dir, days, now)
    activities = []
    for bucket, label in BUCKETS.items():
        mine = [line for line in lines if FEATURES[line["feature"]] == bucket]
        if not mine:
            continue
        count, of = _what_it_did(bucket, mine)
        features = []
        for feature in dict.fromkeys(line["feature"] for line in mine):
            calls = [line for line in mine if line["feature"] == feature]
            features.append({"feature": feature, "label": FEATURE_LABELS[feature],
                             "usd": round(sum(_weight(line) for line in calls), 4), "calls": len(calls)})
        features.sort(key=lambda f: -f["usd"])
        activities.append({"activity": bucket, "label": label, "usd": round(sum(_weight(line) for line in mine), 4),
                           "count": count, "of": of, "features": features})
    activities.sort(key=lambda a: -a["usd"])
    sizes = run_sizes(every, _records(jobs_dir) if records is None else records)
    return {"days": days, "usd": round(sum(_weight(line) for line in lines), 4), "activities": activities,
            "per_run": {kind: round(value, 4) if value else None for kind, value in sizes.items()}}


def latest(jobs_dir: Path | None = None, *, now: datetime | None = None) -> dict | None:
    """The plan as the newest call that read it left it, or None before any call did.

    A window whose reset time has passed by `now` reads as unused (`{"used": 0.0}`, its next
    reset unknown), and the call's `status` is dropped then: it may have spoken of that window.

    Returns:
        ``{"at", "status"?, "five_hour"?: {"used"?, "resets_at"?}, "seven_day"?: {...}}``.
    """
    now_s = (now or datetime.now(timezone.utc)).timestamp()
    for line in reversed(read(jobs_dir)):
        windows, reset = {}, False
        for window, short in _WINDOW_KEYS.items():
            used, resets_at = line.get(f"u{short}"), line.get(f"r{short}")
            reading = {}
            if _number(used):
                reading["used"] = float(used)
            if _number(resets_at):
                if resets_at <= now_s:
                    reading, reset = {"used": 0.0}, True
                else:
                    reading["resets_at"] = int(resets_at)
            if reading:
                windows[window] = reading
        status = line.get("status") if isinstance(line.get("status"), str) else None
        if not windows and status is None:
            continue
        result = {"at": line.get("at")}
        if status is not None and not reset:
            result["status"] = status
        return {**result, **windows}
    return None


def _at(line: dict) -> datetime | None:
    try:
        at = datetime.fromisoformat(str(line.get("at")))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def _segments(lines: list[dict], window: str) -> list[list[dict]]:
    """The log's readings of `window`, oldest first, cut into segments: a new one at each new
    reset time and after each gap of over `SEGMENT_GAP`."""
    short = _WINDOW_KEYS[window]
    segments: list[list[dict]] = []
    previous = None
    for line in lines:
        used, reset, at = line.get(f"u{short}"), line.get(f"r{short}"), _at(line)
        if not (_number(used) and _number(reset)) or at is None:
            continue
        if previous is None or reset != previous[0] or at - previous[1] > SEGMENT_GAP:
            segments.append([])
        segments[-1].append(line)
        previous = (reset, at)
    return segments


def calibration(lines: list[dict], window: str) -> float | None:
    """How much of `window` (`"five_hour"` or `"seven_day"`) one unit of weight uses, from the
    log's `lines` (oldest first); None until there is enough to go on (`MIN_LINES`, `MIN_RISE`).

    Within a segment the window's use telescopes: its rise from the first reading to the last
    is what every call after the first used (the first call's own share is unknown, so its
    weight is left out), whatever order parallel calls finished in. The latest segments are
    pooled, up to about `CALIBRATION_LINES` lines: the sum of their rises over the sum of
    their weights. The user's own Claude chats during a segment add to its rise, so this
    comes out too large and the room left too small: an error on the safe side.
    """
    short = _WINDOW_KEYS[window]
    rise = weight = 0.0
    count = 0
    for segment in reversed(_segments(lines, window)):
        if count >= CALIBRATION_LINES:
            break
        count += len(segment)
        if len(segment) < 2:
            continue
        rise += segment[-1][f"u{short}"] - segment[0][f"u{short}"]
        weight += sum(_weight(line) for line in segment[1:])
    if count < MIN_LINES or rise < MIN_RISE or weight <= 0:
        return None
    return rise / weight


def _per_posting(lines: list[dict]) -> float | None:
    """The weight of scoring one posting, from the latest `WINDOW` scoring calls that scored any."""
    scored = [line for line in lines if line["feature"] == "match_scoring" and _units(line)][-WINDOW:]
    postings = sum(_units(line) for line in scored)
    per = sum(_weight(line) for line in scored) / postings if postings else 0.0
    return per if per > 0 else None


def run_sizes(lines: list[dict], records: list[dict]) -> dict:
    """The weight of one find and of one prepare, or None for one there is nothing to size by.

    A find is the mean, over the latest `RUNS` run records with any finding call between their
    `started_at` and `finished_at`, of those calls' weight (scoring, title translation, careers
    lookups); a prepare the mean of the latest `PREPARES` tailoring calls, each with the retry calls after the first of them. Before there is
    such history, each is `DEFAULT_POSTINGS_PER_RUN` / `DEFAULT_PREPARE_WEIGHT` times the
    weight of scoring one posting.

    Returns:
        ``{"find": float | None, "prepare": float | None}``.
    """
    finding = [(at, line) for line in lines if FEATURES[line["feature"]] == "find" and (at := _at(line))]
    runs = []
    for record in records:
        try:
            start = datetime.fromisoformat(str(record.get("started_at")))
            end = datetime.fromisoformat(str(record.get("finished_at")))
        except ValueError:
            continue
        mine = [line for at, line in finding if start <= at <= end]
        if mine:
            runs.append(sum(_weight(line) for line in mine))
    runs = runs[-RUNS:]
    tailoring = [i for i, line in enumerate(lines) if line["feature"] == "tailoring"][-PREPARES:]
    # A retry belongs to the prepare it followed: counted from the first selected tailoring line on.
    tailored = (sum(_weight(line) for line in lines[tailoring[0]:] if line["feature"] in ("tailoring", "tailoring_retry"))
                / len(tailoring)) if tailoring else None
    per_posting = _per_posting(lines)
    find = sum(runs) / len(runs) if runs else (DEFAULT_POSTINGS_PER_RUN * per_posting if per_posting else None)
    prepare = (tailored if tailored is not None
               else (DEFAULT_PREPARE_WEIGHT * per_posting if per_posting else None))
    return {"find": find or None, "prepare": prepare or None}


def _records(jobs_dir: Path) -> list[dict]:
    """The run records of `jobs/runs/`, oldest first; unreadable ones skipped."""
    records = []
    for path in sorted((jobs_dir / "runs").glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict) and record.get("started_at"):
            records.append(record)
    return sorted(records, key=lambda r: str(r["started_at"]))


_WARNINGS = {"allowed_warning": "Claude's usage limit is close", "rejected": "Claude's usage limit is reached"}


def room(jobs_dir: Path | None = None, *, records: list[dict] | None = None, now: datetime | None = None) -> dict | None:
    """How full the plan's windows are and how many more finds and prepares fit, as of the
    latest call that read the plan; None before any did.

    For each window with a reading and a `calibration`, what is left (1 − used) over its
    calibration is the weight that still fits; the window where less fits binds, and each
    `room` is that over the size of one run (`run_sizes`), rounded down. `room` is None until
    a window is calibrated and a run sized; the windows' figures stand on their own.
    `allowed_warning` adds a `warning`; `rejected` leaves no room. Chats outside The other door
    are not seen until its next call, so the answer is as of `as_of`. `records` are the run
    records (read from `jobs/runs/` when not given).

    Returns:
        ``{"as_of", "status"?, "five_hour"?: {"used"?, "resets_at"? (ISO)}, "seven_day"?: {...},
        "room": {"find": int | None, "prepare": int | None} | None, "binding": window | None,
        "warning"?}``.
    """
    jobs_dir = Path(jobs_dir or workspace.JOBS_DIR)
    reading = latest(jobs_dir, now=now)
    if reading is None:
        return None
    lines = read(jobs_dir)
    status = reading.get("status")
    result = {"as_of": reading["at"]}
    if status is not None:
        result["status"] = status
    left = {}
    for window in _WINDOW_KEYS:
        figures = reading.get(window)
        if figures is None:
            continue
        shown = {"used": figures["used"]} if "used" in figures else {}
        if "resets_at" in figures:
            shown["resets_at"] = datetime.fromtimestamp(figures["resets_at"], timezone.utc).isoformat()
        result[window] = shown
        k = calibration(lines, window) if "used" in figures else None
        if k:
            left[window] = max(0.0, 1.0 - figures["used"]) / k
    binding, plan_room = None, None
    if status == "rejected":
        used = {w: reading[w].get("used", 0.0) for w in _WINDOW_KEYS if w in reading}
        binding = max(used, key=used.get) if used else None
        plan_room = {"find": 0, "prepare": 0}
    elif left:
        binding = min(left, key=left.get)
        sizes = run_sizes(lines, _records(jobs_dir) if records is None else records)
        if any(sizes.values()):
            plan_room = {kind: int(left[binding] / size) if size else None for kind, size in sizes.items()}
    result["room"] = plan_room
    result["binding"] = binding
    if status in _WARNINGS:
        result["warning"] = _WARNINGS[status]
    return result
