"""Helpers shared by the command modules: config loading, job references, the ledger lock
decorator, the `claude` CLI guard, small time/JSON utilities and shared defaults.
"""

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import click

from door import i18n
from door.core import cv_read, profile_loader, progress, utils, workspace
from door.core.employers import companies
from door.core.downloads import chromium
from door.core.downloads import installers
from door.core.profile_loader import ConfigError, Profile


# ALL_SITES lives in door.core.sites (re-exported here) so both
# the CLI and Profile.sites validate against the same registry.
_DEFAULT_RETIRE_AFTER_DAYS = 90


def _feed_config(profile_dir: Path) -> dict[str, list[str]]:
    """Each platform's followed employers under the key its scraper reads, from
    `profile_dir/companies.json` (`door.core.employers.companies.feed_config`).

    Raises:
        ConfigError: companies.json is malformed.
    """
    try:
        return companies.feed_config(profile_dir)
    except companies.CompaniesError as exc:
        raise ConfigError(str(exc).splitlines()) from None


def _company_items(profile_dir: Path) -> list:
    """The employer list (`profile_dir/companies.json`) as `Company` objects.

    Raises:
        ConfigError: companies.json is malformed.
    """
    try:
        return companies.load(profile_dir)
    except companies.CompaniesError as exc:
        raise ConfigError(str(exc).splitlines()) from None


def _is_url(value: str) -> bool:
    return re.match(r"https?://", value, re.IGNORECASE) is not None


def web_address(value: str) -> str:
    """A page the user typed, with `https://` when it has no scheme (`github.com/jane`)."""
    value = value.strip()
    return value if re.match(r"[a-z][a-z0-9+.-]*://", value, re.IGNORECASE) else f"https://{value}"


# The sha256 of each earlier profile.example/cv.md that a user may still hold a copy of (#189). Add the hash of the
# old file whenever the example changes (tests/commands/test_example_cv_guard_cli.py pins the current one and fails when it changes).
_PAST_EXAMPLE_CV_SHA256 = frozenset({
    "7fa9feb82a3175b413ac20c255161e87539097264fd6c98bebfffe72dd8ef66a",  # before the tagline and LinkedIn/GitHub (#189)
})


def _is_example_cv(path: Path, example: Path | None = None) -> bool:
    """Whether the CV at `path` is, byte for byte, the example (`example`, else profile.example/'s) or one of its
    earlier versions: the one check every reader of a CV makes (#189)."""
    example = workspace.PROFILE_EXAMPLE_DIR / "cv.md" if example is None else example
    try:
        data = Path(path).read_bytes()
    except OSError:
        return False
    return (example.is_file() and data == example.read_bytes()) or hashlib.sha256(data).hexdigest() in _PAST_EXAMPLE_CV_SHA256


def _cv_is_example(config: dict, profile_dir: Path) -> bool:
    """Whether the profile's CV is still the example (`_is_example_cv`)."""
    return _is_example_cv(workspace.cv_path(config, profile_dir))


EXAMPLE_CV_MESSAGE = "Your CV is still the example (Jane Doe's). Add your own CV first."


def _require_own_cv(config: dict, profile_dir: Path) -> None:
    """Nothing is scored or tailored against the example CV: the results would be someone else's.

    Raises:
        ConfigError: the CV is still the example.
    """
    if _cv_is_example(config, profile_dir):
        raise ConfigError([EXAMPLE_CV_MESSAGE])


def _cv_reading(config: dict, profile_dir: Path) -> dict:
    """The reading (`core.cv_read`) of the profile's CV: cached, so the first caller of a run pays and the rest do not.
    A missing or empty CV is read without a call.

    Raises:
        cv_read.CvReadError: the CV could not be read; there is no fallback.
    """
    path = workspace.cv_path(config, profile_dir)
    return cv_read.read(path.read_text(encoding="utf-8") if path.exists() else "")


def _write_with_backup(path: Path, text: str) -> Path | None:
    """Replace `path`'s contents with `text`, keeping the previous file byte for
    byte as `<path>.bak`; returns the backup path, or None when there was none."""
    backup = None
    if path.exists():
        backup = path.with_name(path.name + ".bak")
        utils.write_atomic(backup, path.read_bytes())
    utils.write_atomic(path, text)
    return backup


