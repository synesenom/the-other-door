"""`jobs` (list) and `jobs show`: browse the matches, best first, and one posting with its status history and prepared materials."""

import os
import re
import subprocess
import sys
from pathlib import Path

import click

import door.core.tracker as _tracker_mod
from door import i18n
from door.commands import _common as common
from door.commands import _prompts
from door.commands import compile as compile_cmd
from door.commands import revise as revise_cmd
from door.commands import salary as salary_cmd
from door.commands import status as status_cmd
from door.core import sites, workspace
from door.tailoring import facts as facts_mod
from door.tailoring import readability


def _list_core(
    min_score: float | None = None,
    limit: int | None = None,
    jobs_dir: Path | None = None,
    profile_dir: Path | None = None,
    new_only: bool = False,
    status: str | None = None,
    ongoing: bool = False,
    closed: bool = False,
) -> dict:
    """Matches, best first, as summaries — ids and headline fields only.

    Never includes descriptions (context economy for MCP callers — `show`
    is the one call that returns a posting's full text).

    Only untracked (or ``unapplied``) postings scoring at least `min_score` (default:
    config's ``min_score``) and above 0; postings older than config's
    ``max_age_days`` (default 30; measured from ``posted_at``, else
    ``scraped_at``; ``null`` disables) are dropped.

    Args:
        limit: Only the top N (`cv gaps --top N`).
        new_only: Only postings first seen (``scraped_at``) after the last
            review (`jobs/last_review.json`, stamped by `reviewed`).
        status: Only postings with this ledger status (``unapplied`` includes the
            untracked) instead of the untracked ones. Your own postings stay
            listed however old, and `min_score` defaults to 0 unless given.
        ongoing: Only postings still in play (``prepared``, ``applied``, ``interview:*``,
            ``offer``), listed like `status` does; not together with `status`.
        closed: Only applications that ended: ``rejected``, ``ghosted``, or ``discarded`` after
            being in play (a match dismissed without applying is not one); listed like `status`.

    Returns:
        ``{"min_score", "last_reviewed_at", "scored", "matches": [{"id",
        "score", "title", "title_en", "company", "location", "work_permit",
        "status", "is_new", "updated_at", "rounds"}, ...]}``, sorted by score descending;
        ``weak`` is None, or, in the default view only (no status, ongoing, closed, new_only or limit) until any posting
        on disk has scored at least the config's ``min_score``, ``{"matches": [rows like the above, the best 3 untracked
        fresh postings below the bar], "hint": "sources" | "keywords", "sources": [{"key", "label"}]}``: ``sources``
        names the discovery sources serving the profile's city that are not turned on;
        ``scored`` is how many postings on disk the model scored (score above 0), whatever the filters, status or limit;
        ``updated_at`` is when the current status happened (None when untracked), ``rounds`` the
        interview rounds as ``[{"stage", "result"}]`` (`ApplicationTracker.interview_rounds`); ``title_en`` is the
        English translation of a non-English title, else ``None``; ``work_permit`` is what the ad says
        about a visa or work permit (``no_sponsorship``, ``permit_required``,
        ``sponsorship_offered``, ``not_mentioned``) or ``None`` when unscored; ``status`` is the ledger status
        or ``"unapplied"``; ``is_new`` is whether it was first seen after the last
        review (always True before the first review).
    """
    from door.core import selection

    if jobs_dir is None:
        jobs_dir = workspace.JOBS_DIR
    if profile_dir is None:
        profile_dir = workspace.PROFILE_DIR

    config = common._load_config_or_defaults(profile_dir)
    if status is not None and status not in _tracker_mod.CANONICAL_STATUSES:
        raise ValueError(f"unknown status {status!r}; one of {', '.join(sorted(_tracker_mod.CANONICAL_STATUSES))}")
    if sum((ongoing, closed, status is not None)) > 1:
        raise ValueError("ongoing, closed and status are alternatives: pass one")
    wanted = _tracker_mod.ONGOING_STATUSES if ongoing else _tracker_mod.CLOSED_STATUSES if closed else status
    if min_score is not None:
        resolved_min_score = min_score
    elif wanted is not None and wanted != "unapplied":
        resolved_min_score = 0.0
    else:
        resolved_min_score = config.get("min_score", common._DEFAULT_MIN_SCORE)

    app_tracker = _tracker_mod.ApplicationTracker(jobs_dir / "applications.json")
    postings = selection.read_postings(jobs_dir)
    scored = sum(1 for p in postings if (p.get("score") or 0) > 0)
    matches = selection.select_matches(jobs_dir, app_tracker, resolved_min_score, status=wanted, postings=postings)
    if closed:
        matches = [m for m in matches if any(e.get("status") in _tracker_mod.ONGOING_STATUSES for e in app_tracker.history(m.get("id", "")))]
    if wanted in (None, "unapplied"):
        matches = common._drop_stale(matches, config.get("max_age_days", common._DEFAULT_MAX_AGE_DAYS))
    reviewed_iso = status_cmd._last_reviewed_at(jobs_dir)
    reviewed_at = common._parse_iso(reviewed_iso)
    seen = status_cmd._seen_since_review(jobs_dir)
    if new_only:
        matches = [m for m in matches if status_cmd._is_new_since(m, reviewed_at, seen)]
    if limit is not None:
        matches = matches[:limit]
    weak = None
    if wanted is None and not new_only and limit is None:
        weak = _weak_matches(postings, app_tracker, jobs_dir, config, reviewed_at, seen)

    return {
        "min_score": resolved_min_score,
        "last_reviewed_at": reviewed_iso,
        "scored": scored,
        "matches": [_match_row(posting, app_tracker, reviewed_at, seen) for posting in matches],
        "weak": weak,
    }


