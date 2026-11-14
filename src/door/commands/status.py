"""`jobs status` (set a status, picked from lists), `jobs summary` (the pipeline dashboard with
"since last review"), and the review watermark `mark_reviewed` stamps."""

import hashlib
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

import door.core.tracker as _tracker_mod
from door.commands import _common as common
from door.commands import _progress, _prompts
from door.core import companies, drive, lock, progress, recurring, runs, usage, workspace
from door.core import utils
from door.tailoring import facts as facts_mod


# An ad shorter than this is a snippet, not the ad: too little for the analysis of what passes.
_SHORT_AD_CHARS = 400


@common._locked("set_status")
def _set_status_core(
    job_id: str,
    status: str,
    notes: str | None = None,
    jobs_dir: Path | None = None,
    *,
    at: str | None = None,
    progress=None,
) -> dict:
    """Set the application status for a job posting; return structured data.

    Mirrors the ``jobs status`` CLI's side effects (writes to
    ``jobs_dir/applications.json`` via `ApplicationTracker`, which keeps
    every change in the entry's history) but never prints — callers (CLI,
    MCP) render their own presentation from the returned dict.

    What the analysis of which applications pass needs is kept with it: when
    the event happened (``at``, for a change recorded afterwards) and, the
    first time a status means it was sent, a copy of the materials in ``jobs/output/<job_id>/sent/`` (what
    went out, whatever `revise` does later) with their hashes in the ledger.
    A sent application whose ad is not on disk (a posting, or the
    ``posting.json`` beside its materials) or is only a snippet gets a
    ``warning``; the status is recorded all the same.

    Args:
        job_id: The job: words from its company and title, or its id
            (see `_resolve_job_ref`).
        status: One of `tracker.STATUSES` (an interview round is
            ``interview:<stage>``).
        notes: Optional notes (e.g. for ``discarded`` — why "not this one", or
            what an interview covered and how it went), stored with the ledger entry; `list`
            hides discarded postings.
        jobs_dir: Directory containing `applications.json` (defaults to the
            module-level `JOBS_DIR`).
        at: When it happened, ``YYYY-MM-DD`` or an ISO datetime; None is now.
            An event dated before the latest one leaves the current status.
        progress: Reporter for the ledger lock's Drive pull and push.

    Returns:
        ``{"job_id", "status", "notes", "at", "current",
        "label" (title — company), "sent_dir"?, "warning"?}`` — ``at`` is the event's date, ``current``
        the status the job has now (``status`` unless the event was
        backdated before a later one), ``sent_dir`` where the copy of the
        materials went when one was taken.

    Raises:
        ValueError: `job_id` is not a valid slug, `status` is not a
            canonical status, or `at` is not a date or is in the future.
        tracker.DuplicateApplicationError: the job was already `"applied"`
            and the new status is also `"applied"`.
    """
    if jobs_dir is None:
        jobs_dir = workspace.JOBS_DIR

    job_id = common._resolve_job_ref(job_id, jobs_dir)
    when = _tracker_mod.parse_at(at) if at else None
    now = datetime.now(timezone.utc)

    notes = (notes or "").strip() or None
    app_tracker = _tracker_mod.ApplicationTracker(jobs_dir / "applications.json")
    first_sent = _tracker_mod.is_sent(status) and not any(
        _tracker_mod.is_sent(event.get("status")) for event in app_tracker.history(job_id)
    )
    out_dir = jobs_dir / "output" / job_id
    materials = _material_hashes(out_dir) if first_sent else None
    app_tracker.set_status(job_id, status, now=now, notes=notes, at=when, materials=materials or None)
    app_tracker.save()

    result = {
        "job_id": job_id, "status": status, "notes": notes, "at": (when or now).isoformat(),
        "current": app_tracker.get_status(job_id),
        "label": common._job_label(job_id, jobs_dir),
    }
    if materials:
        sent_dir = out_dir / "sent"
        sent_dir.mkdir(parents=True, exist_ok=True)
        for name in materials:
            shutil.copy2(out_dir / name, sent_dir / name)
        result["sent_dir"] = str(sent_dir)
    if _tracker_mod.is_sent(status):
        warnings = [w for w in (_ad_warning(jobs_dir, job_id), _unsupported_warning(out_dir, job_id)) if w]
        if warnings:
            result["warning"] = "; ".join(warnings)
    return result


