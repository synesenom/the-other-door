"""`skill-gaps`: a prioritised, WebSearch-cited learning plan for the gaps between
the CV and a target role or some matches, written to `upskill/report-<date>.md`.

Two `claude -p` calls, so no call that can search the web holds the CV or an ad (a hidden instruction in an ad
could otherwise put the CV into a search): the first, with no tools, reads the CV and the targets and names the
gaps; the second, with WebSearch, gets only the date and the gap names and finds resources. Code keeps what it
can verify of each answer and writes the Markdown itself. The `skill_gaps` tool in a conversation and
`cv gaps` in a shell make the same calls.
"""

import re
import sys
from datetime import date
from pathlib import Path

import click

from door.commands import _common as common
from door.commands import _progress
from door.commands import matches as matches_cmd
from door.core import profile_loader
from door.core import claude_cli, utils, workspace
from door.core import progress as progress_mod
from door.matching import integrity

_PLAN_ITEM_RE = re.compile(r"^### \d+\.", re.MULTILINE)
MAX_GAPS = 15
MAX_NAME = 80
MAX_WHY = 300
MAX_TITLE = 200
_PRIORITIES = ("High", "Medium", "Low")
_NO_RESOURCE = "No vetted resource found — manual research recommended."

_GAPS_SCHEMA = {
    "type": "object",
    "properties": {"gaps": {"type": "array", "items": {
        "type": "object",
        "properties": {"name": {"type": "string"}, "pass": {"type": "integer", "enum": [1, 2]},
                       "source_or_why": {"type": "string"}, "priority": {"type": "string", "enum": list(_PRIORITIES)}},
        "required": ["name", "pass", "source_or_why", "priority"],
    }}},
    "required": ["gaps"],
}
_RESOURCES_SCHEMA = {
    "type": "object",
    "properties": {"resources": {"type": "array", "items": {
        "type": "object",
        "properties": {"gap": {"type": "string"}, "title": {"type": "string"}, "url": {"type": "string"}},
        "required": ["gap", "url"],
    }}},
    "required": ["resources"],
}


def _today() -> str:
    return date.today().isoformat()


def _resolve_targets(targets: list[str], top: int | None, *, jobs_dir: Path, profile_dir: Path,
                     jobs: list[str] | None = None) -> list[dict]:
    """Each role name in *targets* as ``{"kind": "role", "label"}``, and each job in *jobs* (words
    from its company and title, or its id) and each of the top N matches as
    ``{"kind": "posting", "label", "job_id", "posting"}``."""
    from door.core.jobs.selection import find_posting

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


def _line(value, limit: int) -> str:
    """One line of at most *limit* characters; a `|` would break a table cell."""
    return " ".join(str(value or "").split()).replace("|", "/")[:limit].strip()


def parse_gaps(answer: dict) -> list[dict]:
    """The analysis's gaps held to what code can verify: at most `MAX_GAPS` distinct names, each one line of at most
    `MAX_NAME` characters, a pass of 1 or 2, a known priority (else Medium).

    Raises:
        claude_cli.ClaudeError: the answer has no list of gaps.
    """
    items = answer.get("gaps")
    if not isinstance(items, list):
        raise claude_cli.ClaudeError("claude's analysis has no list of gaps")
    gaps, seen = [], set()
    for item in items:
        name = _line(item.get("name"), MAX_NAME) if isinstance(item, dict) else ""
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        priority = item.get("priority")
        gaps.append({"name": name, "pass": 1 if item.get("pass") == 1 else 2,
                     "why": _line(item.get("source_or_why"), MAX_WHY),
                     "priority": priority if priority in _PRIORITIES else "Medium"})
        if len(gaps) == MAX_GAPS:
            break
    return gaps


def parse_resources(answer: dict, gaps: list[dict]) -> dict[str, list[dict]]:
    """Gap name to its resources: only for a gap that was sent, and only an http(s) URL."""
    by_name = {g["name"] for g in gaps}
    found: dict[str, list[dict]] = {}
    for item in answer.get("resources") or []:
        if not isinstance(item, dict) or item.get("gap") not in by_name:
            continue
        url = item.get("url")
        if isinstance(url, str) and re.match(r"https?://\S+$", url):
            found.setdefault(item["gap"], []).append({"title": _line(item.get("title"), MAX_TITLE) or url, "url": url})
    return found


