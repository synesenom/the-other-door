"""`jobs salary`: the salary range to expect for one job, from a quick Haiku web search (#371).

One `claude_cli.ask()` with WebSearch, only when the user asks; the answer is cached in
`jobs/salary.json` (`{job_id: {low, high, currency, period, gross, position, basis, sources, ad_salary,
as_of}}`) so a second look costs nothing. In the app it runs only by itself (#624): `prepare` asks once a
job is prepared, reusing an estimate younger than `STALE_AFTER_DAYS`; `show` reads the cache and never
asks; `find` never calls it.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click

from door.commands import _common as common
from door.core import claude_cli, lock, profile_loader, salary, workspace
from door.core.jobs import selection
from door.core.utils import write_json_atomic

CACHE = "salary.json"
_NO_SOURCE = "No salary source found for this job, so there is no number to give."
STALE_AFTER_DAYS = 90  # `prepare` asks again for an estimate older than this


_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "low": {"type": "number"},
        "high": {"type": "number"},
        "currency": {"type": "string"},
        "period": {"type": "string", "enum": ["month", "year"]},
        "gross": {"type": "boolean"},
        "position": {"type": "string", "enum": ["below", "within", "above"]},
        "basis": {"type": "string"},
        "sources": {
            "type": "array",
            "items": {"type": "object", "properties": {"title": {"type": "string"}, "url": {"type": "string"}},
                      "required": ["url"]},
        },
        "ad_salary": {"type": ["string", "null"]},
    },
    "required": ["found"],
}


def _read_cache(jobs_dir: Path) -> dict:
    import json

    try:
        data = json.loads((jobs_dir / CACHE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def cached(job_id: str, jobs_dir: Path) -> dict | None:
    """The cached estimate for *job_id*, or None; reads only, never asks."""
    entry = _read_cache(jobs_dir).get(job_id)
    return entry if isinstance(entry, dict) else None


def _fresh(entry: dict, max_age_days: int | None, now: datetime | None = None) -> bool:
    """Whether a cached *entry* may stand: always without ``max_age_days``, else when its ``as_of`` is
    younger than that (an unreadable date is old)."""
    if max_age_days is None:
        return True
    try:
        as_of = datetime.fromisoformat(str(entry.get("as_of")))
    except ValueError:
        return False
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) - as_of < timedelta(days=max_age_days)


def _salary_core(job_id: str, refresh: bool = False, *, max_age_days: int | None = None, model: str | None = None,
                 jobs_dir: Path | None = None, profile_dir: Path | None = None) -> dict:
    """The salary range to expect for one job.

    Returns ``{"job_id", "title", "company", "found": True, "low", "high", "currency", "period"
    ("month"|"year"), "gross", "position" ("below"|"within"|"above"|None), "basis", "sources":
    [{"title", "url"}], "ad_salary", "as_of", "cached"}``, or ``{"job_id", "title", "company", "found":
    False, "message"}`` when the search found nothing it can cite (not cached, so a later ask tries again).
    A cached estimate is returned without a call unless `refresh`, or unless it is ``max_age_days`` or
    older (`prepare` passes `STALE_AFTER_DAYS`; a user's own ask shows an old one as it is).

    Raises:
        ValueError / LookupError: no such job, or several (``candidates``); the CV could not be read (`cv_read.CvReadError`).
        claude_cli.ClaudeError: the call failed; nothing is cached.
    """
    jobs_dir = Path(jobs_dir if jobs_dir is not None else workspace.JOBS_DIR)
    profile_dir = Path(profile_dir if profile_dir is not None else workspace.PROFILE_DIR)
    job_id = common._resolve_job_ref(job_id, jobs_dir)
    posting = selection.find_posting(jobs_dir, job_id)
    if posting is None:
        raise LookupError(f"no posting found for job_id {job_id!r}")
    head = {"job_id": job_id, "title": posting.get("title", ""), "company": posting.get("company", "")}

    entry = None if refresh else cached(job_id, jobs_dir)
    if entry is not None and _fresh(entry, max_age_days):
        return {**head, "found": True, **entry, "cached": True}

    config = profile_loader.load_config_or_defaults(profile_dir)
    try:
        cv_text = workspace.cv_path(config, profile_dir).read_text(encoding="utf-8")
    except OSError:
        cv_text = ""
    text = salary.build_input(posting, cv_text, config, common._cv_reading(config, profile_dir))  # a CV that cannot be read is never sent as it is
    answer = claude_cli.ask(claude_cli.prompt("salary"), text, model=model or claude_cli.model_of("salary"), feature="salary",
                            schema=_SCHEMA, allowed_tools=claude_cli.tools_of("salary"), timeout_s=180, profile_dir=profile_dir)
    parsed = salary.parse(answer)
    if parsed is None:
        return {**head, "found": False, "message": _NO_SOURCE}
    entry = {**parsed, "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with lock.ledger_lock(jobs_dir, "salary"):
        store = _read_cache(jobs_dir)
        store[job_id] = entry
        write_json_atomic(jobs_dir / CACHE, store)
    return {**head, "found": True, **entry, "cached": False}


def _amount(value) -> str:
    return f"{value:,.0f}"


def range_text(entry: dict) -> str:
    """``55,000–70,000 DKK per month (gross)``."""
    gross = "gross" if entry.get("gross", True) else "net"
    return f"{_amount(entry['low'])}–{_amount(entry['high'])} {entry['currency']} per {entry['period']} ({gross})"


def render(result: dict) -> str:
    """The estimate as the CLI prints it."""
    label = f"{result['title']} — {result['company']}"
    if not result["found"]:
        return f"{label}\n{result['message']}"
    lines = [label, range_text(result)]
    if result["ad_salary"]:
        lines.append(f"The ad says: {result['ad_salary']}")
    if result["position"] or result["basis"]:
        lines.append(f"You sit {result['position'] or 'in it'}: {result['basis']}".rstrip(": "))
    lines += ["Sources:", *(f"- {s['title']} {s['url']}" for s in result["sources"])]
    lines.append(f"An estimate from public pages as of {result['as_of'][:10]}, not advice.")
    return "\n".join(lines)


@click.command("salary")
@click.argument("job_id", metavar="JOB", required=False)
@click.option("--refresh", is_flag=True, help="Ask again even if an estimate is saved.")
@click.option("--model", default=None, help=f"Claude model to ask (default: {claude_cli.model_of('salary')}).")
def salary_cmd(job_id: str | None, refresh: bool, model: str | None):
    """The salary range to expect for JOB, with sources.

    JOB is words from its company and title (`trustpilot`; several matches are picked from) or its id;
    without it, pick from your jobs. One Haiku call with a web search, adjusted to your CV's experience
    against what the ad asks; the answer is saved in jobs/salary.json, so asking again costs nothing
    (`--refresh` asks anew). An estimate from public pages, with its sources, not advice."""
    try:
        job_id = common._job_ref_cli(job_id, workspace.JOBS_DIR)
        if job_id is None:
            click.echo("No postings to pick from — `find` fetches some, `jobs add` brings one in.")
            return
        result = _salary_core(job_id, refresh, model=model, jobs_dir=workspace.JOBS_DIR, profile_dir=workspace.PROFILE_DIR)
    except (ValueError, LookupError, claude_cli.ClaudeError, lock.LockHeldError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    click.echo(render(result))