def _material_hashes(out_dir: Path) -> dict[str, str]:
    """``{file: sha256}`` of the materials `prepare` leaves in `out_dir` that are there, and the CV photo
    `compile` copied beside them when the CV carries one (#605)."""
    from door.commands import compile as compile_cmd
    from door.commands import prepare as prepare_cmd

    names = (*prepare_cmd._TAILOR_OUTPUTS, *compile_cmd._PHOTO_FILES.values())
    return {name: hashlib.sha256((out_dir / name).read_bytes()).hexdigest() for name in names if (out_dir / name).is_file()}


def _ad_text(jobs_dir: Path, job_id: str) -> str:
    """The job's ad, the longer of its posting's and the one kept with its materials ("" if neither)."""
    from door.core.selection import find_posting

    kept = common._load_json_tolerant(jobs_dir / "output" / job_id / "posting.json")
    return max(((find_posting(jobs_dir, job_id) or {}).get("description") or "",
                kept.get("description") or ""), key=len).strip()


def _unsupported_warning(out_dir: Path, job_id: str) -> str | None:
    """Figures, employers, skills, certifications or degrees of the materials being sent that cv.md and the story bank do not back (#325)."""
    found = facts_mod.check(out_dir, workspace.PROFILE_DIR, write=False)
    if not found:
        return None
    values = ", ".join(dict.fromkeys(
        f"{c['value']} ({c['reason']})" if c.get("reason") else c["value"] for c in found))
    return (f"{len(found)} claim(s) in the sent materials are not in your cv.md: {values} "
            f"- check them before you rely on {job_id}")


def _ad_warning(jobs_dir: Path, job_id: str) -> str | None:
    """Why the job's ad will not serve the analysis of what passes, or None when it will."""
    ad = _ad_text(jobs_dir, job_id)
    if not ad:
        return (f"no ad text on disk for {job_id}: what passes can only be learned from the ads kept — "
                f"import the ad with `jobs add` and record the status on that posting")
    if len(ad) < _SHORT_AD_CHARS:
        return f"the ad on disk for {job_id} is only {len(ad)} characters, too little to learn from; keep the whole ad when you can"
    return None


@click.command()
@click.argument("job_id", metavar="JOB", required=False, default=None)
@click.argument("status", required=False, default=None, type=click.Choice(_tracker_mod.STATUSES))
@click.option("--notes", default=None, help="Notes — stored with the ledger entry: why, or how an interview went (e.g. `--notes \"too junior\"`).")
@click.option("--at", default=None, help="When it happened, YYYY-MM-DD, for a change recorded afterwards (default: now).")
def status(job_id: str | None, status: str | None, notes: str | None, at: str | None):
    """Set a posting's application status, picked from lists.

    `jobs status` alone lists your postings (the ones in play, then the
    matches you haven't acted on) to pick one, then the status, then an
    optional note. JOB (words from its company and title, e.g. `trustpilot`
    or "novonesis head of ai"; several matches are picked from) skips the
    first list, and STATUS the second: one of unapplied, prepared,
    applied, interview:screening, interview:impression, interview:assessment,
    interview:technical, ghosted, rejected, offer, discarded. Record one
    interview:<kind> per round; rejected or ghosted ends the last one.
    Picked from the list, a status also asks when it happened.
    """
    if job_id is None and status is not None:
        click.echo("Error: STATUS needs a JOB.", err=True)
        sys.exit(1)
    try:
        # Before the lock: a bad reference or date fails at once, not after the Drive sync.
        job_id = common._job_ref_cli(job_id, workspace.JOBS_DIR)
        if job_id is None:
            click.echo("No postings to pick from — `find` fetches some, `jobs add` brings one in.")
            return
        if at is not None:
            _tracker_mod.parse_at(at)
        if status is None:
            status = _pick_status(job_id)
            if at is None:
                at = _prompts.text("at", "When (YYYY-MM-DD; Enter for now)", default="", validate=_date_error) or None
            if notes is None:
                notes = _prompts.text("notes", "Note (optional: what it covered, how it went, why)", default="")
        with _progress.live_progress(enabled=common._stdout_is_tty()) as reporter:
            result = _set_status_core(job_id, status, notes, jobs_dir=workspace.JOBS_DIR,
                                      at=at, progress=reporter)
    except ValueError as exc:  # DuplicateApplicationError included
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    name = result.get("label") or result["job_id"]
    why = f" ({result['notes']})" if result["notes"] else ""
    if result["current"] == result["status"]:
        click.echo(f"Status for {name!r} set to {result['status']!r}{why}.")
    else:
        click.echo(f"Recorded {result['status']!r} for {name!r} on {result['at'][:10]}{why}; "
                   f"it is still {result['current']!r}.")
    if result.get("sent_dir"):
        click.echo(f"Kept a copy of what was sent in {common._display_path(result['sent_dir'])}.")
    if result.get("warning"):
        click.echo(f"Warning: {result['warning']}", err=True)


