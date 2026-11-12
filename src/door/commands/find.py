"""`find`: the batch entrypoint — five steps (search, discover, follow, collect, match), with run records.

`./door find` runs them in this order; `./door find <step>` (hidden from --help) runs one. Each step is a module of
`door.pipeline` with a core that returns a dict (its block of the run record); `_find_core`
composes them and writes `jobs/runs/<timestamp>.json` and a line of `jobs/runs/latest.log`.
"""

import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import click

from door import pipeline
from door.commands import _common as common
from door.commands import scrape as scrape_cmd
from door.core import discovery_sources, problem_log, runs, usage, utils, workspace
from door.core.sites import BOARDS
from door.pipeline import collect as collect_step
from door.pipeline import discover as discover_step
from door.pipeline import display
from door.pipeline import follow as follow_step
from door.pipeline import match as match_step
from door.pipeline import search as search_step

STEPS = pipeline.STEPS


def _run_record_filename(started_at: str) -> str:
    """Turn an ISO timestamp into a filesystem-safe `<...>.json` filename."""
    return re.sub(r"[^A-Za-z0-9_-]", "-", started_at) + ".json"


def _format_run_summary(record: dict, min_score: float) -> str:
    """Format the one-line summary shared by `find`'s stdout and `jobs/runs/latest.log`.

    e.g. ``2026-09-23T06:30 ok 41 scraped, 12 scored, 3 new >= 0.65, 0 failures, 4m12s; search: 41
    postings from 2 boards; follow: ...`` — the totals, then each step that ran with its own
    summary (plain ASCII ``>=``, so the log stays grep-friendly).
    """
    dt = datetime.fromisoformat(record["started_at"])
    ts = dt.strftime("%Y-%m-%dT%H:%M")
    new_count = len(record["new_above_threshold"])
    n_failures = len(record["failures"])
    status = "ok" if n_failures == 0 else "failed"
    elapsed = common._format_elapsed(record["elapsed_s"])

    line = (
        f"{ts} {status} {runs.postings_scraped(record)} scraped, {runs.scored(record)} scored, "
        f"{new_count} new >= {min_score:g}, {n_failures} failures, {elapsed}"
    )
    steps = [f"{name}: {record[name].get('summary', '')}" for name in STEPS if record.get(name)]
    if record.get("unsure_on"):  # the sources whose terms forbid automated access that the user turned on
        steps.append(f"unsure sources on: {', '.join(record['unsure_on'])}")
    return line + "; " + "; ".join(steps) if steps else line


def _write_run_record(record: dict, jobs_dir: Path, min_score: float) -> None:
    """Persist a `_find_core` record to `jobs_dir/runs/<started_at>.json` and
    append its one-line summary to `jobs_dir/runs/latest.log`; what failed in it goes to the problem log.

    The JSON write is atomic (`utils.write_json_atomic`).
    """
    runs_dir = jobs_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    record_path = runs_dir / _run_record_filename(record["started_at"])
    utils.write_json_atomic(record_path, record)

    log_line = _format_run_summary(record, min_score)
    with (runs_dir / "latest.log").open("a") as f:
        f.write(log_line + "\n")
    problem_log.run_record(record)


def _fold_late(first: dict, late: dict, *, lists=(), counts=(), keep=()) -> None:
    """Fold a late pass's block into the block of the step it repeats: lists concatenated, counts
    added, *keep* fields taken from the late one (the queue as it is now), and the summary
    extended (``... + late: ...``), so the record keeps its five blocks."""
    for key in lists:
        first[key] = list(first.get(key) or []) + list(late.get(key) or [])
    for key in counts:
        first[key] = (first.get(key) or 0) + (late.get(key) or 0)
    for key in keep:
        first[key] = late.get(key)
    first["late"] = {"summary": late["summary"], "elapsed_s": late.get("elapsed_s", 0.0)}
    first["summary"] = f"{first['summary']} + late: {late['summary']}"


def _failed_sites(record: dict) -> list[str]:
    """The sites of ``search`` and ``collect`` whose outcome was ``error`` or ``failed``."""
    return [e["site"] for e in runs.site_entries(record) if e.get("outcome") in ("error", "failed")]


