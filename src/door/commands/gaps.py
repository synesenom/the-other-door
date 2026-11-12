"""`skill-gaps`: a prioritised, WebSearch-cited learning plan for the gaps between
the CV and a target role or some matches, written to `upskill/report-<date>.md`.

One `claude -p` call does the analysis and the searching; `/upskill` in a
conversation and `skill-gaps` in a shell make the same call.
"""

import re
import sys
from datetime import date
from pathlib import Path

import click

from door.commands import _common as common
from door.commands import _progress
from door.commands import matches as matches_cmd
from door.core import claude_cli, workspace
from door.core import progress as progress_mod
from door.matching import integrity

_DEFAULT_MODEL = "sonnet"

_RULES = """You write a skill-gap analysis and learning plan for a job seeker. You get their CV and one or more targets (a role name, or job postings). Work in this order and write the report in Markdown, nothing else.

Pass 1 — Hard-skill gaps: the explicit and implicit requirements of the targets (tools and software, methods, domain knowledge, licences and named certifications, languages) that the CV does not show, each with the target that requires it.

Pass 2 — Synthesised gaps: what a keyword diff misses — soft skills, domain depth (knowing a method vs. having led it: bookkeeping vs. running a year-end close), tooling maturity (using a system vs. running it: entering orders in an ERP vs. configuring it), credentials that would strengthen the application, and experience the CV mentions but does not evidence with outcomes — each with why it matters for the targets.

Resources: for each gap, use WebSearch to find real, credible learning resources (a course, a study guide, a book, documentation). Never invent URLs, course titles, platforms or resource names: cite only what WebSearch returned. A gap with no credible result goes under "Skipped gaps" as "No vetted resource found — manual research recommended."

Plan: order the gaps by impact — hard skills explicitly required first, then domain and tooling maturity, then certifications, then soft skills and portfolio evidence.

Report structure (use the date you are given):

# Upskill Plan — YYYY-MM-DD

## Target role(s)
<the roles or postings analysed>

## Pass 1 — Hard-skill gaps

| Gap | Source | Priority |
|-----|--------|----------|

## Pass 2 — Synthesised gaps

| Gap | Why it matters | Priority |
|-----|---------------|----------|

## Prioritized learning plan

### 1. <Gap name> (Priority: High)
**Why**: <one sentence on impact>
**Resources**:
- [<Resource name>](<URL from WebSearch>) — <why it helps>

### 2. ...

## Skipped gaps
<gaps with no vetted resource, or "none">
"""

_PLAN_ITEM_RE = re.compile(r"^### \d+\.", re.MULTILINE)


def _today() -> str:
    return date.today().isoformat()


def _resolve_targets(targets: list[str], top: int | None, *, jobs_dir: Path, profile_dir: Path,
                     jobs: list[str] | None = None) -> list[dict]:
    """Each role name in *targets* as ``{"kind": "role", "label"}``, and each job in *jobs* (words
    from its company and title, or its id) and each of the top N matches as
    ``{"kind": "posting", "label", "job_id", "posting"}``."""
    from door.core.selection import find_posting

    resolved = []

    def add_posting(ref: str) -> None:
        job_id = common._resolve_job_ref(ref, jobs_dir)
        posting = find_posting(jobs_dir, job_id)
        if posting is None:
            raise LookupError(f"no posting found for job_id {job_id!r}")
        integrity.ensure(posting)  # a posting stored before the gate: clean in memory
        resolved.append({
            "kind": "posting",
            "label": f"{posting.get('title', '')} — {posting.get('company', '')}",
            "job_id": job_id,
            "posting": posting,
        })

    for item in [t.strip() for t in targets or [] if t and t.strip()]:
        resolved.append({"kind": "role", "label": item})
    for ref in [j.strip() for j in jobs or [] if j and j.strip()]:
        add_posting(ref)
    if top:
        listed = matches_cmd._list_core(limit=top, jobs_dir=jobs_dir, profile_dir=profile_dir)["matches"]
        for match in listed:
            if not any(t.get("job_id") == match["id"] for t in resolved):
                add_posting(match["id"])
    if not resolved:
        raise ValueError("nothing to analyse: give a role name, a job (`--job trustpilot`), or top N")
    return resolved


def _target_text(target: dict) -> str:
    if target["kind"] == "role":
        return f"Role: {target['label']}"
    posting = target["posting"]
    return (
        f"Posting: {posting.get('title', '')} at {posting.get('company', '')} ({posting.get('location', '')})\n"
        f"{posting.get('description', '')}"
    )