_WEAK_COUNT = 3


def _match_row(posting: dict, app_tracker, reviewed_at, seen) -> dict:
    job_id = posting.get("id", "")
    return {
        "id": job_id,
        "score": posting.get("score"),
        "title": posting.get("title", ""),
        "title_en": posting.get("title_en"),
        "company": posting.get("company", ""),
        "location": posting.get("location", ""),
        "work_permit": posting.get("work_permit"),
        "status": app_tracker.get_status(job_id) or "unapplied",
        "is_new": status_cmd._is_new_since(posting, reviewed_at, seen),
        "updated_at": app_tracker.updated_at(job_id),
        "rounds": [{"stage": r["stage"], "result": r["result"]} for r in app_tracker.interview_rounds(job_id)],
    }


def _weak_matches(postings, app_tracker, jobs_dir, config, reviewed_at, seen) -> dict | None:
    """Until any posting on disk has scored at least the config's ``min_score``: the best few
    untracked, fresh postings below it, with what would widen the search. None otherwise."""
    from door.core import discovery_sources, selection

    bar = config.get("min_score", common._DEFAULT_MIN_SCORE)
    if any((p.get("score") or 0) >= bar for p in postings):
        return None
    below = selection.select_matches(jobs_dir, app_tracker, 0.0, status=None, postings=postings)
    below = common._drop_stale(below, config.get("max_age_days", common._DEFAULT_MAX_AGE_DAYS))
    best = [p for p in below if 0 < (p.get("score") or 0) < bar][:_WEAK_COUNT]
    if not best:
        return None
    off = discovery_sources.off_for_location(config)
    return {
        "matches": [_match_row(p, app_tracker, reviewed_at, seen) for p in best],
        "hint": "sources" if off else "keywords",
        "sources": [{"key": s["key"], "label": s["label"]} for s in off],
    }


def weak_line(weak: dict) -> str:
    """The line above the weak matches: how many, and what would widen the search."""
    count = len(weak["matches"])
    head = f"{count} weak match{' found' if count == 1 else 'es found'}."
    if weak["hint"] == "sources":
        labels = [s["label"] for s in weak["sources"]]
        names = labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]
        return f"{head} Turn on more sources ({names}) in your profile to widen the search, at your own risk (see LEGAL_DISCLAIMER.md)."
    return f"{head} Broaden your search keywords to find closer ones."