@click.command("summary")
def summary():
    """The pipeline dashboard: postings, matches by status, the applications
    ledger, how each kind of interview went, and what happened since the
    last review."""
    _print_pipeline_status()


# What each status means, for the picker `jobs status` opens.
_STATUS_HINTS = {
    "unapplied": "not acted on yet",
    "prepared": "materials made, not sent",
    "applied": "application sent",
    "interview:screening": "pre-screening: recruiter / HR call",
    "interview:impression": "first interview, non-technical",
    "interview:assessment": "personality or cognitive test",
    "interview:technical": "technical interview, case or take-home",
    "ghosted": "they stopped answering",
    "rejected": "they said no (after the last interview)",
    "offer": "offer received",
    "discarded": "not this one (hidden from `jobs`)",
}


def _pick_status(job_ref: str) -> str:
    """Ask for a job's new status from the one list of statuses."""
    job_id = common._resolve_job_ref(job_ref, workspace.JOBS_DIR)
    current = _tracker_mod.ApplicationTracker(workspace.JOBS_DIR / "applications.json").get_status(job_id) or "unapplied"
    width = max(map(len, _tracker_mod.STATUSES))
    return _prompts.select(
        "status", f"{common._job_label(job_id, workspace.JOBS_DIR)} is {current}. New status",
        choices=[(f"{label:<{width}}  {_STATUS_HINTS[label]}", label) for label in _tracker_mod.STATUSES],
        default=current,
    )


def _date_error(text: str) -> str | None:
    """Why `text` is not a date for `--at` ("" is fine: now), or None."""
    if not text.strip():
        return None
    try:
        _tracker_mod.parse_at(text)
    except ValueError as exc:
        return str(exc)
    return None


_LEDGER_STATUSES = _tracker_mod.STATUSES