@common._with_progress
def _skill_gaps_core(
    targets: list[str] | None = None,
    *,
    jobs: list[str] | None = None,
    top: int | None = None,
    model: str | None = None,
    profile_dir: Path | None = None,
    jobs_dir: Path | None = None,
    timeout_s: float = 900,
    progress=None,
) -> dict:
    """Write `upskill/report-<today>.md` for `targets` (role names), `jobs` (postings:
    words from the company and title, or ids) and/or the `top` N matches, with one
    `claude -p` call that may use WebSearch. Never prints: the call is reported to ``progress``
    (stage ``"gaps"``) as it starts and, with an ``outcome``, as it ends.

    Returns:
        ``{"report_path", "report" (its Markdown), "targets": [{"kind", "label", "job_id"?}], "plan_items"}``.

    Raises:
        FileNotFoundError, ConfigError: no or invalid profile/config.json; no CV.
        ValueError: no target, or a job reference that matches no job or several
            (`AmbiguousJobRef`).
        claude_cli.ClaudeError: the `claude -p` call failed or returned nothing.
    """
    if profile_dir is None:
        profile_dir = workspace.PROFILE_DIR
    if jobs_dir is None:
        jobs_dir = workspace.JOBS_DIR
    config = common._load_config(profile_dir)
    cv_path = common._cv_path(config, profile_dir)
    if not cv_path.is_file():
        raise FileNotFoundError(f"{cv_path} not found (profile/cv.md): set up the profile first")
    resolved = _resolve_targets(targets or [], top, jobs_dir=jobs_dir, profile_dir=profile_dir, jobs=jobs)

    today = _today()
    prompt = (
        f"Date: {today}\n\n"
        f"CV (profile/cv.md):\n<<<\n{cv_path.read_text(encoding='utf-8')}\n>>>\n\n"
        "Targets:\n\n" + "\n\n".join(_target_text(t) for t in resolved) + "\n"
    )
    model = model or _DEFAULT_MODEL
    progress_mod.report(f"analysing {len(resolved)} target(s) with {model} and WebSearch (minutes)", stage="gaps")
    try:
        report = claude_cli.ask(
            _RULES, prompt, model=model, feature="skill_gaps", allowed_tools=("WebSearch",),
            timeout_s=timeout_s, profile_dir=profile_dir,
        )
        if not report:
            raise claude_cli.ClaudeError("claude returned an empty report")
    except claude_cli.ClaudeError:
        progress_mod.report("the analysis failed", stage="gaps", outcome="failed")
        raise
    progress_mod.report(f"analysed {len(resolved)} target(s)", stage="gaps", outcome="ok")

    out_dir = workspace.UPSKILL_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"report-{today}.md"
    report_path.write_text(report + "\n", encoding="utf-8")
    return {
        "report_path": str(report_path),
        "report": report + "\n",
        "targets": [{k: v for k, v in t.items() if k != "posting"} for t in resolved],
        "plan_items": len(_PLAN_ITEM_RE.findall(report)),
    }


@click.command("skill-gaps")
@click.argument("targets", nargs=-1)
@click.option("--job", "jobs", multiple=True, help="A job to analyse: words from its company and title (`--job trustpilot`); repeatable.")
@click.option("--top", type=click.IntRange(min=1), default=None, help="Also analyse the top N matches from `jobs`.")
@click.option("--model", default=None, help=f"Claude model to analyse with (default: {_DEFAULT_MODEL}).")
def skill_gaps(targets: tuple[str, ...], jobs: tuple[str, ...], top: int | None, model: str | None):
    """Skill-gap report for TARGETS (role names), the --job postings and/or
    the --top N matches: a prioritised, WebSearch-cited learning plan written to
    upskill/report-<today>.md by one `claude -p` call (minutes).
    """
    interactive = common._stdout_is_tty()
    try:
        job_refs = [common._job_ref_cli(j, workspace.JOBS_DIR) for j in jobs]  # a picker, before the live line
        with _progress.live_progress(enabled=interactive) as reporter:
            result = _skill_gaps_core(list(targets), jobs=job_refs, top=top, model=model, profile_dir=workspace.PROFILE_DIR,
                                      jobs_dir=workspace.JOBS_DIR, progress=reporter)
    except (FileNotFoundError, ValueError, claude_cli.ClaudeError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    _render_report(result)


def _render_report(result: dict) -> None:
    """✓, what was analysed, how many plan items, where the report is (one
    unbroken line, so it stays copyable), and what to do next."""
    from rich.markup import escape

    console = common._console()
    console.print()
    common._mark_line(console, "ok", "Upskill plan written")
    console.print()
    for i, target in enumerate(result["targets"]):
        label = "Analysed" if i == 0 else ""
        console.print(f"  [dim]{label:<8}[/] {escape(target['label'])}", soft_wrap=True)
    console.print(f"  [dim]{'Plan':<8}[/] {result['plan_items']} plan item(s)", soft_wrap=True)
    console.print(f"  [dim]{'Report':<8}[/] [green]{escape(common._display_path(result['report_path']))}[/]", soft_wrap=True)
    console.print()
    common._next_steps(console, [("./door cv enrich <url ...>", "add what you have learned to profile/cv.md, from public pages")])