# How `show` words the scorer's work_permit value; not_mentioned and missing show no row.
_WORK_PERMIT_LABELS = {
    "no_sponsorship": "no visa sponsorship",
    "permit_required": "permit required",
    "sponsorship_offered": "sponsorship offered",
}


def _render_matches_table(result: dict, *, title: str | None = None) -> None:
    """A table: score bar | posting, each row one line: the title (and
    English title) · company · location, cut short with ``…`` when it does not
    fit; no job id (later commands take words from company and title). A status column appears only when some row has one (`--status`,
    `--ongoing`); the default listing is all untracked, so it has none.

    ``✦`` before the title marks postings first seen since the last review — only once there has
    been one, since before it every posting is new.
    """
    from rich import box
    from rich.table import Table
    from rich.text import Text

    console = common._console(max_width=common._LIST_MAX_WIDTH)
    matches = result["matches"]
    mark_new = result["last_reviewed_at"] is not None

    count = len(matches)
    if title is None:
        threshold = f" ≥ {result['min_score']:.2f}" if result["min_score"] > 0 else " scored above 0"
        console.print(Text.assemble((f"{count} match{'' if count == 1 else 'es'}", "bold"), (threshold, "dim")))
    else:
        console.print(Text(title, style="bold"))
    table = Table(box=box.SIMPLE_HEAD, header_style="dim", pad_edge=False, expand=True)
    table.add_column("Score", no_wrap=True)
    table.add_column("Posting")
    show_status = any(m.get("status", "unapplied") != "unapplied" for m in matches)
    if show_status:
        table.add_column("Status", no_wrap=True)
    for match in matches:
        headline = Text(no_wrap=True, overflow="ellipsis")
        if mark_new and match["is_new"]:
            headline.append("✦ ", style="yellow")
        headline.append(match.get("title", ""), style="bold")
        if match.get("title_en"):
            headline.append(f" ({match['title_en']})", style="italic")
        headline.append(f" · {match.get('company', '')}", style="cyan")
        if match.get("location"):
            headline.append(f" · {match['location']}", style="dim")
        cells = [common._score_text(match.get("score")), headline]
        if show_status:
            cells.append(Text(match.get("status", "unapplied"), style="magenta"))
        table.add_row(*cells)
    console.print(table)
    if mark_new and any(m["is_new"] for m in matches):
        console.print(Text("✦ new since your last review", style="dim yellow"))


@click.command("list")
@click.option("--score", type=float, default=None, help="Only matches scoring at least this (default: anything above 0).")
@click.option("--new", "new_only", is_flag=True, default=False, help="Only postings first seen since the last `reviewed`.")
@click.option("--status", type=click.Choice(_tracker_mod.STATUSES), default=None, help="Only postings with this status (default: the ones you haven't acted on).")
@click.option("--ongoing", is_flag=True, default=False, help="Only postings still in play: prepared, applied, interview:… or offer.")
@click.option("--closed", is_flag=True, default=False, help="Only applications that ended: rejected, ghosted, or withdrawn after preparing or applying.")
def list_matches(score: float | None, new_only: bool, status: str | None, ongoing: bool, closed: bool):
    """List the job matches you haven't acted on yet, best first.

    Reads scored postings from jobs/postings/<date>/<site>/*.json and prints those
    scoring at least --score (default: anything above 0), best first.
    Postings with a status (prepared, applied, discarded, …; per
    jobs/applications.json) and postings older than max_age_days (default 30)
    are not listed, unless --status asks for that status: then those postings
    are listed, however old. --ongoing lists the ones still in play (prepared, applied,
    interview, offer) the same way, and --closed the applications that ended. --new keeps only postings first seen since the last
    `reviewed` stamp. Later commands name a job by words from its company
    and title (e.g. `jobs prepare trustpilot`).
    """
    if sum((ongoing, closed, status is not None)) > 1:
        raise click.UsageError("--ongoing, --closed and --status are alternatives: pass one.")
    result = _list_core(
        min_score=score if score is not None else 0.0,
        jobs_dir=workspace.JOBS_DIR,
        profile_dir=workspace.PROFILE_DIR,
        new_only=new_only,
        status=status,
        ongoing=ongoing,
        closed=closed,
    )

    # Until a posting clears the bar, plain `jobs` (whose default lists anything above 0) shows the weak block,
    # as the app does; an explicit --score lists what cleared it.
    weak = result.get("weak")
    if weak and (score is None or not result["matches"]):
        _render_matches_table({**result, "matches": weak["matches"]}, title=weak_line(weak))
        return
    if not result["matches"]:
        click.echo("No matches found — `./door find` first.")
        return

    _render_matches_table(result)