@common._locked("run")
def _find_core(
    step: str | None = None,
    *,
    skip: list[str] | tuple[str, ...] = (),
    boards: list[str] | None = None,
    companies: list[str] | None = None,
    dry_run: bool = False,
    jobs_dir: Path | None = None,
    profile_dir: Path | None = None,
    progress=None,
) -> dict:
    """Run the pipeline — search, discover, follow, collect, match — or one step of it.

    The non-interactive, one-command entrypoint for a session or a script. Each step is a core
    of `door.pipeline` (see there for what it reads and writes); this runs the ones asked for,
    in order — except that in a full run discover starts first and works in the background
    (`door.pipeline.discover.begin`: its LinkedIn requests are minutes apart) while search,
    follow and collect run; when it is over (collect waits for it) the employers it queued get a
    short "late" follow and collect, folded into those steps' blocks (``late``). Boards are read
    since their last search (at most ``max_age_days`` back), employers' feeds for whatever is new
    to the history, and matches picked at the profile's ``min_score``. Writes a JSON record and
    appends a log line under `jobs_dir/runs/` before returning (see `_write_run_record`), except for
    ``follow`` as a dry run (it records nothing). Never prints.

    Args:
        step: Run just this step (one of `STEPS`); ``None`` runs them all, minus ``skip``.
        skip: Steps to leave out of a full run (their lines show as skipped).
        boards: ``search`` only: boards to search instead of every board of the profile's country.
        companies: ``collect`` only: collect just these followed employers.
        dry_run: ``follow`` only: detect, but record nothing.
        jobs_dir / profile_dir: Default to `workspace.JOBS_DIR` / `workspace.PROFILE_DIR`.
        progress: A `door.core.progress.Reporter` (or None). Every step reports itself
            (``stage="step"``) and its work to it; it is not passed to the cores.

    Returns:
        ``{"started_at", "finished_at", "elapsed_s", "steps": [steps that ran], "skipped":
        {step: reason}, "search", "discover", "follow", "collect", "match": <the step's block, or
        None when it did not run>, "new_above_threshold": [job_id, ...] (the matches this run scored), "top": [{"id",
        "score", "title", "company"}, ...] (top 10), "failures": [site_or_job_id, ...]}`` — the record written under jobs/runs/.

    Raises:
        ConfigError: `profile_dir/config.json` fails validation (issue #137), or the run would score against the example CV.
        FileNotFoundError: `profile_dir/config.json` is missing.
        ValueError: an unknown step, ``skip`` together with ``step``, an unknown board, or a company
            that is not followed.
    """
    jobs_dir = workspace.JOBS_DIR if jobs_dir is None else jobs_dir
    profile_dir = workspace.PROFILE_DIR if profile_dir is None else profile_dir
    skip = list(skip or ())
    for name in ([step] if step else []) + skip:
        if name not in STEPS:
            raise ValueError(f"unknown step {name!r}. Steps: {', '.join(STEPS)}")
    if step and skip:
        raise ValueError("skip leaves steps out of a full run; it cannot go with a single step")
    ran = [step] if step else [s for s in STEPS if s not in skip]
    if "match" in ran:  # before a run's minutes of reading, not at its end
        common._require_own_cv(common._load_config_or_defaults(profile_dir), profile_dir)

    config = common._load_config(profile_dir)
    min_score = config.get("min_score", common._DEFAULT_MIN_SCORE)
    started_at = datetime.now(timezone.utc).isoformat()
    start = time.monotonic()

    pipeline.plan([step] if step else STEPS)
    skipped = {}
    for name in STEPS:
        if not step and name in skip:
            skipped[name] = "--skip"
            pipeline.skipped(name, "--skip")

    where = {"jobs_dir": jobs_dir, "profile_dir": profile_dir}
    cores = {
        "search": lambda: search_step._search_core(boards=boards, **where),
        "discover": lambda: discover_step._discover_core(**where),
        "follow": lambda: follow_step._follow_core(dry_run=dry_run, **where),
        "collect": lambda: collect_step._collect_core(companies=companies, **where),
        "match": lambda: match_step._match_step_core(**where),
    }
    blocks = {name: None for name in STEPS}
    done: list[str] = []
    # In a full run discover works on a thread beside the others (LinkedIn is paced in minutes);
    # this thread writes every ledger, and settles it with `settle` once it is over.
    background = discover_step.begin(**where) if "discover" in ran and not step else None
    in_background = background is not None
    if background is not None and background.skipped:
        blocks["discover"], background = background.finish(), None
        skipped["discover"] = blocks["discover"]["skipped"]

    def settle() -> None:
        """Wait for discover, record what it found, then follow and collect the employers it queued
        after those steps ran ("late")."""
        nonlocal background
        handle, background = background, None
        blocks["discover"] = discover_block = handle.finish()
        if not discover_block["employers"]:
            return
        late_follow = None
        if "follow" in done:
            late_follow = follow_step._follow_core(dry_run=dry_run, late=True, **where)
            _fold_late(blocks["follow"], late_follow, lists=("followed", "unfollowable", "unresolved", "errors", "results"),
                       counts=("checked", "settled", "expired"), keep=("queued", "kept"))
        if "collect" in done and late_follow and late_follow["followed"] and not dry_run and not companies:
            late_collect = collect_step._collect_core(
                companies=[f["company"] for f in late_follow["followed"]], late=True, **where)
            _fold_late(blocks["collect"], late_collect, lists=("sites", "retired"),
                       counts=("employers", "postings", "failed", "non_local"))

    try:
        for name in ran:
            if name == "discover" and in_background:
                continue
            if background is not None and (name == "match" or (name == "follow" and background.ready())):
                settle()  # over already: follow will take its employers, no late pass needed
            blocks[name] = cores[name]()
            done.append(name)
            if blocks[name].get("skipped"):  # a discover that rested or was off: a skip, not a step that ran
                skipped[name] = blocks[name]["skipped"]
            if background is not None and (name == "collect" or (name == "follow" and background.ready())):
                settle()
        if background is not None:
            settle()
    finally:
        if background is not None:  # the run is ending early: stop LinkedIn, keep what it read
            background.cancel()
            try:
                blocks["discover"] = background.finish()
            except Exception:  # noqa: BLE001 - the run's own error is the one to report
                pass

    match_block = blocks["match"]
    matches_top = match_block["top"] if match_block else []

    record = {
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_s": time.monotonic() - start,
        "steps": [name for name in ran if name not in skipped],
        "skipped": skipped,
        **blocks,
        "new_above_threshold": match_block["new_above_threshold"] if match_block else [],
        "top": matches_top,
        "failures": [],
        "unsure_on": [s["label"] for s in discovery_sources.on(config)],
    }
    record["failures"] = _failed_sites(record) + (match_block["failed"] if match_block else [])

    if not (step == "follow" and dry_run):
        _write_run_record(record, jobs_dir, min_score)
    return record