def _status_summary_core(jobs_dir: Path | None = None, profile_dir: Path | None = None) -> dict:
    """The `jobs summary` dashboard as data: pipeline counts + ledger breakdown.

    Returns:
        ``{"min_score", "pipeline": {"total", "excluded", "applicable",
        "above_threshold", "unapplied", "above_threshold_by_status":
        {"unapplied", "prepared", "applied", "discarded"}}, "ledger": {<status>: count, ...}, "since_last_review":
        {...}, "interviews": {stage: {"passed", "rejected", "ghosted", "withdrawn",
        "pending"}}, "application": {"passed", "rejected", "ghosted",
        "withdrawn", "pending"}, "pass_rates": {stage: {"passed", "decided",
        "rate", "low", "high"}}, "in_progress": {...} | None, "employers": {"followed", "unfollowable",
        "unresolved"}, "drive": {"connected", "account", "last_synced",
        "last_error", "configured"}, "recurring_problem": bool, "plan": {...} | None, "cost": {...} | None}`` — every ledger status is present,
        0 when unused; ``interviews`` is `tracker.interview_outcomes` (only the
        stages that occur); ``application`` is `tracker.application_outcomes`
        (did each sent application lead to an interview); ``pass_rates`` is
        `tracker.pass_rate` for ``application`` and then each interview stage
        (rate of the decided rounds with its one-sigma Wilson interval, None
        until one is decided); ``since_last_review`` is `_since_last_review`'s dict;
        ``in_progress`` is None unless a run holds the ledger lock right now
        and has reported progress: ``{"purpose", "pid", "started_at",
        "message", "done", "total", "site", "stage", "updated_at"}`` (the
        latest known event, so it can lag the real state by a moment);
        ``recurring_problem`` is `recurring.check`: whether something keeps going wrong
        since the last problem report (a site, scoring, the server or a tool), no details;
        ``plan`` is `_plan_block`: how full the Claude plan's windows are, how many more finds
        and prepares fit (`usage.room`) and this week's shares (`usage.week`), or None before
        any call read the plan; ``cost`` is `usage.cost`: what the last 7 days' calls cost at API
        prices, per activity and feature, and one find and one prepare, or None before any call
        was weighed.
    """
    from door.core import selection

    if jobs_dir is None:
        jobs_dir = workspace.JOBS_DIR
    if profile_dir is None:
        profile_dir = workspace.PROFILE_DIR

    config = common._load_config_or_defaults(profile_dir)
    min_score = config.get("min_score", common._DEFAULT_MIN_SCORE)

    app_tracker = _tracker_mod.ApplicationTracker(jobs_dir / "applications.json")
    # Read once: the pipeline counts and the new matches are two views of the same postings.
    postings = selection.read_postings(jobs_dir)
    summary = selection.pipeline_summary(jobs_dir, app_tracker, min_score, postings=postings)
    breakdown = selection.ledger_breakdown(common._load_json_tolerant(jobs_dir / "applications.json"))
    ledger = {label: breakdown.get(label, 0) for label in _LEDGER_STATUSES}
    for label, count in breakdown.items():
        ledger.setdefault(label, count)

    interviews = _tracker_mod.interview_outcomes(app_tracker)
    application = _tracker_mod.application_outcomes(app_tracker)
    stages = {"application": application, **interviews} if any(application.values()) else interviews
    records = _load_run_records(jobs_dir)
    since = _since_last_review(
        jobs_dir, app_tracker, min_score, config.get("max_age_days", common._DEFAULT_MAX_AGE_DAYS), postings=postings,
        records=records,
    )
    return {
        "min_score": min_score,
        "pipeline": dict(summary),
        "ledger": ledger,
        "since_last_review": since,
        "interviews": interviews,
        "application": application,
        "pass_rates": {stage: _tracker_mod.pass_rate(counts) for stage, counts in stages.items()},
        "in_progress": _in_progress(jobs_dir),
        "employers": _employer_counts(profile_dir),
        "drive": _drive_block(),
        # the data folder holds jobs/: its logs/ (#593)
        "recurring_problem": recurring.check(jobs_dir.parent, records),
        "plan": _plan_block(jobs_dir, records),
        "cost": usage.cost(jobs_dir, records=records),
    }


def _plan_block(jobs_dir: Path, records: list[dict]) -> dict | None:
    """How full the Claude plan is and how many finds and prepares fit (`usage.room`), with
    this week's shares (`usage.week`); None before any call read the plan."""
    plan = usage.room(jobs_dir, records=records)
    if plan is not None:
        plan["week"] = usage.week(jobs_dir)
    return plan


def _drive_block() -> dict:
    """Whether Google Drive sync is on and how it last went (never the tokens)."""
    state = drive.read_state() or {}
    connected = bool(state.get("refresh_token"))
    return {
        "connected": connected,
        "account": state.get("account") if connected else None,
        "last_synced": state.get("last_synced") if connected else None,
        "last_error": state.get("last_error") if connected else None,
        # False in a build without the project's Google client: connecting cannot work there.
        "configured": drive.is_configured(),
    }


def _employer_counts(profile_dir: Path) -> dict:
    """How many employers of `profile_dir/companies.json` are in each status (all 0 when the list is
    missing or unreadable: `doctor` reports a broken file)."""
    try:
        items = companies.load(profile_dir)
    except companies.CompaniesError:
        items = []
    return {s: sum(1 for c in items if c.status == s) for s in companies.STATUSES}