_MATERIALS = ("cv", "cover_letter")
_TAILORING_RE = re.compile(r"^\s*%\s*Tailoring:\s*(.+?)\s*$", re.MULTILINE)
_PAGE_PNG_RE = re.compile(r"_page_(\d+)\.png$")


def _show_core(job_id: str, *, open: bool = False, jobs_dir: Path | None = None) -> dict:
    """One posting in full (description included), its ledger status and,
    once prepared, a summary of its materials.

    Returns:
        The posting's JSON fields plus ``"source_name"`` (`sites.source_name`: the site
        in words, None for a posting added by hand), ``"status"`` (``"unapplied"`` if untracked),
        ``"history"`` (`ApplicationTracker.timeline`: every status change with
        its date and note, each interview round with its result; empty while
        untracked) and ``"materials"``: ``None`` until both PDFs exist, then
        `_materials`'s dict plus ``"sent"``: whether the application went out (any sent status in its
        history, `tracker.is_sent`). A sent application's materials are the copy taken when it was first
        sent (``output/<id>/sent/``), not the working files a later `revise` may have changed; without
        that copy, the working files. ``"salary"`` is the cached estimate (`salary.cached`: what
        `prepare` found, #624) or None; `show` never asks for one.

    Raises:
        ValueError: `job_id` is not a valid slug.
        LookupError: no posting with that id under `jobs_dir`.
        FileNotFoundError: ``open`` and no prepared materials yet.
    """
    from door.core.selection import find_posting

    if jobs_dir is None:
        jobs_dir = workspace.JOBS_DIR
    job_id = common._resolve_job_ref(job_id, jobs_dir)

    posting = find_posting(jobs_dir, job_id)
    if posting is None:
        raise LookupError(f"no posting found for job_id {job_id!r}")

    app_tracker = _tracker_mod.ApplicationTracker(jobs_dir / "applications.json")
    sent = any(_tracker_mod.is_sent(event.get("status")) for event in app_tracker.history(job_id))
    output_dir = jobs_dir / "output" / job_id
    sent_dir = output_dir / "sent"
    materials = (_materials(sent_dir) if sent else None) or _materials(output_dir)
    if materials is not None:
        materials["sent"] = sent
    if open:
        if materials is None:
            raise FileNotFoundError(f"no prepared materials for {job_id!r} in {output_dir} — prepare it first")
        _open_files([materials["pdfs"][name] for name in _MATERIALS])

    return {
        **posting,
        "source_name": sites.source_name(posting.get("source")),
        "status": app_tracker.get_status(job_id) or "unapplied",
        "history": app_tracker.timeline(job_id),
        "materials": materials,
        "salary": salary_cmd.cached(job_id, jobs_dir),
    }


def _material_pngs(output_dir: Path, name: str) -> list[str]:
    pages = []
    for path in output_dir.glob(f"{name}_page_*.png"):
        match = _PAGE_PNG_RE.search(path.name)
        if match:
            pages.append((int(match.group(1)), str(path)))
    return [p for _, p in sorted(pages)]


_UNSAFE_IN_FILE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _file_names(name: str | None) -> dict[str, str]:
    """What to save the CV and the letter as: the candidate's name first (what an employer sees on an
    upload, never ``cv.pdf``), plain ASCII around it, no character a file system refuses."""
    who = " ".join(_UNSAFE_IN_FILE_NAME.sub(" ", name or "").split())
    prefix = f"{who} - " if who else ""
    return {"cv": f"{prefix}CV.pdf", "cover_letter": f"{prefix}Cover letter.pdf"}