# --------------------------------------------------------------------------- #
# The command
# --------------------------------------------------------------------------- #

def _render_top_matches(console, top: list[dict], total: int, min_score: float) -> None:
    """`find`'s top matches as a table like `jobs list`'s: score bar | title
    (English title) · company · location, then the job id on its own line."""
    from rich import box
    from rich.padding import Padding
    from rich.table import Table
    from rich.text import Text

    shown = f"top {len(top)} of {total}" if total > len(top) else f"{total} match{'' if total == 1 else 'es'}"
    console.print(Text.assemble(("  " + shown, "bold"), (f" ≥ {min_score:g}", "dim")))
    table = Table(box=box.SIMPLE_HEAD, header_style="dim", pad_edge=False, expand=True)
    table.add_column("Score", no_wrap=True)
    table.add_column("Posting", ratio=1)
    for entry in top:
        headline = Text(entry.get("title") or "", style="bold", no_wrap=True, overflow="ellipsis")
        if entry.get("title_en"):
            headline.append(f" ({entry['title_en']})", style="italic")
        headline.append(f" · {entry.get('company') or ''}", style="cyan")
        if entry.get("location"):
            headline.append(f" · {entry['location']}", style="dim")
        table.add_row(common._score_text(entry.get("score")), headline)
    console.print(Padding(table, (0, 1)))