def _in_progress(jobs_dir: Path) -> dict | None:
    """What a lock-holding run is doing right now, or None.

    Needs both a live lock and a `.progress.json` (a lock held for a quick
    status write has none); a file left by a crashed run is ignored because
    nobody holds the lock.
    """
    holder = lock.lock_holder(jobs_dir)
    snapshot = progress.read_progress(jobs_dir) if holder is not None else None
    if holder is None or snapshot is None:
        return None
    return {
        "purpose": holder.get("purpose"),
        "pid": holder.get("pid"),
        "started_at": holder.get("started_at"),
        "message": snapshot.get("message"),
        "done": snapshot.get("done"),
        "total": snapshot.get("total"),
        "site": snapshot.get("site"),
        "stage": snapshot.get("stage"),
        "updated_at": snapshot.get("updated_at"),
        "steps": snapshot.get("steps"),
    }


_BAR_WIDTH = 30
# Ledger statuses worth a colour when non-zero; the rest are plain.
_LEDGER_STYLES = {
    "applied": "cyan", **dict.fromkeys(_tracker_mod.INTERVIEW_STATUSES, "magenta"),
    "ghosted": "yellow", "offer": "bold green", "rejected": "red", "discarded": "dim",
}

_ROUND_STYLES = {"passed": "green", "rejected": "red", "ghosted": "yellow", "withdrawn": "dim"}


def _pass_rate_text(rate: dict):
    """``1/2 passed  50% (21–79%)``, or a dash until a round is decided."""
    from rich.text import Text

    if rate["rate"] is None:
        return Text("–", style="dim")
    return Text(f"{rate['passed']}/{rate['decided']} passed  {rate['rate']:.0%} "
                f"({rate['low'] * 100:.0f}–{rate['high']:.0%})")


def _segment_widths(counts: list[int], width: int) -> list[int]:
    """Split `width` cells over `counts` in proportion (largest remainder), at
    least one cell for every non-zero count."""
    total = sum(counts)
    if not total:
        return [0] * len(counts)
    exact = [c / total * width for c in counts]
    widths = [max(1, int(e)) if c else 0 for c, e in zip(counts, exact)]
    order = sorted(range(len(counts)), key=lambda i: exact[i] - int(exact[i]), reverse=True)
    i = 0
    while sum(widths) < width:
        if counts[order[i % len(order)]]:
            widths[order[i % len(order)]] += 1
        i += 1
    while sum(widths) > width:
        widest = max(range(len(widths)), key=lambda j: widths[j])
        widths[widest] -= 1
    return widths


def _stacked_bar(segments: list[tuple[int, str, str]]):
    """One bar of `_BAR_WIDTH` cells, a run of `glyph` in `style` per ``(count, glyph, style)``."""
    from rich.text import Text

    widths = _segment_widths([count for count, _, _ in segments], _BAR_WIDTH)
    return Text.assemble(*((glyph * w, style) for w, (_, glyph, style) in zip(widths, segments)))


def _legend(entries: list[tuple[str, str, int, str]]):
    """``█ label n   ▒ label n``: each entry's glyph in its colour, a zero dimmed."""
    from rich.text import Text

    parts: list = []
    for glyph, label, count, style in entries:
        if parts:
            parts.append("   ")
        parts += [(f"{glyph} ", style), (f"{label} ", "" if count else "dim"), (str(count), "bold" if count else "dim")]
    return Text.assemble(*parts)