def _materials(output_dir: Path) -> dict | None:
    """Everything needed to judge a posting's prepared materials, or None
    until both PDFs are in `output_dir`.

    PDF and page-PNG paths (rendering the PNGs first if any are missing),
    the ``% Keywords:`` and ``% Tailoring:`` lines the tailor writes into
    ``cv.tex`` (what it emphasised; what it cut, kept or condensed), page
    counts and the cover letter's word count.

    Returns:
        ``{"output_dir", "pdfs": {"cv", "cover_letter"}, "pngs": {"cv":
        [...], "cover_letter": [...]}, "keywords": [...], "tailoring": [...],
        "page_counts": {"cv", "cover_letter"}, "cover_letter_words",
        "rendered", "unsupported", "file_names"}`` — ``rendered`` says whether this call rendered PNGs;
        ``file_names`` is what to save each PDF as (`_file_names`);
        ``unsupported`` lists the numbers, years, employers, skills, certifications and degrees of the CV and letter
        that ``profile/cv.md`` and the story bank do not back (each ``{kind, value,
        context, file}``; ``[]`` clean; None not checked, e.g. no cv.md); ``readability`` is what an ATS
        would not read back from the PDFs on disk (`readability.check_pdf`; each ``{file, kind, detail}``,
        ``file`` ``cv`` or ``cover_letter``; ``[]`` clean; None when a PDF could not be read).
    """
    from door.tailoring import pdf_render

    pdfs = {name: output_dir / f"{name}.pdf" for name in _MATERIALS}
    if not all(p.is_file() for p in pdfs.values()):
        return None

    rendered = False
    if not all(_material_pngs(output_dir, name) for name in _MATERIALS):
        compile_cmd._render_pages(output_dir)
        rendered = True

    cv_tex = output_dir / "cv.tex"
    keywords: list[str] = []
    tailoring: list[str] = []
    if cv_tex.is_file():
        cv_text = cv_tex.read_text(encoding="utf-8")
        match = readability.KEYWORDS_RE.search(cv_text)
        if match:
            keywords = [k.strip() for k in match.group(1).split(",") if k.strip()]
        match = _TAILORING_RE.search(cv_text)
        if match:
            tailoring = [n.strip() for n in match.group(1).split(";") if n.strip()]

    letter_tex = output_dir / "cover_letter.tex"
    words = revise_cmd._latex_word_count(letter_tex.read_text(encoding="utf-8")) if letter_tex.is_file() else None

    unsupported = facts_mod.check(output_dir, workspace.PROFILE_DIR, write=False)
    if unsupported is None:
        unsupported = facts_mod.load(output_dir)

    return {
        "output_dir": str(output_dir),
        "readability": _readability(output_dir),
        "pdfs": {name: str(path) for name, path in pdfs.items()},
        "pngs": {name: _material_pngs(output_dir, name) for name in _MATERIALS},
        "keywords": keywords,
        "tailoring": tailoring,
        "page_counts": {name: pdf_render.get_page_count(path) for name, path in pdfs.items()},
        "cover_letter_words": words,
        "rendered": rendered,
        "unsupported": unsupported,
        "file_names": _file_names(common._load_config_or_defaults(workspace.PROFILE_DIR).get("name")),
    }


def _readability(output_dir: Path) -> list[dict] | None:
    """The ATS read-back of both PDFs in `output_dir`, or None when either cannot be read."""
    name = compile_cmd._profile_name()
    found: list[dict] = []
    try:
        for material in _MATERIALS:
            tex_path = output_dir / f"{material}.tex"
            tex = tex_path.read_text(encoding="utf-8") if tex_path.is_file() else ""
            found += [{"file": material, **p} for p in readability.check_pdf(output_dir / f"{material}.pdf", tex, name)]
    except Exception:  # an unreadable PDF is "not checked", never an error in `show`
        return None
    return found


