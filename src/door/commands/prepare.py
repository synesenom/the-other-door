"""`prepare`: run the tailor agent for one posting (or the top match) and record it as prepared."""

import json
import shutil
import sys
from pathlib import Path

import click

import door.core.tracker as _tracker_mod
from door import i18n
from door.commands import _common as common
from door.commands import _progress
from door.commands import matches as matches_cmd
from door.commands import salary as salary_cmd
from door.core import claude_cli, usage, workspace
from door.core import photo as photo_mod
from door.core import progress as progress_mod
from door.core.lock import LockHeldError, ledger_lock
from door.core import utils
from door.matching import integrity
from door.tailoring import facts as facts_mod


_TAILOR_OUTPUTS = ("posting.json", "cv.tex", "cover_letter.tex", "cv.pdf", "cover_letter.pdf")
_DEFAULT_TAILOR_TIMEOUT_MIN = 20
# Seconds between "tailoring <id> · 3m20s elapsed" events while the (opaque)
# tailor run is going; read at call time so tests can shorten it.
_HEARTBEAT_INTERVAL_S = 30.0


def _tailor_outputs_missing(output_dir: Path) -> list[str]:
    """The tailor agent's output files (see `.claude/agents/tailor.md` → Output)
    that are absent or empty in `output_dir`, in contract order.

    An empty list means the materials are complete. A 0-byte file counts as
    missing (a half-written or failed compile).
    """
    output_dir = Path(output_dir)
    missing = []
    for name in _TAILOR_OUTPUTS:
        path = output_dir / name
        if not path.is_file() or path.stat().st_size == 0:
            missing.append(name)
    return missing


# Tools the tailor agent's steps use (#441): the reviewer sub-agent (Agent), the door MCP
# compile/render tool, and Read/Write scoped by path in `_tailor_args`. No Bash: the job
# ad is untrusted text, and an injected "run curl ..." must meet no shell. Under
# `claude -p`, a tool missing here is silently denied.
_TAILOR_ALLOWED_TOOLS = ("Agent", "mcp__door__compile")

# The file the tailor writes its new CARL stories to, in its output folder; `prepare`
# adds them to the story bank afterwards (the agent cannot write under the profile).
_STORIES_FILE = "stories.json"
# The `--agents` file `_run_tailor` writes beside the posting copy: the tailor and its reviewer.
_AGENTS_FILE = "agents.json"
_TAILOR_AGENTS = ("tailor", "reviewer")


def _rule_path(path) -> str:
    """`path` in the absolute form of Claude Code's permission rules: `//home/me/x`,
    and a Windows `C:\\Users\\me` as `//c/Users/me`."""
    posix = path.as_posix()
    drive = getattr(path, "drive", "")
    if drive:
        posix = "/" + drive.rstrip(":").lower() + posix[len(drive):]
    return "/" + posix


def _tailor_read_files(profile_dir: Path) -> list[Path]:
    """The CV and templates the profile names, when they live outside the profile folder."""
    try:
        config = common._load_config_or_defaults(profile_dir)
    except Exception:  # noqa: BLE001 - an invalid config fails the run on its own; the rules stay narrow
        config = {}
    files = [common._cv_path(config, profile_dir)]
    for key in ("cv_template", "cover_letter_template"):
        if config.get(key):
            path = Path(config[key])
            files.append(path if path.is_absolute() else workspace.HOME / path)
    profile = profile_dir.absolute()
    return [f.absolute() for f in files if not f.absolute().is_relative_to(profile)]


def _tailor_tools(job_id: str, posting_path: Path) -> list[str]:
    """`_TAILOR_ALLOWED_TOOLS` plus the path rules: Read the profile, the posting and the
    job's own output folder (where `compile` puts the page images); write only there."""
    profile_dir = workspace.PROFILE_DIR
    output_dir = (workspace.JOBS_DIR / "output" / job_id).absolute()
    reads = [
        f"Read({_rule_path(profile_dir.absolute())}/**)",
        f"Read({_rule_path(Path(posting_path).absolute())})",
        f"Read({_rule_path(output_dir)}/**)",
        *(f"Read({_rule_path(f)})" for f in _tailor_read_files(profile_dir)),
    ]
    # Claude Code never matches `Write(path)` rules; `Edit(path)` covers every file-writing tool.
    writes = [f"Edit({_rule_path(output_dir)}/**)"]
    return [*_TAILOR_ALLOWED_TOOLS, *reads, *writes]