def _print_pipeline_status() -> None:
    """Print the zero-arg `status` summary: a run in progress (if any), two
    stacked bars (all postings → applicable → above the threshold; the matches
    by ledger status), the ledger counts and what happened since the last review."""
    from rich.padding import Padding
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    result = _status_summary_core(workspace.JOBS_DIR, workspace.PROFILE_DIR)
    summary = result["pipeline"]
    threshold = f"≥ {result['min_score']:g}"
    console = common._console()

    live = result["in_progress"]
    if live is not None:
        started = common._local_time(live["started_at"]) if live.get("started_at") else "?"
        line = progress.Progress(live["message"], live["done"], live["total"], site=live["site"]).line.strip()
        body = Text.assemble(
            (f"In progress: {live['purpose']} (started {started}, pid {live['pid']})", "bold yellow"), "\n", line
        )
        console.print(Panel(body, border_style="yellow", padding=(0, 1)))

    total, applicable, above = summary["total"], summary["applicable"], summary["above_threshold"]
    common._section(console, f"Postings ({total})")
    console.print(Padding(_stacked_bar([
        (above, "█", "green"), (applicable - above, "▒", "cyan"), (total - applicable, "░", "dim"),
    ]), (0, 2)))
    console.print(Padding(_legend([
        ("█", threshold, above, "green"), ("▒", "applicable", applicable, "cyan"), ("░", "filtered out", total - applicable, "dim"),
    ]), (0, 2)))

    by_status = summary["above_threshold_by_status"]
    common._section(console, f"Matches {threshold} ({above} match{'' if above == 1 else 'es'})")
    if above:
        segments = [
            (by_status["unapplied"], "█", "yellow", "unapplied"),
            (by_status["prepared"], "▓", "blue", "prepared"),
            (by_status["applied"], "▒", "green", "applied"),
        ]
        if by_status["discarded"]:
            segments.append((by_status["discarded"], "░", "dim", "discarded"))
        console.print(Padding(_stacked_bar([(c, g, st) for c, g, st, _ in segments]), (0, 2)))
        console.print(Padding(_legend([(g, label, c, st) for c, g, st, label in segments]), (0, 2)))
    else:
        console.print(Padding(Text(f"No postings score {threshold} yet.", style="dim"), (0, 2)))

    common._section(console, "Applications")
    if any(result["ledger"].values()):
        ledger = Table.grid(padding=(0, 2))
        ledger.add_column(no_wrap=True)
        ledger.add_column(justify="right", no_wrap=True)
        for label in _LEDGER_STATUSES:
            count = result["ledger"][label]
            style = _LEDGER_STYLES.get(label, "") if count else "dim"
            ledger.add_row(Text(label, style=style), Text(str(count), style=f"bold {style}" if count else "dim"))
        console.print(Padding(ledger, (0, 2)))
    else:
        console.print(Padding(Text("No applications yet — `jobs status <company> applied` records one.", style="dim"), (0, 2)))

    if result["pass_rates"]:
        common._section(console, "Stages")
        rounds = Table.grid(padding=(0, 2))
        rounds.add_column(no_wrap=True)
        rounds.add_column(no_wrap=True)
        rounds.add_column()
        stages = {"application": result["application"], **result["interviews"]}
        for stage, rate in result["pass_rates"].items():
            line = Text()
            for label in _tracker_mod.ROUND_RESULTS:
                if stages[stage][label]:
                    if line:
                        line.append(", ")
                    line.append(f"{stages[stage][label]} {label}", style=_ROUND_STYLES.get(label, ""))
            rounds.add_row(stage, _pass_rate_text(rate), line)
        console.print(Padding(rounds, (0, 2)))
        console.print(Padding(Text("pass rate of the decided rounds (± one sigma, Wilson interval)", style="dim"), (0, 2)))

    employers = result["employers"]
    if any(employers.values()):
        common._section(console, "Employers")
        console.print(Padding(Text(", ".join(f"{n} {label}" for label, n in employers.items()), style=""), (0, 2)))

    if result["drive"]["connected"]:
        common._section(console, "Google Drive")
        line = f"synced as {result['drive']['account']}"
        if result["drive"]["last_synced"]:
            line += f", last {common._local_time(result['drive']['last_synced'])}"
        if result["drive"]["last_error"]:
            line += f" (last problem: {result['drive']['last_error']})"
        console.print(Padding(Text(line, style=""), (0, 2)))

    if result["plan"]:
        common._section(console, "Claude plan")
        console.print(Padding(Text(common._plan_line(result["plan"]),
                                   style="yellow" if result["plan"].get("warning") else ""), (0, 2)))

    if result["cost"]:
        _print_cost(console, result["cost"])

    _print_since_last_review(console, result["since_last_review"])