def _open_files(paths: list[str]) -> None:
    """Open files in the desktop's default viewer (best effort)."""
    for path in paths:
        if sys.platform == "darwin":
            subprocess.run(["open", path], check=False, stdin=subprocess.DEVNULL)
        elif sys.platform == "win32":
            os.startfile(path)  # noqa: S606 — a local PDF the user asked to see
        else:
            subprocess.run(["xdg-open", path], check=False, stdin=subprocess.DEVNULL)


_HEADING_MAX_CHARS = 50
_HEADING_MAX_WORDS = 6


def _posted_text(posted_at) -> str:
    """``2026-10-07 (2 days ago)``, or the raw value when it is not a timestamp."""
    from datetime import datetime, timezone

    dt = common._parse_iso(posted_at)
    if dt is None:
        return str(posted_at or "?")
    days = (datetime.now(timezone.utc) - dt).days
    age = "today" if days <= 0 else "yesterday" if days == 1 else f"{days} days ago"
    return f"{dt.date().isoformat()} ({age})"


def _is_heading(line: str) -> bool:
    """A short line with no sentence punctuation ("About the role", "Requirements:")."""
    return (
        len(line) <= _HEADING_MAX_CHARS
        and len(line.split()) <= _HEADING_MAX_WORDS
        and not line.endswith((".", ",", ";", "!", "?"))
    )


def _description_renderables(description: str, width: int) -> list:
    """The description, one paragraph per line: heading-like lines bold and set
    apart, a blank line after a paragraph that wraps (wider than `width`), runs of
    short lines (lists) kept together."""
    from rich.text import Text

    lines = [line.strip() for line in description.splitlines()]
    lines = [line for line in lines if line]
    out: list = []
    previous_wrapped = False
    for i, line in enumerate(lines):
        if 0 < i < len(lines) - 1 and _is_heading(line):
            out += [Text(""), Text(line, style="bold cyan")]
            previous_wrapped = False
            continue
        wraps = len(line) > width
        if previous_wrapped or (wraps and out and out[-1].plain and out[-1].style != "bold cyan"):
            out.append(Text(""))
        out.append(Text(line))
        previous_wrapped = wraps
    return out


_ROUND_STYLES = {"passed": "green", "rejected": "red", "ghosted": "yellow", "withdrawn": "dim", "pending": "magenta"}


def _render_history(history: list[dict], console) -> None:
    """One line per status change: date, status, how an interview round went, the note."""
    from rich.padding import Padding
    from rich.table import Table
    from rich.text import Text

    common._section(console, "History")
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", no_wrap=True)
    grid.add_column(no_wrap=True)
    grid.add_column(no_wrap=True)
    grid.add_column(overflow="fold")
    for event in history:
        when = common._local_time(event["at"]) if event.get("at") else ""
        result = event.get("result")
        grid.add_row(when, event.get("status") or "", Text(result or "", style=_ROUND_STYLES.get(result, "")),
                     event.get("notes") or "")
    console.print(Padding(grid, (0, 2)))


def _skill_list(skills: list[str], mark: str, style: str):
    """One column of `show`'s Skills: a mark beside each skill, a wrapped skill kept under its text."""
    from rich.table import Table
    from rich.text import Text

    grid = Table.grid(padding=(0, 1))
    grid.add_column(no_wrap=True)
    grid.add_column(overflow="fold")
    for skill in skills:
        grid.add_row(Text(mark, style=style), skill)
    return grid