def _agent_definition(name: str) -> dict:
    """`.claude/agents/<name>.md` as an `--agents` entry: its frontmatter's description,
    model and tools, and its body as the prompt."""
    text = (workspace.REPO_ROOT / ".claude" / "agents" / f"{name}.md").read_text(encoding="utf-8")
    _, front, body = text.split("---", 2)
    entry: dict = {"prompt": body.strip()}
    key = None
    for line in front.splitlines():
        if line.lstrip().startswith("- ") and key == "tools":
            entry["tools"].append(line.strip()[2:].strip())
        elif ":" in line and not line.startswith(" "):
            key, value = (part.strip() for part in line.split(":", 1))
            if key == "tools":
                entry["tools"] = []
            elif key in ("description", "model"):
                entry[key] = value
    return entry


def _tailor_folders(posting_path: Path) -> list[Path]:
    """The folders the tailor session works in besides its output folder (its working
    directory): the profile, the posting's own folder, and the folder of a CV or template
    kept outside the profile."""
    folders = [workspace.PROFILE_DIR, Path(posting_path).parent]
    folders += [f.parent for f in _tailor_read_files(workspace.PROFILE_DIR)]
    return list(dict.fromkeys(Path(f).absolute() for f in folders))


def _cv_conventions_text(posting_path: Path) -> str:
    """The country's CV conventions as the tailor reads them (`.claude/agents/tailor.md` → CV conventions): the
    posting's country, else the profile's (`common._cv_country`), else the neutral default."""
    try:
        posting = json.loads(Path(posting_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        posting = {}
    try:
        config = common._load_config_or_defaults(workspace.PROFILE_DIR)
    except Exception:  # noqa: BLE001 - an invalid config fails the run on its own
        config = {}
    country = common._cv_country(posting, config)
    cv = country.cv if country else i18n.CvConventions()
    photo = config.get("photo")
    has_photo = bool(photo) and photo_mod.problem(Path(photo) if Path(photo).is_absolute() else workspace.HOME / photo) is None
    return (
        f"CV conventions for this job's country ({country.code if country else 'no country file'}): "
        f"photo: {cv.photo}; the profile has a photo: {'yes' if has_photo else 'no'}; "
        f"{'a date of birth is usual there' if cv.date_of_birth else 'no date of birth is expected there'}, but never add a date of birth: keep one only if cv.md already has it; "
        f"at most {cv.max_pages} pages; a full date is written {cv.date_format}."
    )


def _tailor_args(job_id: str, posting_path: Path) -> list[str]:
    """The `claude -p` arguments that run the tailor agent for one posting.

    The session runs in the job's output folder (`_run_tailor`), not the checkout, in
    `--restricted` mode: no tool that runs commands, file tools confined to the working
    directories (that folder and `_tailor_folders`), no project or user settings. The
    tailor and reviewer agents come from `--agents` (the `.claude/agents/` files), the
    door server from `--mcp-config` alone.
    """
    output_dir = workspace.JOBS_DIR / "output" / job_id
    prompt = (
        f"Tailor job_id {job_id!r}: `job` is the posting at {posting_path}, `profile` is "
        f"{workspace.PROFILE_DIR / 'config.json'} (the profile folder is {workspace.PROFILE_DIR}; "
        f"the story bank is {workspace.PROFILE_DIR / 'story_bank.md'}). Produce "
        f"{output_dir}/posting.json, cv.tex and "
        f"cover_letter.tex and compile them to PDFs, following your steps in order; "
        f"new stories go to {output_dir / _STORIES_FILE}. "
        f"{_cv_conventions_text(posting_path)} "
        f"Use these absolute paths, not paths relative to the working directory."
    )
    argv = [
        prompt,
        "--restricted",
        "--agents", str(Path(posting_path).parent / _AGENTS_FILE),
        "--agent", "tailor",
        "--allowedTools", ",".join(_tailor_tools(job_id, posting_path)),
        "--mcp-config", json.dumps(workspace.mcp_config_entry()),
        "--strict-mcp-config",
        *claude_cli.STREAM_ARGS,  # the stream carries the run's usage and the plan's limits (#575)
    ]
    for folder in _tailor_folders(posting_path):
        argv += ["--add-dir", str(folder)]
    return argv


def _add_stories(output_dir: Path, profile_dir: Path) -> dict:
    """Add the stories the tailor wrote to `output_dir/stories.json` to the profile's
    story bank (`StoryBank` dedups by title), then remove the file.

    Returns ``{"added", "present", "skipped": [line, ...]}``: a story that is not an
    object with every field a non-empty string is skipped with a line saying why.
    """
    from door.tailoring import StoryBank, _REQUIRED_FIELDS

    summary = {"added": 0, "present": 0, "skipped": []}
    path = Path(output_dir) / _STORIES_FILE
    if not path.is_file():
        return summary
    try:
        stories = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        summary["skipped"].append(f"{_STORIES_FILE} could not be read: {exc}")
        stories = []
    if not isinstance(stories, list):
        summary["skipped"].append(f"{_STORIES_FILE} is not a list of stories")
        stories = []
    valid = []
    for i, story in enumerate(stories, 1):
        if not isinstance(story, dict):
            summary["skipped"].append(f"story {i}: not an object")
            continue
        bad = [f for f in _REQUIRED_FIELDS if not isinstance(story.get(f), str) or not story[f].strip()]
        if bad:
            summary["skipped"].append(f"story {i} ({str(story.get('title') or 'untitled')[:60]}): missing or empty {', '.join(bad)}")
            continue
        valid.append({f: story[f].strip() for f in _REQUIRED_FIELDS})
    if valid:
        bank = StoryBank(Path(profile_dir) / "story_bank.md")
        before = len(bank.stories)
        for story in valid:
            bank.append(story)
        summary["added"] = len(bank.stories) - before
        summary["present"] = len(valid) - summary["added"]
        if summary["added"]:
            bank.save()
    path.unlink(missing_ok=True)
    return summary


class TailorError(claude_cli.ClaudeError):
    """The `claude -p` tailor run failed (non-zero exit, timeout, or no `claude`)."""


def _run_tailor(job_id: str, posting_path: Path, timeout_s: float | None = None) -> bool:
    """Drive the tailor agent for a single posting via the `claude` CLI.

    `claude -p "<prompt>" --agent tailor ...` (`_tailor_args`) in headless/print mode from
    the job's output folder, never the checkout (#441): `--agent tailor` runs the session *as* the tailor agent — one fewer layer
    than asking a default session to delegate to it — and `--mcp-config`
    gives it the door `compile` tool (which also renders the pages). `timeout_s` bounds a hung
    agent (issue #135). This is the seam tests monkeypatch instead of mocking
    subprocess directly, since the real tailoring logic is out of scope for
    this command (see issue #72).

    Returning True only means `claude` exited 0 — callers must still check
    `_tailor_outputs_missing` before recording the job as prepared.

    Raises:
        TailorError: non-zero exit (message includes `claude`'s stderr),
            timeout, or the `claude` binary could not be started.
    """
    try:
        workspace.ensure_mcp_config()   # a custom DOOR_HOME gets a .mcp.json for this interpreter
    except RuntimeError as exc:
        raise TailorError(str(exc)) from None
    output_dir = workspace.JOBS_DIR / "output" / job_id
    output_dir.mkdir(parents=True, exist_ok=True)  # the session's working directory
    try:
        agents = {name: _agent_definition(name) for name in _TAILOR_AGENTS}
        (Path(posting_path).parent / _AGENTS_FILE).write_text(json.dumps(agents), encoding="utf-8")
    except (OSError, ValueError) as exc:
        raise TailorError(f"cannot set up the tailor agents: {exc}") from None
    try:
        claude_cli.run(_tailor_args(job_id, posting_path), feature="tailoring", timeout_s=timeout_s, cwd=output_dir)
    except claude_cli.ClaudeError as exc:
        raise TailorError(str(exc)) from None
    return True


def _step(message: str, outcome: str | None = None) -> None:
    """One of `prepare`'s steps: running (no ``outcome``), or done ("ok"/"failed")."""
    progress_mod.report(message, stage="prepare", outcome=outcome)


# The plan's states that leave no room for an estimate nobody asked for (`usage.room`'s `status`).
_PLAN_FULL = ("allowed_warning", "rejected")


def _estimate_salary(job_id: str, jobs_dir: Path, profile_dir: Path) -> dict | None:
    """The salary estimate of a job just prepared (#624): the cached one while younger than
    `salary.STALE_AFTER_DAYS`, else one Haiku web search. Only shown to the user, never handed to the
    tailor. None, and nothing said, when no source was found, the call failed, or the plan is close
    to its limit (`usage.room`): an estimate is never worth a failed prepare or a spent plan."""
    try:
        plan = usage.room(jobs_dir)
    except Exception:  # noqa: BLE001 - a reading that fails is no reason to skip, nor to fail
        plan = None
    if plan and plan.get("status") in _PLAN_FULL:
        return None
    progress_mod.report("estimating the salary", stage="prepare")
    try:
        result = salary_cmd._salary_core(job_id, max_age_days=salary_cmd.STALE_AFTER_DAYS,
                                         jobs_dir=jobs_dir, profile_dir=profile_dir)
    except Exception:  # noqa: BLE001 - the materials are ready; a missing estimate is said nowhere
        result = None
    _step("salary estimate done", "ok")
    return result if result and result.get("found") else None


@common._with_progress
def _prepare_core(
    job_id: str | None = None,
    force: bool = False,
    timeout_s: float | None = _DEFAULT_TAILOR_TIMEOUT_MIN * 60,
    jobs_dir: Path | None = None,
    *,
    profile_dir: Path | None = None,
    progress=None,
) -> dict:
    """Tailor materials for one posting and advance its status to `prepared`.

    ``job_id`` None means the single highest-scoring unapplied match, resolved
    in `jobs list` order ("selecting top match" is reported first).

    Idempotent: complete materials in `jobs/output/<job_id>/` are skipped
    unless `force`; an incomplete directory is regenerated. The ledger only
    records `prepared` once every file in `_TAILOR_OUTPUTS` is on disk and
    non-empty (issue #135). Never prints; ``progress`` (a
    `door.core.progress.Reporter` or None) receives each step (stage
    ``"prepare"``) as it starts and, with an ``outcome``, as it ends: the
    top match picked, the tailor run, the outputs verified, the status
    recorded; plus an elapsed-time heartbeat every `_HEARTBEAT_INTERVAL_S`
    while the tailor agent runs.

    Returns:
        ``{"job_id": None, "outcome": "no_matches"}`` when no job_id was
        given and nothing clears min_score; else
        ``{"job_id", "outcome": "prepared" | "skipped" | "failed",
        "output_dir", "files": [name, ...], "regenerated_incomplete",
        "error"?, "missing"?, "unsupported"?, "stories"?, "salary"?}`` — ``salary`` (a prepared
        job only) is `_estimate_salary`'s estimate or None; ``stories`` is
        `_add_stories`'s count of the CARL stories added to the story bank; ``files`` lists the material files present
        afterwards; ``missing`` is set when the tailor run finished without
        writing all of them.

    Raises:
        ValueError: `job_id` is not a valid slug.
        LookupError: no posting with that id.
    """
    from door.core.selection import find_posting_path

    if jobs_dir is None:
        jobs_dir = workspace.JOBS_DIR
    home = workspace.PROFILE_DIR if profile_dir is None else profile_dir
    if common._cv_is_example(common._load_config_or_defaults(home), home):
        return {"job_id": job_id, "outcome": "failed", "error": common.EXAMPLE_CV_MESSAGE}
    if job_id is None:
        if not common._claude_available():
            return {"job_id": None, "outcome": "failed", "error": f"the `claude` CLI is not installed — {common._CLAUDE_FIX}."}
        job_id = _top_match_id(jobs_dir, profile_dir)
        if job_id is None:
            return {"job_id": None, "outcome": "no_matches"}
        _step(f"top match: {common._job_label(job_id, jobs_dir)}", "ok")
    job_id = common._resolve_job_ref(job_id, jobs_dir)

    posting_path = find_posting_path(jobs_dir, job_id)
    if posting_path is None:
        raise LookupError(f"no posting found for job_id {job_id!r}")

    try:  # a posting stored before the gate is cleaned on disk before the tailor reads the file
        stored = json.loads(posting_path.read_text(encoding="utf-8"))
        if integrity.ensure(stored):
            utils.write_json_atomic(posting_path, stored)
    except (OSError, ValueError):
        pass

    output_dir = jobs_dir / "output" / job_id
    result = {
        "job_id": job_id,
        "outcome": "failed",
        "output_dir": str(output_dir),
        "files": [],
        "regenerated_incomplete": False,
    }

    # Refuse up front rather than spend a tailor run's quota and then fail to
    # record it. A lock this thread already holds is fine.
    from door.core.lock import _describe, _held_depth, lock_holder

    holder = None if _held_depth(jobs_dir) else lock_holder(jobs_dir)
    if holder is not None:
        return {**result, "error": _describe(holder)}

    def _present() -> list[str]:
        missing = set(_tailor_outputs_missing(output_dir))
        return [name for name in _TAILOR_OUTPUTS if name not in missing]

    if output_dir.exists() and not force:
        if not _tailor_outputs_missing(output_dir):
            return {**result, "outcome": "skipped", "files": _present()}
        result["regenerated_incomplete"] = True

    if not common._claude_available():
        return {**result, "error": f"the `claude` CLI is not installed — {common._CLAUDE_FIX}; status left unchanged."}

    label = common._job_label(job_id, jobs_dir)
    progress_mod.report(f"tailoring {label}", stage="prepare")
    tailor_dir = jobs_dir / ".tailor" / job_id  # the posting copy and agents file; the tailor sees only this of jobs/
    model_copy = tailor_dir / "posting.json"  # no excerpts of removed text: the tailor reads this
    (output_dir / _STORIES_FILE).unlink(missing_ok=True)  # never stories of an earlier run
    try:
        with progress_mod.heartbeat(f"tailoring {label}", stage="prepare", interval_s=_HEARTBEAT_INTERVAL_S):
            utils.write_json_atomic(model_copy, integrity.for_model(json.loads(posting_path.read_text(encoding="utf-8"))))
            _run_tailor(job_id, model_copy, timeout_s=timeout_s)
    except TailorError as exc:
        _step("tailoring failed", "failed")
        return {
            **result,
            "files": _present(),
            "error": f"tailor step failed for {job_id!r}: {exc}; status left unchanged.",
        }
    finally:
        shutil.rmtree(tailor_dir, ignore_errors=True)

    _step("tailored the CV and cover letter", "ok")
    _step(f"verifying outputs for {label}")
    missing = _tailor_outputs_missing(output_dir)
    if missing:
        _step(f"missing {', '.join(missing)}", "failed")
        return {
            **result,
            "files": _present(),
            "missing": missing,
            "error": (
                f"tailor step finished but jobs/output/{job_id}/ is missing: "
                f"{', '.join(missing)}; status left unchanged."
            ),
        }

    _step("CV, cover letter and both PDFs on disk", "ok")
    # Reported, never a block: figures, employers, skills, certifications and degrees cv.md and the story bank do not back (#325, #369).
    unsupported = facts_mod.check(output_dir, profile_dir or workspace.PROFILE_DIR)
    # After the check: stories written this run must not back the run's own figures.
    stories = _add_stories(output_dir, profile_dir or workspace.PROFILE_DIR)
    try:
        with ledger_lock(jobs_dir, "prepare"):
            app_tracker = _tracker_mod.ApplicationTracker(jobs_dir / "applications.json")
            app_tracker.advance(job_id, "prepared")
            app_tracker.save()
    except (ValueError, LockHeldError) as exc:  # ValueError includes DuplicateApplicationError
        _step("could not record the status", "failed")
        return {
            **result,
            "files": _present(),
            "error": f"materials are ready but the status could not be recorded: {exc}",
        }

    _step("status set to prepared", "ok")
    estimate = _estimate_salary(job_id, jobs_dir, profile_dir or workspace.PROFILE_DIR)
    return {**result, "outcome": "prepared", "files": _present(), "unsupported": unsupported, "stories": stories,
            "salary": estimate}


def _top_match_id(jobs_dir: Path, profile_dir: Path | None = None) -> str | None:
    """The id of the highest-scoring unapplied match (in `jobs list` order), or None."""
    from door.core.selection import select_matches

    if profile_dir is None:
        profile_dir = workspace.PROFILE_DIR
    progress_mod.report("selecting top match", stage="prepare")
    config = common._load_config_or_defaults(profile_dir)
    min_score = config.get("min_score", common._DEFAULT_MIN_SCORE)
    app_tracker = _tracker_mod.ApplicationTracker(jobs_dir / "applications.json")
    matches = common._drop_stale(select_matches(jobs_dir, app_tracker, min_score), config.get("max_age_days", common._DEFAULT_MAX_AGE_DAYS))
    return matches[0]["id"] if matches else None


def _render_prepared(result: dict, *, interactive: bool) -> None:
    """A finished (or skipped) `_prepare_core` result: what happened as a ✓/⚠
    line, `show`'s card for the posting (without the ad itself), the materials
    summary and what to do next."""
    from door.core.selection import find_posting

    job_id = result["job_id"]
    output_dir = Path(result["output_dir"])
    where = common._display_path(output_dir)
    console = common._console()
    if interactive:
        console.print()
    if result["outcome"] == "skipped":
        common._mark_line(console, "warn", f"materials already in [bold]{where}[/] — not regenerated (pass --force to redo them)")
    else:
        if result.get("regenerated_incomplete"):
            common._mark_line(console, "warn", f"incomplete materials found in [bold]{where}[/] — regenerated")
        if not interactive:  # on a terminal the step lines above already said so
            common._mark_line(console, "ok", "Tailored materials ready; status set to [bold]prepared[/]")
    console.print()

    posting = find_posting(workspace.JOBS_DIR, job_id)
    if posting is not None:
        posting = {**posting, "salary": result.get("salary") or salary_cmd.cached(job_id, workspace.JOBS_DIR)}
        status = _tracker_mod.ApplicationTracker(workspace.JOBS_DIR / "applications.json").get_status(job_id) or "unapplied"
        matches_cmd._render_posting_detail(posting, status, console, description=False)
    try:
        materials = matches_cmd._materials(output_dir)
    except Exception as exc:  # noqa: BLE001 - page counts/PNGs are a summary; the files are there
        console.print()
        common._mark_line(console, "warn", f"could not summarise the materials ({exc}); they are in [bold]{where}[/]")
    else:
        if materials is not None:
            matches_cmd._render_materials(materials, console)
    console.print()
    words = common.job_words(posting or {"id": job_id}, workspace.JOBS_DIR)
    common._next_steps(console, [
        (f"./door jobs show {words} --open", "open the CV and cover letter"),
        (f"./door jobs status {words} applied", "once you've sent the application"),
    ])


_timeout_option = click.option(
    "--timeout",
    "timeout_min",
    type=click.FloatRange(min=0, min_open=True),
    default=_DEFAULT_TAILOR_TIMEOUT_MIN,
    show_default=True,
    help="Minutes to wait for the tailor agent before giving up.",
)


@click.command()
@click.argument("job_id", metavar="JOB", required=False, default=None)
@click.option("--force", is_flag=True, default=False, help="Regenerate materials even if jobs/output/<job_id>/ already exists.")
@_timeout_option
def prepare(job_id: str | None, force: bool, timeout_min: float):
    """Generate tailored CV/cover-letter materials for JOB and mark it 'prepared'.

    JOB is words from its company and title (`trustpilot`, "novonesis head of ai";
    several matches are picked from) or its id; without it, the single
    highest-scoring unapplied match (in `jobs list` order).
    Locates the posting, invokes the tailor flow, and on success advances
    its application status to 'prepared' — but only once cv.tex,
    cover_letter.tex, both PDFs and posting.json are all on disk. Idempotent
    by default — skips work if jobs/output/<job_id>/ already holds complete
    materials (an incomplete directory is regenerated); pass --force to
    regenerate anyway.
    """
    interactive = common._stdout_is_tty()
    try:
        if job_id is not None:
            job_id = common._job_ref_cli(job_id, workspace.JOBS_DIR)
        room_line = common._prepare_room_line(usage.room(workspace.JOBS_DIR))
        if room_line:
            click.echo(room_line)
        with _progress.live_progress(enabled=interactive) as reporter:
            result = _prepare_core(
                job_id, force, timeout_min * 60, jobs_dir=workspace.JOBS_DIR,
                profile_dir=workspace.PROFILE_DIR, progress=reporter,
            )
    except (ValueError, LookupError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if result["outcome"] == "no_matches":
        click.echo("No matches found — `./door find` first.")
        return
    if result["outcome"] not in ("prepared", "skipped"):
        click.echo(f"Error: {result['error']}", err=True)
        sys.exit(1)
    _render_prepared(result, interactive=interactive)