def _render_ending(record: dict, min_score: float) -> None:
    """The end of a full run or `match` on a terminal, after the step lines: the Top matches
    table and what to run next — the look of `jobs show`, `jobs list` and `jobs add`."""
    from rich.text import Text

    console = common._console(max_width=common._LIST_MAX_WIDTH)
    top = record["top"]
    common._section(console, "Top matches")
    if top:
        _render_top_matches(console, top, len(record["new_above_threshold"]), min_score)
    else:
        common._mark_line(console, "info", Text(f"No matches at or above {min_score:g}.", style="dim"))

    steps = []
    if top:
        steps.append(("./door jobs show", "pick a match and read it in full"))
        steps.append(("./door jobs prepare", "tailor a CV and cover letter for the top match"))
    steps.append(("./door jobs list", "every match, best first" if top else "everything that scored above 0"))
    if any(e.get("outcome") in ("error", "failed", "empty") for e in runs.site_entries(record)):
        steps.append(("./door doctor --probe", "check the sites that failed or came back empty"))
    console.print()
    common._next_steps(console, steps)


def _stdout_is_tty() -> bool:
    """Return True if stdout looks like an interactive terminal.

    Delegates to `common._stdout_is_tty`; kept here as the seam `find`'s tests
    patch (`find` calls it by this name).
    """
    return common._stdout_is_tty()


def _csv(ctx, param, value: str | None) -> list[str] | None:
    return [x.strip() for x in value.split(",") if x.strip()] if value else None


_MARKS = {"followed": click.style("✓", fg="green"), "unfollowable": click.style("✗", fg="red"),
          "unresolved": click.style("?", fg="yellow")}


def _echo_follow_results(block: dict) -> None:
    """One line per employer `follow` checked: what it found (or would record)."""
    verb = "would record" if block["dry_run"] else "recorded"
    for row in block["results"]:
        if row["error"]:
            click.echo(f"{click.style('!', fg='yellow')} {row['company']}: failed - {row['error']}")
        elif row["status"] == "followed":
            click.echo(f"{_MARKS['followed']} {row['company']}: {row['platform']}:{row['entry']} ({verb})")
        else:
            click.echo(f"{_MARKS[row['status']]} {row['company']}: {row['status']} - {row['reason']} ({verb})")


def _echo_site_problems(record: dict) -> None:
    """One line per site that failed, errored, came back empty or was left alone, on stderr."""
    for entry in runs.site_entries(record):
        outcome = entry.get("outcome")
        if outcome in ("failed", "error", "empty"):
            click.echo(f"  {scrape_cmd._site_done_message(entry)}", err=True)
        elif outcome == "resting":
            click.echo(f"  {entry['site']}: resting after it pushed back; next try after "
                       f"{common._local_time(entry['until'])}.", err=True)
        elif outcome == "reserved":
            click.echo(f"  {entry['site']}: skipped - its terms reserve it against scraping ({entry['terms_url']}).", err=True)


def _execute(ctx: click.Context, step: str | None, **options) -> None:
    """Run `_find_core` for the command (a step, or all) and render the result. Exits with the code
    of `find`: 2 on a failed site, 1 when postings were left unscored."""
    group = ctx.find_object(dict) or {}
    if options.get("boards") is None:
        options["boards"] = group.get("boards")
    plain = not _stdout_is_tty()
    skip = group.get("skip") or []

    try:
        with display.steps_progress(tty=not plain) as reporter:
            record = _find_core(
                step, skip=skip, boards=options.get("boards"), companies=options.get("company"),
                dry_run=options.get("dry_run", False), jobs_dir=workspace.JOBS_DIR, profile_dir=workspace.PROFILE_DIR,
                progress=reporter,
            )
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    min_score = common._load_config_or_defaults(workspace.PROFILE_DIR).get("min_score", common._DEFAULT_MIN_SCORE)

    if record["follow"] and (record["follow"]["dry_run"] or (not plain and step == "follow")):
        _echo_follow_results(record["follow"])
    if not plain:
        _echo_site_problems(record)
        if record["match"]:
            _render_ending(record, min_score)
    if step is None and plain:
        click.echo(_format_run_summary(record, min_score))
    if (record["match"] or {}).get("scored"):
        plan_line = common._plan_use_line(usage.room(workspace.JOBS_DIR))
        if plan_line:
            click.echo(plan_line)

    match_failed = (record["match"] or {}).get("failed") or []
    if _failed_sites(record):
        sys.exit(2)
    if match_failed:
        click.echo(f"Failed to score {len(match_failed)} posting(s): {', '.join(match_failed)}", err=True)
        click.echo("Resume with: ./door find match (it scores what is left)", err=True)
        sys.exit(1)