def _render_posting_detail(posting: dict, status: str, console=None, *, description: bool = True) -> None:
    """A header panel (title, company, location), a key/value grid (score, status,
    posted, source, language, links), the score reason, the skills and (unless
    ``description`` is false: `add`'s card) the description."""
    from rich.padding import Padding
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    console = console or common._console()

    header = Text(posting.get("title", ""), style="bold")
    if posting.get("title_en"):
        header.append(f"\n{posting['title_en']}", style="italic")
    header.append(f"\n{posting.get('company', '')}", style="cyan")
    if posting.get("location"):
        header.append(f" · {posting['location']}", style="dim")
    console.print(Panel(header, border_style=common._score_style(posting.get("score")), padding=(0, 1)))

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", no_wrap=True)
    grid.add_column(overflow="fold")
    grid.add_row("Score", common._score_text(posting.get("score")))
    grid.add_row("Status", Text(status, style="bold magenta" if status != "unapplied" else "bold"))
    grid.add_row("Posted", _posted_text(posting.get("posted_at")))
    grid.add_row("Source", posting.get("source", ""))
    if "language" in posting:
        language = i18n.language_label(posting["language"])
        requirement = posting.get("language_requirement")
        if requirement and requirement != "none":
            language += f" — {requirement}"
        grid.add_row("Language", language)
    permit = _WORK_PERMIT_LABELS.get(posting.get("work_permit"))
    if permit:
        grid.add_row("Work permit", permit)
    if posting.get("salary"):
        grid.add_row("Salary", f"{salary_cmd.range_text(posting['salary'])}, an estimate from public pages")
    grid.add_row("URL", Text(posting.get("url", ""), style="blue underline"))
    apply_url = posting.get("apply_url")
    if apply_url and apply_url != posting.get("url"):
        grid.add_row("Apply", Text(apply_url, style="blue underline"))
    console.print(grid)

    common._section(console, "Why this score")
    console.print(Padding(Text(posting.get("score_reason") or "(unscored)", style="italic"), (0, 2)))

    findings = (posting.get("integrity") or {}).get("findings") or []
    if (posting.get("integrity") or {}).get("verdict") == "suspicious" and findings:
        common._section(console, "Suspicious ad")
        console.print(Padding(Text("Text hidden from readers or aimed at a model was removed before scoring:", style="yellow"), (0, 2)))
        for finding in findings:
            console.print(Padding(Text(f"{finding.get('kind', '')}: {finding.get('excerpt', '')}"), (0, 4)))

    matching = posting.get("matching_skills") or []
    missing = posting.get("missing_skills") or []
    if matching or missing:
        common._section(console, "Skills")
        # Two columns: what the CV covers on the left, what it lacks on the right. Each
        # is its own list, so a skill that wraps on one side never moves the other.
        skills = Table.grid(padding=(0, 2), expand=True)
        skills.add_column(ratio=1)
        skills.add_column(ratio=1)
        skills.add_row(_skill_list(matching, "✓", "bold green"), _skill_list(missing, "✗", "bold red"))
        console.print(Padding(skills, (0, 2)))

    if not description:
        return
    common._section(console, "Description")
    for renderable in _description_renderables(posting.get("description", ""), console.width - 2):
        console.print(Padding(renderable, (0, 2)))


def _render_extras(posting: dict, console) -> None:
    """What `show` adds below the card: the status history, the materials."""
    if posting["history"]:
        _render_history(posting["history"], console)
    if posting["materials"] is not None:
        _render_materials(posting["materials"], console)


def _page_description(posting: dict, console) -> None:
    """The description in the terminal's pager (`less`: scroll, `/` to search,
    `q` back to the card), under the posting's title and company. `less`
    gets ``-R`` for the colours and ``-F`` to just print a description that
    fits the screen, unless ``LESS`` is set already."""
    import os

    from rich.padding import Padding
    from rich.text import Text

    os.environ.setdefault("LESS", "-RF")
    with console.pager(styles=True):
        console.print(Text.assemble((posting.get("title", ""), "bold"), " · ", (posting.get("company", ""), "cyan")))
        common._section(console, "Description")
        for renderable in _description_renderables(posting.get("description", ""), console.width - 2):
            console.print(Padding(renderable, (0, 2)))