# How a `claude -p` call with WebFetch should read a candidate's public pages;
# shared by the prompts that take URLs (`init`'s CV step, `enrich`).
_WEBFETCH_RULES = (
    "Fetch every URL you are given with WebFetch. A personal site's home page is often "
    "navigation only, so follow its own subpages (research, publications, projects, open "
    "source, about); a page that renders with JavaScript loads its content from a data "
    "file (.json, .bib) named in its source, so fetch that. Read a GitHub user through "
    "https://api.github.com/users/<name>/repos?per_page=100 and name only non-fork repos "
    "with stars or a description, with what each one does. Read an ORCID iD through https://pub.orcid.org/v3.0/<id>/works. Never fetch a LinkedIn or "
    "Indeed URL: skip it and say so."
)


# Pages the model is never given a fetch rule for (the prompt tells it so, so the user is told it was skipped).
_NO_FETCH_NAMES = ("linkedin", "indeed")   # the name label of the host, any subdomain or country: not the host itself, which only discovery names


def _is_no_fetch(host: str) -> bool:
    return any(label in _NO_FETCH_NAMES for label in host.split("."))


def _twin(host: str) -> str:
    return host[4:] if host.startswith("www.") else "www." + host


# Profile sites a personal page may link to, each with the host its public data is read through (the prompt says how).
_PROFILE_HOSTS = {"github.com": ("github.com", "api.github.com"), "orcid.org": ("orcid.org", "pub.orcid.org")}


def _read_page(url: str) -> tuple[str | None, list[str]]:
    """The host the page at *url* ends on after its redirects, and its absolute links (one public, size-capped
    fetch), or ``(None, [])`` when it cannot be read."""
    import requests
    from bs4 import BeautifulSoup

    from door.scrapers.http_client import PoliteSession, RobotsBlocked

    try:
        resp = PoliteSession(min_delay=0.3, max_delay=0.6, timeout=15, max_retries=0).get(url)
        resp.raise_for_status()
    except (requests.RequestException, RobotsBlocked):
        return None, []
    soup = BeautifulSoup(resp.text, "html.parser")
    return (urlsplit(resp.url).hostname or "").lower() or None, [urljoin(resp.url, a["href"]) for a in soup.find_all("a", href=True)]


def _linked_hosts(url: str, links: list[str], site: str) -> list[str]:
    """The hosts of *links* (the page at *url*'s) that may be read beside it: GitHub and ORCID with their data hosts
    (`_PROFILE_HOSTS`), and, when *url* is a home page (the user's own site, not a profile on a shared one), the
    subdomains of *site* (its host without `www.`). Found here, by code."""
    home = urlsplit(url).path in ("", "/")
    hosts: list[str] = []
    for link in links:
        host = (urlsplit(link).hostname or "").lower()
        if host.removeprefix("www.") in _PROFILE_HOSTS:
            hosts += _PROFILE_HOSTS[host.removeprefix("www.")]
        elif home and host.endswith("." + site):
            hosts.append(host)
    return hosts


# A host a rule may name: plain DNS labels (a page's link could carry a comma, a space or an escape into the rule list).
_PLAIN_HOST = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+")


def webfetch_rules(urls: list[str]) -> tuple[str, ...]:
    """`WebFetch(domain:<host>)` for each page the user gave, built here and never by the model: the host, its
    www/apex twin and the host its address redirects to, read with its links in one fetch (a rule matches one host, no subdomains), with the data
    host of GitHub or ORCID (`_PROFILE_HOSTS`: `api.github.com`, `pub.orcid.org`, which the prompt reads them
    through); then what the given page links to (`_linked_hosts`). Only plain host names; none for LinkedIn and Indeed."""
    hosts: list[str] = []
    for url in urls:
        given = (urlsplit(url).hostname or "").lower()
        if not given or _is_no_fetch(given):
            continue
        landed, links = _read_page(url)
        for host in (given, landed):
            if host and not _is_no_fetch(host):
                hosts += [host, _twin(host), *_PROFILE_HOSTS.get(host.removeprefix("www."), ())]
        if given.removeprefix("www.") not in _PROFILE_HOSTS:
            hosts += [h for h in _linked_hosts(url, links, given.removeprefix("www.")) if not _is_no_fetch(h)]
    return tuple(f"WebFetch(domain:{h})" for h in dict.fromkeys(hosts) if _PLAIN_HOST.fullmatch(h))