def build_report(today: str, targets: list[dict], gaps: list[dict], resources: dict[str, list[dict]]) -> str:
    """The Markdown report, written by code from the checked gaps and resources."""
    out = [f"# Upskill Plan — {today}", "", "## Target role(s)"] + [f"- {_line(t['label'], 200)}" for t in targets]
    for number, heading, column in ((1, "Hard-skill gaps", "Source"), (2, "Synthesised gaps", "Why it matters")):
        out += ["", f"## Pass {number} — {heading}", "", f"| Gap | {column} | Priority |", "|-----|" + "-" * len(column) + "|----------|"]
        out += [f"| {g['name']} | {g['why']} | {g['priority']} |" for g in gaps if g["pass"] == number]
    planned = sorted((g for g in gaps if g["name"] in resources), key=lambda g: _PRIORITIES.index(g["priority"]))
    out += ["", "## Prioritized learning plan"]
    for i, g in enumerate(planned, 1):
        out += ["", f"### {i}. {g['name']} (Priority: {g['priority']})", f"**Why**: {g['why']}", "**Resources**:"]
        out += [f"- [{r['title'].replace(']', ')').replace('[', '(')}]({r['url']})" for r in resources[g["name"]]]
    skipped = [f"- {g['name']}: {_NO_RESOURCE}" for g in gaps if g["name"] not in resources]
    out += ["", "## Skipped gaps"] + (skipped or ["none"])
    return "\n".join(out) + "\n"


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
    two `claude -p` calls (the analysis, then a WebSearch for resources that sees only the gap names). Never prints: the calls are reported to ``progress``
    (stage ``"gaps"``) as they start and, with an ``outcome``, as they end.

    Returns:
        ``{"report_path", "report" (its Markdown), "targets": [{"kind", "label", "job_id"?}], "plan_items"}``.

    Raises:
        FileNotFoundError, ConfigError: no or invalid profile/config.json; no CV.
        ValueError: no target, or a job reference that matches no job or several
            (`AmbiguousJobRef`).
        claude_cli.ClaudeError: a `claude -p` call failed or the analysis has no list of gaps.
    """
    if profile_dir is None:
        profile_dir = workspace.PROFILE_DIR
    if jobs_dir is None:
        jobs_dir = workspace.JOBS_DIR
    config = profile_loader.load_profile_config(profile_dir)
    cv_path = workspace.cv_path(config, profile_dir)
    if not cv_path.is_file():
        raise FileNotFoundError(f"{cv_path} not found (profile/cv.md): set up the profile first")
    resolved = _resolve_targets(targets or [], top, jobs_dir=jobs_dir, profile_dir=profile_dir, jobs=jobs)

    today = _today()
    # the analysis has no tools, so it may read the whole CV and the ads
    prompt = (
        f"Date: {today}\n\n"
        f"CV:\n<<<\n{cv_path.read_text(encoding='utf-8')}\n>>>\n\n"
        "Targets:\n\n" + "\n\n".join(_target_text(t) for t in resolved) + "\n"
    )
    model = model or claude_cli.model_of("skill-gaps")
    progress_mod.report(f"analysing {len(resolved)} target(s) with {model} (minutes)", stage="gaps")
    try:
        found = parse_gaps(claude_cli.ask("skill-gaps", prompt, model=model, feature="skill_gaps", schema=_GAPS_SCHEMA,
                                          timeout_s=timeout_s, profile_dir=profile_dir))
        resources: dict[str, list[dict]] = {}
        if found:
            # the search has the web, so it gets the date and the gap names, never the CV or an ad
            names = "\n".join(f"- {g['name']}" for g in found)
            resources = parse_resources(
                claude_cli.ask("skill-resources", f"Date: {today}\n\nGaps:\n{names}\n", feature="skill_gaps",
                               schema=_RESOURCES_SCHEMA, timeout_s=timeout_s, profile_dir=profile_dir), found)
    except claude_cli.ClaudeError:
        progress_mod.report("the analysis failed", stage="gaps", outcome="failed")
        raise
    progress_mod.report(f"analysed {len(resolved)} target(s)", stage="gaps", outcome="ok")
    report = build_report(today, resolved, found, resources)

    out_dir = workspace.UPSKILL_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"report-{today}.md"
    utils.write_atomic(report_path, report)
    return {
        "report_path": str(report_path),
        "report": report,
        "targets": [{k: v for k, v in t.items() if k != "posting"} for t in resolved],
        "plan_items": len(_PLAN_ITEM_RE.findall(report)),
    }


@click.command("skill-gaps")
@click.argument("targets", nargs=-1)
@click.option("--job", "jobs", multiple=True, help="A job to analyse: words from its company and title (`--job trustpilot`); repeatable.")
@click.option("--top", type=click.IntRange(min=1), default=None, help="Also analyse the top N matches from `jobs`.")
@click.option("--model", default=None, help=f"Claude model to analyse with (default: {claude_cli.model_of('skill-gaps')}).")
def skill_gaps(targets: tuple[str, ...], jobs: tuple[str, ...], top: int | None, model: str | None):
    """Skill-gap report for TARGETS (role names), the --job postings and/or
    the --top N matches: a prioritised, WebSearch-cited learning plan written to
    upskill/report-<today>.md by two `claude -p` calls (minutes).
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