@click.group("find", invoke_without_command=True, subcommand_metavar="")
@click.option("--boards", callback=_csv, default=None, metavar="BOARDS",
              help=f"Comma-separated boards to search instead of all of your country's (valid: {', '.join(BOARDS)}).")
@click.option("--skip", callback=_csv, default=None, metavar="STEPS",
              help=f"Comma-separated steps to leave out of the full run ({', '.join(STEPS)}).")
@click.pass_context
def find(ctx, boards, skip):
    """Fetch new jobs and score them against your profile.

    \b
    Runs five steps in order:
    search    every job board of your country (jobindex, thehub, arbetsformedlingen, francetravail, reed, workable, ...) with your keywords
    discover  LinkedIn, profession.hu, Jobbsafari, HelloWork: which employers hire for them (each skipped while it rests)
    follow    find each new employer's own job feed and record it (profile/companies.json)
    collect   every followed employer's feed
    match     filter, dedup, score with Haiku, pick the matches

    --skip leaves steps out (`--skip discover,collect`). On a terminal each step has a line
    (waiting, spinner with counts, done with its summary); into a pipe or a log file, one plain line
    as each step ends. Boards are read since your last search (at most max_age_days back),
    employers' feeds for whatever is new; matches are picked at your min_score.

    Every run writes a JSON record (one block per step) to jobs/runs/<timestamp>.json and
    appends a summary line to jobs/runs/latest.log.

    Exit codes: 0 on success; 2 if any site failed (outcome "error" or "failed"); 1 if
    postings were left unscored (run again to score them).
    """
    bad = [s for s in skip or [] if s not in STEPS]
    if bad:
        raise click.BadParameter(f"unknown step(s): {', '.join(bad)}. Steps: {', '.join(STEPS)}", param_hint="--skip")
    ctx.obj = {"boards": boards, "skip": skip}
    if ctx.invoked_subcommand is None:
        _execute(ctx, None)


# The single steps: hidden from --help (`./door find` is the command), kept for debugging a step.
@find.command("search", hidden=True)
@click.option("--boards", callback=_csv, default=None, metavar="BOARDS",
              help=f"Comma-separated boards to search instead of all of your country's (valid: {', '.join(BOARDS)}).")
@click.pass_context
def search_cmd(ctx, boards):
    """Step 1: search the job boards with your keywords; queue each posting's employer."""
    _execute(ctx, "search", boards=boards)


@find.command("discover", hidden=True)
@click.pass_context
def discover_cmd(ctx):
    """Step 2: LinkedIn shows which employers hire for your keywords; queue them."""
    _execute(ctx, "discover")


@find.command("follow", hidden=True)
@click.option("--dry-run", "dry_run", is_flag=True, default=False, help="Show what would be recorded; write nothing.")
@click.pass_context
def follow_cmd(ctx, dry_run):
    """Step 3: find the job feed of every queued employer and record it in profile/companies.json."""
    _execute(ctx, "follow", dry_run=dry_run)


@find.command("collect", hidden=True)
@click.option("--company", multiple=True, metavar="NAME", help="Collect just this followed employer (repeatable).")
@click.pass_context
def collect_cmd(ctx, company):
    """Step 4: read the job feed of every followed employer."""
    _execute(ctx, "collect", company=list(company) or None)


@find.command("match", hidden=True)
@click.pass_context
def match_cmd_(ctx):
    """Step 5: filter, dedup and score what the other steps wrote; pick the matches."""
    _execute(ctx, "match")