def _resolve_job_ref(ref: str, jobs_dir: Path | None = None) -> str:
    """A job reference -> job id: words from its company and title ("trustpilot data"), or the id.

    Every core that takes a job id calls this first, so "prepare trustpilot" is one
    call on both surfaces (`selection.resolve_job_ref`, issue #312).

    Raises:
        AmbiguousJobRef: several jobs match (a ValueError carrying the ``candidates``).
        ValueError: nothing matches.
    """
    from door.core.jobs.selection import resolve_job_ref

    return resolve_job_ref(ref, jobs_dir if jobs_dir is not None else workspace.JOBS_DIR)


def _job_ref_cli(ref: str | None, jobs_dir: Path | None = None) -> str | None:
    """A command's job argument -> job id. No reference: pick from the jobs in play and the
    matches (`_pick_job`; None when there are none). Several matches: pick one of them on a
    terminal; elsewhere the `AmbiguousJobRef` error stands."""
    from door.commands import _prompts
    from door.core.jobs.selection import AmbiguousJobRef

    if ref is None:
        return _pick_job()
    try:
        return _resolve_job_ref(ref, jobs_dir)
    except AmbiguousJobRef as exc:
        if not _stdout_is_tty():
            raise
        return _prompts.select("job", f"Several jobs match {exc.ref!r}. Which one", choices=[
            (f"{c['title']} — {c['company']}  [{c['status']}]", c["job_id"]) for c in exc.candidates[:30]
        ])


def _job_label(job_id: str, jobs_dir: Path | None = None) -> str:
    """How the CLI names a job to the user: "<title> — <company>"; the id when the posting is not on disk."""
    from door.core.jobs.selection import find_posting

    posting = find_posting(jobs_dir if jobs_dir is not None else workspace.JOBS_DIR, job_id) or {}
    title, company = posting.get("title"), posting.get("company")
    if title and company:
        return f"{title} — {company}"
    return title or company or job_id


def job_words(posting: dict, jobs_dir: Path) -> str:
    """The shortest words (shell-quoted) that name *posting* uniquely: the company's first word,
    the whole company name, then company plus 1, 2, ... title words; the id when none is unique.
    Each candidate is checked with `selection.resolve_job_ref`."""
    import shlex

    from door.core.jobs.selection import _words, resolve_job_ref

    job_id = posting["id"]
    company, title = _words(posting.get("company") or ""), _words(posting.get("title") or "")
    candidates: list[list[str]] = []
    if company:
        candidates += [company[:1], company]
    candidates += [company + title[:k] for k in range(1, len(title) + 1)]
    tried: set[str] = set()
    for words in candidates:
        text = " ".join(words)
        if not text or text in tried:
            continue
        tried.add(text)
        try:
            if resolve_job_ref(text, jobs_dir) == job_id:
                return shlex.quote(text)
        except ValueError:  # ambiguous or nothing matches
            continue
    return shlex.quote(job_id)


# Statuses after which a job is no longer in play (`_pick_job` leaves them out).
_CLOSED_STATUSES = frozenset({"rejected", "offer", "discarded"})