def _print_cost(console, cost: dict) -> None:
    from rich.padding import Padding
    from rich.table import Table
    from rich.text import Text

    common._section(console, f"Claude usage, last {cost['days']} days, at API prices")
    head, rows = common._cost_lines(cost)
    console.print(Padding(Text(head), (0, 2)))
    if rows:
        grid = Table.grid(padding=(0, 2))
        grid.add_column(no_wrap=True)
        grid.add_column(justify="right", no_wrap=True)
        grid.add_column(style="dim")
        for label, usd, did in rows:
            style = "dim" if label.startswith(" ") else ""
            grid.add_row(Text(label, style=style), Text(usd, style=style), did)
        console.print(Padding(grid, (0, 2)))
    console.print(Padding(Text("what the calls would cost on the API; your plan is not charged per call",
                               style="dim"), (0, 2)))


def _print_since_last_review(console, since: dict) -> None:
    from rich.padding import Padding
    from rich.table import Table
    from rich.text import Text

    reviewed = since["last_reviewed_at"]
    common._section(console, f"Since last review ({common._local_time(reviewed) if reviewed else 'never reviewed'})")
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", no_wrap=True)
    grid.add_column()
    grid.add_row("Runs", str(since["runs"]))
    new = since["new_matches"]
    grid.add_row(
        "Matches",
        Text(f"{new} new match{'' if new == 1 else 'es'} at or above min_score", style="bold green" if new else "dim"),
    )
    last = since["last_run"]
    if last is not None:
        when = common._local_time(last["started_at"])
        if last["failures"]:
            outcome = Text(f"✗ failed ({', '.join(last['failures'])})", style="red")
        else:
            outcome = Text(f"✓ {last['outcome']}", style="green")
        grid.add_row("Last run", Text.assemble(f"{when}  ", outcome))
    console.print(Padding(grid, (0, 2)))

    for failure in since["site_failures"]:
        flagged = failure["outcome"] == "empty"
        mark, style = ("⚠", "yellow") if flagged else ("✗", "red")
        detail = f": {failure['errors'][-1]}" if failure.get("errors") else ""
        console.print(
            Padding(Text.assemble((f"{mark} {failure['site']}", f"bold {style}"), (f" ({failure['outcome']}){detail}", style)), (0, 2))
        )


def _last_reviewed_at(jobs_dir: Path) -> str | None:
    """`jobs/last_review.json`'s timestamp, or None if never reviewed."""
    return common._load_json_tolerant(jobs_dir / "last_review.json").get("reviewed_at")


def _seen_since_review(jobs_dir: Path) -> frozenset[str]:
    """The job ids opened one by one since the last review (`mark_seen`): no longer new."""
    return frozenset(common._load_json_tolerant(jobs_dir / "last_review.json").get("seen") or ())


def _load_run_records(jobs_dir: Path) -> list[dict]:
    """Every `jobs/runs/<timestamp>.json` record, oldest first; unreadable ones skipped."""
    runs_dir = jobs_dir / "runs"
    if not runs_dir.is_dir():
        return []
    records = []
    for path in runs_dir.glob("*.json"):
        record = common._load_json_tolerant(path)
        if common._parse_iso(record.get("started_at")) is not None:
            records.append(record)
    records.sort(key=lambda r: common._parse_iso(r["started_at"]))
    return records


def _summarize_run(record: dict) -> dict:
    """A run record's headline: when, ok/failed, which sites/jobs failed, how many new."""
    match = record.get("match") or {}
    failures = list(record.get("failures") or [])
    return {
        "started_at": record.get("started_at"),
        "finished_at": record.get("finished_at"),
        "outcome": "failed" if failures else "ok",
        "failures": failures,
        "scraped": runs.postings_scraped(record),
        "scored": match.get("scored", 0),
        "new_above_threshold": len(record.get("new_above_threshold") or []),
    }