def _render_materials(materials: dict, console=None) -> None:
    """The materials summary: what was tailored, page counts, file paths."""
    from rich.padding import Padding
    from rich.table import Table
    from rich.text import Text

    console = console or common._console()
    common._section(console, "Materials")

    def pages(n) -> str:
        return f"{n} page" + ("" if n == 1 else "s")

    words = materials["cover_letter_words"]
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", no_wrap=True)
    grid.add_column()
    grid.add_row("Emphasised", ", ".join(materials["keywords"]) or Text("(no % Keywords line in cv.tex)", style="dim"))
    grid.add_row("Tailored", "\n".join(f"• {n}" for n in materials["tailoring"]) or Text("(no % Tailoring line in cv.tex)", style="dim"))
    grid.add_row("CV", pages(materials["page_counts"]["cv"]))
    grid.add_row(
        "Cover letter",
        f"{pages(materials['page_counts']['cover_letter'])}, {words if words is not None else '?'} words",
    )
    if "unsupported" in materials:
        unsupported = materials["unsupported"]
        if unsupported is None:
            grid.add_row("Not in your CV", Text("(not checked: no cv.md)", style="dim"))
        elif not unsupported:
            grid.add_row("Not in your CV", Text("all claims found in cv.md", style="dim"))
        else:
            from rich.markup import escape

            grid.add_row("Not in your CV", "\n".join(
                f"[yellow]• {escape(c['value'])}  — \"{escape(c['context'])}\"  ({c['file'].replace('_', ' ')})"
                + (f" [dim]— kept: {escape(c['reason'])}[/]" if c.get("reason") else "") + "[/]"
                for c in unsupported))
    if "readability" in materials:
        found = materials["readability"]
        if found is None:
            grid.add_row("Read by an ATS", Text("(not checked: a PDF could not be read)", style="dim"))
        elif not found:
            grid.add_row("Read by an ATS", Text("text reads cleanly", style="dim"))
        else:
            from rich.markup import escape

            grid.add_row("Read by an ATS", "\n".join(
                f"[yellow]• {escape(p['detail'])}  ({p['file'].replace('_', ' ')})[/]" for p in found))
    console.print(Padding(grid, (0, 2)))
    console.print()
    for name in _MATERIALS:
        # soft_wrap: a path is never broken across lines, so it stays copyable.
        console.print(f"  [green]{common._display_path(materials['pdfs'][name])}[/]", soft_wrap=True)
        for png in materials["pngs"][name]:
            console.print(f"    [dim]{common._display_path(png)}[/]", soft_wrap=True)


@click.command()
@click.argument("job_id", metavar="JOB", required=False, default=None)
@click.option("--open", "open_", is_flag=True, default=False, help="Open both prepared PDFs in the default viewer.")
def show(job_id: str | None, open_: bool):
    """Show a single posting in full, its application status and, once
    prepared, its materials.

    JOB is words from its company and title (`trustpilot`, "novonesis head
    of ai"; several matches are picked from) or its id; without it, pick
    from your jobs in play and your matches. Prints title,
    company, location, score, score reason, posted_at, source, url, the
    current application status (or "unapplied" if untracked) and its
    history (every status change; interview rounds with how they went); after `prepare`, also what the CV emphasised and how it
    was tailored, page counts, the cover letter's word count and the PDF/PNG
    paths, and the description. On a terminal the card and history come
    first, then one key: [d] the description in the pager (scroll, `/` to
    search, `q` to close), [m] the materials, [q] or Enter to quit; into a
    pipe everything follows in full.
    """
    try:
        job_id = common._job_ref_cli(job_id, workspace.JOBS_DIR)
        if job_id is None:
            click.echo("No postings to pick from — `find` fetches some, `jobs add` brings one in.")
            return
        posting = _show_core(job_id, open=open_, jobs_dir=workspace.JOBS_DIR)
    except (ValueError, LookupError, FileNotFoundError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    console = common._console()
    if not common._stdout_is_tty():
        _render_posting_detail(posting, posting["status"], console)
        _render_extras(posting, console)
        return

    # On a terminal the card and history stay on screen; the description and the
    # materials are a key away.
    _render_posting_detail(posting, posting["status"], console, description=False)
    if posting["history"]:
        _render_history(posting["history"], console)
    keys = {}
    if (posting.get("description") or "").strip():
        keys["d"] = "description"
    if posting["materials"] is not None:
        keys["m"] = "materials"
    if not keys:
        return
    keys["q"] = "quit"
    console.print()
    while (pressed := _prompts.key("view", "", keys=keys, default="q")) != "q":
        if pressed == "d":
            _page_description(posting, console)
        else:
            _render_materials(posting["materials"], console)
            console.print()