def _pick_job() -> str | None:
    """Ask which posting to update: the ones in play first (by status, then
    score), then the unapplied matches at min_score; None when there are none."""
    from door.commands import _prompts
    from door.core.jobs import tracker as _tracker_mod
    from door.core.jobs.selection import select_matches

    jobs_dir = workspace.JOBS_DIR
    config = profile_loader.load_config_or_defaults(workspace.PROFILE_DIR)
    app_tracker = _tracker_mod.ApplicationTracker(jobs_dir / "applications.json")
    order = {label: i for i, label in enumerate(_tracker_mod.STATUSES)}
    tracked = [s for s in _tracker_mod.STATUSES if s != "unapplied" and s not in _CLOSED_STATUSES]
    in_play = sorted(select_matches(jobs_dir, app_tracker, 0.0, status=tracked),
                     key=lambda p: order[app_tracker.get_status(p["id"])])
    unapplied = _drop_stale(
        select_matches(jobs_dir, app_tracker, config.get("min_score", _DEFAULT_MIN_SCORE)),
        config.get("max_age_days", _DEFAULT_MAX_AGE_DAYS),
    )
    postings = in_play + unapplied
    if not postings:
        return None

    def label(posting: dict) -> str:
        current = app_tracker.get_status(posting["id"]) or "unapplied"
        return f"{posting.get('title', '')} — {posting.get('company', '')}  [{current}]"

    return _prompts.select("job", "Which posting", choices=[(label(p), p["id"]) for p in postings])



NoChromium = chromium.NoChromium
INSTALL_HINT = chromium.INSTALL_HINT


def _claude_available() -> bool:
    """Whether the `claude` CLI is on PATH or in ~/.local/bin (monkeypatched in tests)."""
    return installers.find_claude() is not None


def _chromium_available() -> bool:
    """Whether the pinned Chromium headless shell that prints CVs is installed (monkeypatched in tests)."""
    return chromium.find_chromium() is not None


def _with_progress(fn):
    """Route progress events to the core's ``progress=`` reporter for the call.

    The core takes a keyword-only ``progress=None``; while it runs, that
    reporter is active in `door.core.progress`, so everything below it
    (scrapers, passes, nested cores) reaches it through ``report()``.
    """
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with progress.activate(kwargs.get("progress")):
            return fn(*args, **kwargs)

    return wrapper


def _stdout_is_tty() -> bool:
    """Whether stdout looks like an interactive terminal.

    A monkeypatchable wrapper around ``sys.stdout.isatty()``: Click's
    ``CliRunner`` swaps stdout for a non-tty buffer, so tests exercise the TTY
    branch by patching this function.
    """
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _echo_config_error(exc: ConfigError) -> None:
    for line in exc.lines:
        click.echo(f"Error: {line}", err=True)


def _local_time(iso: str) -> str:
    """An ISO timestamp as local "YYYY-MM-DD HH:MM" for display."""
    from datetime import datetime

    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return str(iso)


# --------------------------------------------------------------------------- #
# The Claude plan's room (#575): `status_summary`'s `plan` block as one line
# --------------------------------------------------------------------------- #

_PLAN_WINDOWS = {"five_hour": "this 5-hour window", "seven_day": "this week's window"}


def _clock(iso: str) -> str:
    """An ISO timestamp as a local "HH:MM" today, else "Mon HH:MM"."""
    from datetime import datetime

    try:
        when = datetime.fromisoformat(iso).astimezone()
    except (TypeError, ValueError):
        return str(iso)
    return when.strftime("%H:%M" if when.date() == datetime.now().astimezone().date() else "%a %H:%M")


def _plan_window(plan: dict) -> tuple[str, dict] | None:
    """The window the plan block speaks of: the one that binds, else the first it has figures for."""
    for window in (plan.get("binding"), *_PLAN_WINDOWS):
        if window in _PLAN_WINDOWS and plan.get(window):
            return window, plan[window]
    return None


def _resets(figures: dict) -> str:
    return f" (resets {_clock(figures['resets_at'])})" if figures.get("resets_at") else ""


def _plan_used(plan: dict) -> str | None:
    """"42% of this 5-hour window used (resets 15:30)", or when it resets without a figure."""
    found = _plan_window(plan)
    if found is None:
        return None
    window, figures = found
    if "used" in figures:
        return f"{round(figures['used'] * 100)}% of {_PLAN_WINDOWS[window]} used{_resets(figures)}"
    if figures.get("resets_at"):
        return f"{_PLAN_WINDOWS[window]} resets {_clock(figures['resets_at'])}"
    return None


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _plan_line(plan: dict) -> str:
    """`jobs summary`'s line: a warning, the window's use, the room for finds and prepares, and
    as of when (`usage.room`'s block)."""
    parts = [plan["warning"]] if plan.get("warning") else []
    used = _plan_used(plan)
    if used:
        parts.append(used)
    room = plan.get("room")
    if room and plan.get("status") != "rejected":
        fits = [_count(room[kind], kind) for kind in ("find", "prepare") if room.get(kind) is not None]
        if fits:
            parts.append("room for about " + " or ".join(fits))
    parts.append(f"as of {_clock(plan['as_of'])}")
    return " · ".join(parts)