def _is_new_since(posting: dict, reviewed_at, seen: frozenset[str] = frozenset()) -> bool:
    """First seen (`scraped_at`) after the last review and not opened since (``seen``);
    everything not opened is new before the first review."""
    if posting.get("id") in seen:
        return False
    if reviewed_at is None:
        return True
    seen = common._parse_iso(posting.get("scraped_at"))
    return seen is None or seen > reviewed_at


def _since_last_review(
    jobs_dir: Path,
    app_tracker,
    min_score: float,
    max_age_days: int | None = common._DEFAULT_MAX_AGE_DAYS,
    postings: list[dict] | None = None,
    records: list[dict] | None = None,
) -> dict:
    """What happened since `jobs/last_review.json`: runs, new matches, site failures.

    Returns:
        ``{"last_reviewed_at", "runs": <runs finished since>, "last_run":
        <_summarize_run of the newest run> | None, "new_matches": <unapplied
        matches >= min_score first seen since>, "site_failures": [{"site",
        "outcome", "errors"}, ...]}`` — one entry per site that failed in a
        run since the review, from its latest failure. ``postings`` are the
        postings already read, when the caller has them; ``records`` the run records likewise.
    """
    from door.core import selection

    reviewed_iso = _last_reviewed_at(jobs_dir)
    reviewed_at = common._parse_iso(reviewed_iso)
    seen = _seen_since_review(jobs_dir)
    records = _load_run_records(jobs_dir) if records is None else records
    since = [
        r for r in records
        if reviewed_at is None or (common._parse_iso(r.get("finished_at")) or common._parse_iso(r["started_at"])) > reviewed_at
    ]

    failures: dict[str, dict] = {}
    for record in since:
        for entry in runs.site_entries(record):
            if entry.get("outcome") in ("error", "failed", "empty"):
                errors = entry.get("errors") or [m for m in (entry.get("error"), entry.get("warning")) if m]
                failures[entry["site"]] = {"site": entry["site"], "outcome": entry["outcome"], "errors": errors}

    matches = common._drop_stale(selection.select_matches(jobs_dir, app_tracker, min_score, postings=postings), max_age_days)
    return {
        "last_reviewed_at": reviewed_iso,
        "runs": len(since),
        "last_run": _summarize_run(records[-1]) if records else None,
        "new_matches": sum(1 for m in matches if _is_new_since(m, reviewed_at, seen)),
        "site_failures": list(failures.values()),
    }


@common._locked("mark_reviewed")
def _mark_reviewed_core(jobs_dir: Path | None = None) -> dict:
    """Stamp `jobs/last_review.json` with now: the end of a review session.

    `list --new` / `status_summary`'s ``since_last_review`` count from this
    moment; the ids `mark_seen` kept are dropped, the stamp covers them. Never prints.

    Returns:
        ``{"reviewed_at", "previous"}`` — ``previous`` is the stamp it
        replaced, or None.
    """
    from datetime import datetime, timezone

    if jobs_dir is None:
        jobs_dir = workspace.JOBS_DIR
    previous = _last_reviewed_at(jobs_dir)
    reviewed_at = datetime.now(timezone.utc).isoformat()
    utils.write_json_atomic(jobs_dir / "last_review.json", {"reviewed_at": reviewed_at})
    return {"reviewed_at": reviewed_at, "previous": previous}


@common._locked("mark_seen")
def _mark_seen_core(job_ref: str, jobs_dir: Path | None = None) -> dict:
    """One match opened: it is no longer new (`jobs/last_review.json`'s ``seen``).

    The desktop app calls it when a posting opens; the review stamp stays, so
    ``since_last_review``'s runs and site failures still count from it. Never prints.

    Returns:
        ``{"job_id"}``.
    """
    if jobs_dir is None:
        jobs_dir = workspace.JOBS_DIR
    job_id = common._resolve_job_ref(job_ref, jobs_dir)
    path = jobs_dir / "last_review.json"
    state = common._load_json_tolerant(path)
    seen = list(state.get("seen") or [])
    if job_id not in seen:
        seen.append(job_id)
    utils.write_json_atomic(path, {**state, "seen": seen})
    return {"job_id": job_id}