def _usd(amount: float) -> str:
    """Dollars and cents, "<$0.01" for a sliver above nothing."""
    if 0 < amount < 0.005:
        return "<$0.01"
    return f"${amount:,.2f}"


_SINGULAR = {"postings scored": "posting scored", "applications prepared": "application prepared",
             "other requests": "other request"}


def _cost_lines(cost: dict) -> tuple[str, list[tuple[str, str, str]]]:
    """`jobs summary`'s Claude usage block (`usage.cost`): the total line, then a row per activity
    (label, dollars, what it did), each followed by its features' rows (indented label, dollars,
    "") when it has more than one."""
    per = cost.get("per_run") or {}
    head = [f"about {_usd(cost['usd'])} in all" if cost["activities"] else f"nothing in the last {cost['days']} days"]
    head += [f"one {kind} about {_usd(per[kind])}" for kind in ("find", "prepare") if per.get(kind)]
    rows = []
    for a in cost["activities"]:
        rows.append((a["label"], _usd(a["usd"]),
                     f"{a['count']} {_SINGULAR.get(a['of'], a['of']) if a['count'] == 1 else a['of']}"))
        if len(a["features"]) > 1:
            rows += [(f"  {f['label']}", _usd(f["usd"]), "") for f in a["features"]]
    return " · ".join(head), rows


_PREPARE_ROOM_SHORT = 3  # at or below this many prepares left, `jobs prepare` says so first


def _prepare_room_line(plan: dict | None) -> str | None:
    """What `jobs prepare` says before it starts: only when the window has room for few more
    prepares, is close to its limit or has reached it; None otherwise."""
    if not plan:
        return None
    found = _plan_window(plan)
    resets = _resets(found[1]) if found else ""
    if plan.get("status") == "rejected":
        return f"{plan.get('warning') or "Claude's usage limit is reached"}{resets}."
    left = (plan.get("room") or {}).get("prepare")
    if left is not None and (left <= _PREPARE_ROOM_SHORT or plan.get("warning")):
        return f"This window has room for about {left} more prepare{'' if left == 1 else 's'}{resets}."
    if plan.get("warning"):
        return f"{plan['warning']}{resets}."
    return None


def _plan_use_line(plan: dict | None) -> str | None:
    """The line a `find` ends with: how full the plan's window is after the run."""
    used = _plan_used(plan) if plan else None
    return f"Claude plan: {used}" if used else None


# --------------------------------------------------------------------------- #
# Run records and "since last review" (issue #145)
# --------------------------------------------------------------------------- #

def _parse_iso(value) -> "datetime | None":
    """Parse an ISO-8601 timestamp (a trailing "Z" allowed) into an aware datetime."""
    from datetime import datetime, timezone

    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


_DEFAULT_MAX_AGE_DAYS = 30


def _drop_stale(matches: list[dict], max_age_days: int | None, now=None) -> list[dict]:
    """Postings no older than `max_age_days` (issue #146), by `posted_at`, else
    `scraped_at`; one with neither date is kept. `None` keeps everything."""
    from datetime import datetime, timedelta, timezone

    if max_age_days is None:
        return matches
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max_age_days)
    kept = []
    for posting in matches:
        when = _parse_iso(posting.get("posted_at")) or _parse_iso(posting.get("scraped_at"))
        if when is None or when >= cutoff:
            kept.append(posting)
    return kept


# One default for every command and for the `Profile` schema (a config that
# omits `min_score` gets the same threshold from `list`, `status`, `prepare`
# and `find`).
_DEFAULT_MIN_SCORE: float = Profile.model_fields["min_score"].default


def _format_elapsed(elapsed_s: float) -> str:
    """Format a duration in seconds as `<minutes>m<seconds>s`, e.g. `4m12s`."""
    total_seconds = int(round(elapsed_s))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}m{seconds}s"


def _load_json_tolerant(path: Path) -> dict:
    """Load a JSON object from `path`, tolerating a missing, corrupt or non-object file (``{}``)."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


# Rich rendering shared by `show`, `list` and `status`.
_SHOW_MAX_WIDTH = 100
_LIST_MAX_WIDTH = 140


def _console(max_width: int = _SHOW_MAX_WIDTH):
    """A rich console for `show`, `list` and `status`: colour only on a terminal, at most `max_width` wide."""
    import shutil

    from rich.console import Console

    width = min(shutil.get_terminal_size((80, 24)).columns, max_width)
    return Console(force_terminal=_stdout_is_tty(), highlight=False, width=width)


_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def plain(text) -> str:
    """Text that came from an ad, a page or the model, safe to print: control characters (a terminal escape
    that retitles the window, a bell) dropped, newlines and tabs kept."""
    return _CONTROL_RE.sub("", str(text if text is not None else ""))


def literal(text):
    """`plain(text)` as a rich `Text`, so what looks like markup ("[link=...]") prints as itself."""
    from rich.text import Text

    return Text(plain(text))


def _score_style(score: float | None) -> str:
    if score is None:
        return "dim"
    if score >= 0.7:
        return "green"
    if score >= 0.5:
        return "yellow"
    return "red"


def _score_text(score: float | None):
    """``███████░░░ 0.70``, coloured by how good the score is; ``?`` when unscored."""
    from rich.text import Text

    if score is None:
        return Text("?", style="dim")
    filled = round(max(0.0, min(1.0, score)) * 10)
    style = _score_style(score)
    return Text.assemble(("█" * filled, style), ("░" * (10 - filled), "dim"), (f" {score:.2f}", f"bold {style}"))


def _section(console, title: str) -> None:
    from rich.rule import Rule

    console.print()
    console.print(Rule(f"[bold]{title}[/]", align="left", style="dim"))


# The look every command's result shares (`show`, `add`, `prepare`, `find`, ...):
# ✓/⚠/✗ marks, a key/value grid with dim labels, `_section` rules, and copyable
# "Next" commands. Colour only on a terminal (`_console`).
_MARKS = {"ok": ("✓", "bold green"), "warn": ("⚠", "bold yellow"), "fail": ("✗", "bold red"), "info": ("·", "dim")}


def _mark(kind: str):
    """``✓`` (ok), ``⚠`` (warn), ``✗`` (fail) or ``·`` (info) as a styled rich Text."""
    from rich.text import Text

    glyph, style = _MARKS[kind]
    return Text(glyph, style=style)


def _mark_line(console, kind: str, text, *, indent: int = 2) -> None:
    """One ``  ✓ text`` line; ``text`` is a str (rich markup) or a rich Text."""
    from rich.text import Text

    body = text if isinstance(text, Text) else Text.from_markup(text)
    console.print(Text.assemble(" " * indent, _mark(kind), " ", body), soft_wrap=True)


def _kv_grid(rows):
    """A two-column grid, dim labels on the left: ``rows`` is ``[(label, value), ...]``
    (value a str or any rich renderable; rows whose value is None are left out)."""
    from rich.padding import Padding
    from rich.table import Table

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", no_wrap=True)
    grid.add_column(overflow="fold")
    for label, value in rows:
        if value is not None:
            grid.add_row(label, value)
    return Padding(grid, (0, 2))


def _next_steps(console, steps: list[tuple[str, str]]) -> None:
    """``Next  <command>  <what it does>`` lines, never wrapped so a command stays copyable."""
    for i, (command, hint) in enumerate(steps):
        label = "Next" if i == 0 else ""
        tail = f"  [dim]{hint}[/]" if hint else ""
        console.print(f"  [dim]{label:<8}[/] [bold]{command}[/]{tail}", soft_wrap=True)


def _display_path(path) -> str:
    """``path`` relative to the data home (``jobs/output/<id>/cv.pdf``), else to the repo, else as given."""
    p = Path(path)
    for base in (workspace.HOME, workspace.REPO_ROOT):
        try:
            return str(p.resolve().relative_to(Path(base).resolve()))
        except (ValueError, OSError):
            continue
    return str(path)
