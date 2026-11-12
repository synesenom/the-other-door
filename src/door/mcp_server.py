#!/usr/bin/env python3
"""Door MCP server — every CLI command as a typed MCP tool.

Each tool calls the same `_*_core` function the matching Click command in
`src/door/commands/<name>.py` calls, and returns its dict as-is. The CLI renders text
from that dict; this server hands it to the model. No logic is duplicated
between the two, and `CLI_COMMAND_TOOLS` below maps every command to its
tool(s) — `tests/commands/test_mcp_server.py` asserts the map covers every Click
command and, with `CONVERSATION_ONLY_TOOLS`, every registered tool, so the two
surfaces cannot drift.

Context economy: tools return paths, counts, ids and headline fields, never
full posting bodies — except `show`, the one tool that returns a posting's
description, on request.

Job references: every tool that takes a ``job_id`` also accepts words from
the job's company and title ("trustpilot", "novonesis head of ai"), so
"prepare the Trustpilot one" is one call. Several matching jobs come back as
``{"error", "candidates": [{"job_id", "title", "company", "status"}, ...]}``:
ask the user which (AskUserQuestion), then call again with that ``job_id``.

Errors: an expected failure (bad job_id, missing posting, invalid
profile/config.json, ...) comes back as
``{"error": "<message>"}`` with the wording the CLI prints after
``Error:``, not as a stack trace.

Long-running tools (`find_jobs`, `prepare`)
take minutes. MCP clients time tool calls out on their own side —
Claude Code aborts a stdio call after 30 minutes without a response
(`CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT`), with `MCP_TOOL_TIMEOUT` or a
per-server `timeout` in `.mcp.json` as the overall limit.

`find_jobs` and `prepare` are `async` tools: the core runs
in a worker thread so the event loop stays free, and the progress events it
reports (`door.core.progress`) go to the client as MCP progress
notifications (`ctx.report_progress`). The loop being free also means
`status_summary` answers during a run, with an `in_progress` block. Only one
of the two runs at a time; a second call comes back as an error at once.
stdout is the JSON-RPC stream, so nothing under `src/door/` prints.

Run directly for the `stdio` transport (the shape Claude Code's `.mcp.json`
expects):

    PYTHONPATH=src poetry run python -m door.mcp_server
"""

import asyncio
import functools
import inspect
import json
import threading
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP

from door import i18n
from door import version as version_mod
from door.core import path_scope
from door.commands import _common as common
from door.commands import add as add_cmd
from door.commands import ask as ask_cmd
from door.commands import archive as archive_cmd
from door.commands import compile as compile_cmd
from door.commands import companies as companies_cmd
from door.commands import matches as matches_cmd
from door.commands import prepare as prepare_cmd
from door.commands import query as query_cmd
from door.commands import report as report_cmd
from door.commands import cv as cv_cmd
from door.commands import enrich as enrich_cmd
from door.commands import gaps as gaps_cmd
from door.commands import salary as salary_cmd
from door.commands import keywords as keywords_cmd
from door.commands import preview as preview_cmd
from door.commands import titles as titles_cmd
from door.commands import market as market_cmd
from door.commands import profile as profile_cmd
from door.commands import revise as revise_cmd
from door.commands import find as find_cmd
from door.commands import setup as setup_cmd
from door.commands import status as status_cmd
from door.commands import stories as stories_cmd
from door.core import claude_cli, drive, problem_log, sync, workspace
from door.core.lock import LockHeldError, SyncConflict, ledger_lock, lock_holder
from door.core import companies as companies_store
from door.core.profile_loader import ConfigError
from door.core.tracker import DuplicateApplicationError

# Answers not logged: a background run's failure was logged when it ended (`job_result` only repeats it);
# a sent status's warning names the claims of the CV the materials make.
_UNLOGGED_ANSWERS = ("job_result", "set_status")


def _answer_of(result) -> dict | None:
    """The dict a tool answered, read back from FastMCP's converted result (its first text block)."""
    blocks = result[0] if isinstance(result, tuple) else result
    if isinstance(blocks, dict):
        return blocks
    for block in blocks or ():
        text = getattr(block, "text", None)
        if text is not None:
            try:
                answer = json.loads(text)
            except ValueError:
                return None
            return answer if isinstance(answer, dict) else None
    return None


def _log_answer(tool: str, answer: dict | None) -> None:
    """A tool's ``{"error"}`` and the warnings it returned, to the problem log (never its arguments)."""
    if not answer or tool in _UNLOGGED_ANSWERS:
        return
    if isinstance(answer.get("error"), str):
        problem_log.failure(f"tool {tool}", answer["error"])
    warnings = [answer.get("warning")] + list(answer.get("warnings") or [])
    for warning in warnings:
        if isinstance(warning, str) and warning:
            problem_log.warning(f"tool {tool}", warning)


class _DoorMCP(FastMCP):
    """FastMCP whose every tool call is the one place a failure is logged (#593): over stdio and HTTP alike."""

    async def call_tool(self, name, arguments):
        try:
            result = await super().call_tool(name, arguments)
        except Exception as exc:
            problem_log.crash(f"tool {name}", exc.__cause__ or exc)  # FastMCP wraps it in a ToolError
            raise
        _log_answer(name, _answer_of(result))
        return result


mcp = _DoorMCP("door")
# Its version in `initialize` (FastMCP takes none): the desktop app refuses a server of another version (#224).
mcp._mcp_server.version = version_mod.VERSION

# Every CLI command (sub-commands as "group sub") and the MCP tool(s) that
# expose it. `status` is two tools because the command is two operations:
# set a status (two arguments) or print the summary (none). `init` is three:
# with flags it is `init_profile`; without, its wizard asks what `draft_cv`
# and `keywords` take as arguments.
CLI_COMMAND_TOOLS = {
    # `find` is five steps: the `find_jobs` tool's `step` picks one (none: all of them, minus `skip`).
    "find search": ("find_jobs",),
    "find discover": ("find_jobs",),
    "find follow": ("find_jobs",),
    "find collect": ("find_jobs",),
    "find match": ("find_jobs",),
    "jobs list": ("list_matches",),  # also what bare `jobs` runs
    "jobs show": ("show",),
    "jobs status": ("set_status",),
    "jobs summary": ("status_summary",),
    "jobs prepare": ("prepare",),
    "jobs add": ("import_posting",),
    "jobs query": ("query_jobs",),
    "jobs salary": ("salary_estimate",),
    "init": ("init_profile", "draft_cv", "infer_basics", "keywords", "show_profile"),  # the wizard's reading step
    "cv enrich": ("enrich",),
    "cv gaps": ("skill_gaps",),
    "cv titles": ("suggest_titles",),
    "cv stories list": ("list_stories",),
    "cv stories add": ("save_story",),
    "cv stories remove": ("remove_story",),
    "cv stories draft": ("draft_stories",),
    "market": ("market",),
    "ask": ("ask",),
    "doctor": ("doctor", "setup"),  # `doctor --fix` is `setup`
    "companies list": ("list_companies",),
    "companies add": ("add_company",),
    "companies remove": ("remove_company",),
    "companies merge": ("merge_companies",),
    "companies why": ("why_company",),
    "data export": ("export_data",),
    "data import": ("import_data",),
    "data report": ("report_problem",),
    "data connect": ("connect_drive",),
    "data sync": ("sync_data",),
    "data disconnect": ("disconnect_drive",),
}

# Tools with no command: the conversation (or an agent) is their only caller.
# `revise` and `mark_reviewed` are what a user says ("tighten the second
# paragraph", "I'm done"); `mark_seen` is the desktop app opening a posting; `compile` is the tailor agent's, and `revise`
# recompiles itself, so a .tex never changes without its PDF. `save_cv` is the
# desktop app's wizard putting the reviewed CV in place; `init`'s CV step is its shell twin.
CONVERSATION_ONLY_TOOLS = (
    "revise", "mark_reviewed", "mark_seen", "compile", "save_cv", "job_result", "cancel_job",
    "save_photo", "remove_photo",  # the CV photo: the app's picker, `/onboard` and `init`'s photo question
    "preview_matches",  # onboarding's first look; `init` calls the core itself
    # the phone server, for the desktop app's "Set up your phone" and Claude Code (#444, #424)
    "phone_status", "phone_start", "phone_stop", "pair_phone", "unpair_phone",
)

# Commands with no tool: `serve` runs this server over HTTP and manages who may call it (#302); a tool
# that started or paired the server it is called through would mean nothing.
CLI_ONLY_COMMANDS = ("serve start", "serve pair", "serve devices", "serve unpair", "serve install-agent", "serve uninstall-agent")

# Every tool, once: the ones that only read (what `ask` may hand its model, `commands/ask.ASK_TOOLS`)
# and the ones that can write profile/, jobs/ or elsewhere, or act on the computer (doctor saves drift
# probes; keywords, market and skill_gaps can save; show opens the PDF viewer and renders page images). A new tool goes in one of the two; a test fails until it does.
READ_ONLY_TOOLS = frozenset({
    "status_summary", "list_matches", "show_profile", "query_jobs", "list_companies", "why_company", "ask", "job_result", "phone_status", "suggest_titles", "infer_basics", "preview_matches",
    "list_stories", "draft_stories",
})
WRITING_TOOLS = frozenset({
    "find_jobs", "cancel_job", "phone_start", "phone_stop", "pair_phone", "unpair_phone", "set_status", "prepare", "import_posting", "revise", "compile", "mark_reviewed", "mark_seen", "init_profile",
    "keywords", "save_cv", "save_photo", "remove_photo", "draft_cv", "enrich", "skill_gaps", "market", "salary_estimate", "doctor", "setup", "add_company",
    "remove_company", "merge_companies", "save_story", "remove_story", "export_data", "import_data", "report_problem", "connect_drive", "sync_data", "disconnect_drive",
    "show",  # opens the PDF viewer with `open`, and renders missing page images under jobs/output/
})

# Exceptions the cores raise for bad input or state. They come back to the
# model as ``{"error": "<message>"}`` — the same wording the CLI prints after
# ``Error: `` — rather than as a stack trace. Anything else is a bug and
# propagates.
# Config keys naming a file the tailor reads (`init_profile`'s `other`): kept inside the data folder.
_PATH_KEYS = ("cv_content", "cv_template", "cover_letter_template", "photo")

_EXPECTED_ERRORS = (
    ValueError,
    LookupError,
    FileNotFoundError,
    FileExistsError,  # `export` never overwrites an archive
    ConfigError,
    companies_store.CompaniesError,  # profile/companies.json is malformed
    DuplicateApplicationError,
    LockHeldError,  # a `find` run (or another writer) holds jobs/.lock
    drive.DriveError,  # Google Drive: not connected, offline, revoked, not configured in this build
    SyncConflict,  # Drive and this computer both changed
    revise_cmd.ReviseError,  # the `revise` claude -p call failed
    claude_cli.ClaudeError,  # a `claude -p` call (keywords, …) failed
)


def _with_supported_languages(fn):
    """Fill ``{supported_languages}`` in ``fn``'s docstring (the tool description
    the model reads) with the languages that have a file in ``i18n/lang/``, so
    adding a language needs no edit here. Other braces are left alone."""
    fn.__doc__ = fn.__doc__.replace("{supported_languages}", i18n.supported_language_names())
    return fn


def _tool_errors(fn):
    """Turn an expected core exception into ``{"error": str(exc)}`` (sync or async tools)."""

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except _EXPECTED_ERRORS as exc:
                return _error(exc)

        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except _EXPECTED_ERRORS as exc:
            return _error(exc)

    return wrapper


def _error(exc: Exception) -> dict:
    """``{"error": message}``, plus the ``candidates`` of an ambiguous job reference."""
    from door.core.selection import AmbiguousJobRef

    from door.core.lock import SyncConflict

    if isinstance(exc, AmbiguousJobRef):
        return {"error": str(exc), "candidates": exc.candidates}
    if isinstance(exc, SyncConflict):
        # Both sides changed: the caller asks which to keep (sync_data's keep_local / keep_drive).
        return {"error": str(exc), "conflict": True}
    return {"error": str(exc)}


_BUSY = (
    "another long-running tool (find_jobs or prepare) is already in progress; "
    "wait for it to finish before calling again"
)

# One lock for the two long tools, re-created for each running event loop (a
# test calling `asyncio.run` repeatedly would otherwise hit a cross-loop error).
_serial = {"loop": None, "lock": None}


def _serial_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    if _serial["loop"] is not loop:
        _serial["loop"], _serial["lock"] = loop, asyncio.Lock()
    return _serial["lock"]


class _McpBridge:
    """A progress `Reporter` that forwards events to ``ctx.report_progress``.

    ``report`` is called from the worker thread running the core, so it only
    queues; `pump` (a task on the event loop) sends them one at a time, in
    order. MCP wants ``progress`` to grow with every notification, so it is a
    running event count (``total`` is unknown, and events from different
    stages have unrelated counters) with the event's line as the message. A
    client that errors or disconnects is ignored: progress is best effort.
    """

    def __init__(self, ctx, loop: asyncio.AbstractEventLoop):
        self._ctx = ctx
        self._loop = loop
        self._queue: asyncio.Queue = asyncio.Queue()
        self._count = 0
        self._guard = threading.Lock()

    def report(self, event) -> None:
        with self._guard:
            self._count += 1
            item = (float(self._count), event.line)
        self._loop.call_soon_threadsafe(self._queue.put_nowait, item)

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._queue.put_nowait, None)

    async def pump(self) -> None:
        while (item := await self._queue.get()) is not None:
            try:
                await self._ctx.report_progress(item[0], None, item[1])
            except Exception:  # noqa: BLE001 — a client error must not fail the tool
                pass


class _Cancelled(BaseException):
    """Raised from the next progress event of a run `cancel_job` stopped (a BaseException: nothing on
    the way swallows it, and every `with` block it leaves still cleans up)."""


class _CancelReporter:
    """Hands events on to `inner` (if any) until the run is cancelled; then the next one raises."""

    def __init__(self, cancel: threading.Event, inner=None):
        self._cancel = cancel
        self._inner = inner

    def report(self, event) -> None:
        if self._cancel.is_set():
            raise _Cancelled()
        if self._inner is not None:
            self._inner.report(event)


# The long tools' runs, for `job_result` and `cancel_job`. Over HTTP (`door serve`, #302) a run is a
# task of the server's own and the call returns at once: a phone sleeps, a tunnel cuts long requests.
_runs: dict = {"background": False, "running": None, "cancel": None, "task": None, "last": {}}
_LONG_TOOLS = ("find_jobs", "prepare")


def _runs_reset(*, background: bool = False) -> None:
    _runs.update(background=background, running=None, cancel=None, task=None, last={})


def enable_background_runs() -> None:
    """`door serve` calls this: from now on the long tools start their run and return."""
    _runs["background"] = True


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def _run_long(ctx, core, *args, tool: str = "find_jobs", **kwargs):
    """Run a core in a worker thread, one long tool at a time, streaming its progress to ``ctx``.

    ``progress=`` is only passed to the core when there is a ``ctx`` to
    forward to, so a tool called without one behaves as it always did.
    With background runs on (`door serve`) the run is started and
    ``{"started", "tool", "started_at"}`` comes back at once.
    """
    lock = _serial_lock()
    if lock.locked():
        return {"error": _BUSY}
    await lock.acquire()
    cancel = threading.Event()
    started_at = _now_iso()
    _runs.update(running={"tool": tool, "started_at": started_at}, cancel=cancel)

    def finish(outcome: dict) -> None:
        _runs["last"][tool] = {"tool": tool, "started_at": started_at, "finished_at": _now_iso(), **outcome}
        _runs.update(running=None, cancel=None)
        lock.release()

    if _runs["background"]:
        async def body():
            try:
                result = await asyncio.to_thread(functools.partial(core, *args, progress=_CancelReporter(cancel), **kwargs))
                outcome = {"result": result}
            except _Cancelled:
                outcome = {"cancelled": True}
            except Exception as exc:  # noqa: BLE001 - the run's failure is its result
                outcome = _error(exc)
                problem_log.failure(f"tool {tool}", outcome["error"])
            finish(outcome)

        _runs["task"] = asyncio.create_task(body())
        return {"started": True, "tool": tool, "started_at": started_at}

    try:
        if ctx is None:
            result = await asyncio.to_thread(functools.partial(core, *args, **kwargs))
        else:
            bridge = _McpBridge(ctx, asyncio.get_running_loop())
            pump = asyncio.create_task(bridge.pump())
            try:
                result = await asyncio.to_thread(functools.partial(core, *args, progress=_CancelReporter(cancel, bridge), **kwargs))
            finally:
                bridge.close()
                await pump
    except _Cancelled:
        finish({"cancelled": True})
        return {"error": "the run was stopped", "cancelled": True}
    except BaseException as exc:
        finish(_error(exc) if isinstance(exc, Exception) else {"cancelled": True})
        raise
    finish({"result": result})
    return result


@mcp.tool()
async def job_result(tool: str = "find_jobs") -> dict:
    """The last run of a long tool (find_jobs or prepare): whether it still runs, and how the last one ended.

    Over `door serve` (a phone) those tools start their run and return at
    once; this is where the run's answer is collected. Its progress is
    `status_summary`'s `in_progress`.

    Args:
        tool: find_jobs or prepare.

    Returns:
        ``{"tool", "running"}``, plus ``started_at`` while it runs; after a
        run, ``started_at``, ``finished_at`` and its ``result`` (what the tool
        returns over stdio), or ``cancelled``, or ``error``.
    """
    if tool not in _LONG_TOOLS:
        return {"error": f"not a long tool: {tool} (find_jobs or prepare)"}
    running = _runs["running"]
    if running and running["tool"] == tool:
        return {"tool": tool, "running": True, "started_at": running["started_at"]}
    last = _runs["last"].get(tool)
    return {"running": False, **last} if last else {"tool": tool, "running": False}


@mcp.tool()
@_tool_errors
def phone_status() -> dict:
    """Whether The other door is serving this data folder to a phone, where, over what, and which phones are paired.

    Returns:
        ``{"running", "devices", "web_built", "tailscale_installed"}``, plus
        ``"connection"`` (cloudflare or tailscale), ``"address"``, ``"port"`` and
        ``"lasting"`` (Tailscale's address never changes; a quick tunnel's does)
        while it runs.
    """
    from door.core import phone

    return phone.status(workspace.HOME)


@mcp.tool()
@_tool_errors
async def phone_start(connection: str = "cloudflare") -> dict:
    """Serve this data folder to a phone: `door serve` plus a connection the phone can reach.

    Args:
        connection: "cloudflare" (a quick tunnel: nothing to install and no
            account, but the address changes on restart, when the phone scans a
            new code) or "tailscale" (a lasting, private address; Tailscale on
            this computer and the phone, the same account).

    Returns:
        `phone_status`'s answer; or ``{"needs": "install_tailscale" |
        "sign_in_tailscale" | "enable_https", "link"}`` for a step the user
        takes (the link says where); or ``{"error"}``.
    """
    from door.core import phone

    return await asyncio.to_thread(phone.start, workspace.HOME, connection)


@mcp.tool()
@_tool_errors
def phone_stop() -> dict:
    """Stop serving this data folder to phones (the server, the connection, keeping the Mac awake)."""
    from door.core import phone

    return phone.stop(workspace.HOME)


@mcp.tool()
@_tool_errors
def pair_phone(device: str) -> dict:
    """A QR code that pairs one phone with this data folder: show it on this screen; the phone's camera opens it.

    The code inside is long (about 2^119), works once and only for five
    minutes; it is never returned as text, and the phone's own token never
    passes through here.

    Args:
        device: A name for the phone ("Ada's Pixel").

    Returns:
        ``{"device", "qr_svg", "expires_at"}`` (an SVG to show), or ``{"error"}`` when
        nothing is serving or the name is already paired.
    """
    from door.core import phone

    return phone.pair(workspace.HOME, device)


@mcp.tool()
@_tool_errors
def unpair_phone(device: str) -> dict:
    """Take a phone away (`serve unpair`): its token stops working at once.

    Returns:
        ``{"removed": device}``, or ``{"error"}`` when no phone has that name.
    """
    from door.core import phone

    return phone.remove(workspace.HOME, device)


@mcp.tool()
async def cancel_job() -> dict:
    """Stop the running find_jobs or prepare (it stops at its next step; nothing is lost: the next run picks up).

    Returns:
        ``{"cancelling": tool}``, or ``{"error"}`` when nothing runs.
    """
    running, cancel = _runs["running"], _runs["cancel"]
    if not running or cancel is None:
        return {"error": "nothing is running"}
    cancel.set()
    return {"cancelling": running["tool"]}


@mcp.tool()
@_tool_errors
def compile(job_id: str, render: bool = False) -> dict:
    """Compile LaTeX sources for a job application into PDFs.

    The tailor agent's tool (`revise` recompiles on its own); there is no
    command, since PDFs are never built by hand.

    Args:
        job_id: The job: its id, or words from its company and title
            ("trustpilot").
        render: Also render each compiled PDF's pages to PNGs (read them to
            see the pages), with page counts.

    Returns:
        The output directory and a per-file compile result (compiled/
        skipped/error, with the resulting PDF path or compiler stderr); with
        ``render``, also ``"render": [{"file", "status", "pages",
        "page_count"}, ...]``.
    """
    return compile_cmd._compile_core(job_id, render=render, jobs_dir=workspace.JOBS_DIR)


@mcp.tool()
@_tool_errors
def set_status(job_id: str, status: str, notes: str | None = None, at: str | None = None) -> dict:
    """Set the application status for a job posting.

    "Applied" → ``status="applied"``; "not this one" → ``status="discarded"``
    with the user's reason in ``notes`` (`list_matches` hides it afterwards).
    Identical to `./door jobs status <job_id> <status> [--notes ...] [--at ...]`.
    These records feed the analysis of which applications pass, so: when the
    user says it happened on another day ("I applied on the 3rd", "the
    screening was last week"), pass ``at``. Relay a returned ``warning`` (the
    ad is not on disk or is only a snippet) in one line.

    Args:
        job_id: The job: its id, or words from its company and title ("trustpilot").
        status: One of: unapplied, prepared, applied, interview:screening
            (pre-screening, recruiter/HR call), interview:impression (first
            non-technical interview), interview:assessment (personality or
            cognitive test), interview:technical (technical interview, case
            or take-home), ghosted ("they stopped answering"), rejected,
            offer, discarded. One interview:<kind> per round; rejected or
            ghosted ends the last one. When the user doesn't say which kind
            of interview, ask with the four as options.
        notes: Optional notes, stored with the ledger entry and its history:
            why (a discard's reason), or for an interview what it covered, what
            was said, what felt weak, any feedback.
        at: When it happened, ``YYYY-MM-DD`` (or an ISO datetime); omitted
            is now. An event dated before the latest one is filed in date
            order and leaves the current status.

    Returns:
        ``{"job_id", "status", "notes", "at", "current",
        "sent_dir"?, "warning"?}`` once the ledger at `jobs/applications.json`
        has been updated: ``current`` is the job's status now, ``sent_dir``
        the copy of the materials taken when the application was first sent.
    """
    return status_cmd._set_status_core(job_id, status, notes, jobs_dir=workspace.JOBS_DIR, at=at)


@mcp.tool()
@_tool_errors
async def find_jobs(
    step: str | None = None,
    skip: list[str] | None = None,
    boards: list[str] | None = None,
    company: list[str] | None = None,
    dry_run: bool = False,
    ctx: Context | None = None,
) -> dict:
    """Find new jobs and score them: search -> discover -> follow -> collect -> match (or one step of it).

    The usual way to fetch fresh jobs when the user asks ("get me today's
    jobs"), and the only one. Five steps, in this order: `search` (the job
    boards with the profile's keywords; their employers are queued),
    `discover` (LinkedIn shows which employers hire for the keywords; skipped
    while it rests after a refusal), `follow` (finds each queued employer's
    own job feed and records it in profile/companies.json), `collect` (reads
    every followed employer's feed: a posting is new when The other door has not seen
    it before), `match` (filters, dedups, scores every unscored posting with
    Haiku, including any an interrupted earlier run left, so calling it again
    resumes, and picks the matches). Takes minutes, `collect` the longest;
    the per-site cap is profile/config.json's `max_postings_per_site`. Boards
    are read since their last search (at most `max_age_days` back); matches
    are picked at the profile's `min_score`.

    Args:
        step: Run just this step: search, discover, follow, collect or
            match. Omit to run all five.
        skip: Steps to leave out of a full run (not with `step`).
        boards: `search` only: boards to search instead of every board of the
            profile's country (jobindex, thehub, workable).
        company: `collect` only: collect just these followed employers
            (names as `list_companies` shows them).
        dry_run: `follow` only: show what would be recorded, write nothing.

    Returns:
        ``{"started_at", "finished_at", "elapsed_s", "steps", "skipped",
        "search", "discover", "follow", "collect", "match", "new_above_threshold",
        "top", "failures"}`` — a run record
        identical to the one written under jobs/runs/ (a block per step that
        ran, None for the others; each has a "summary").
    """
    return await _run_long(
        ctx,
        find_cmd._find_core,
        step,
        skip=skip or (),
        boards=boards,
        companies=company,
        dry_run=dry_run,
        jobs_dir=workspace.JOBS_DIR,
        profile_dir=workspace.PROFILE_DIR,
    )


@mcp.tool()
@_tool_errors
def list_matches(
    score: float | None = None,
    new_only: bool = False,
    status: str | None = None,
    ongoing: bool = False,
    closed: bool = False,
) -> dict:
    """List job matches, best first — ids and headline fields only, never descriptions.

    Like `./door jobs`, except that without `score` it stops at the config's
    min_score (the shell's default is anything above 0), so a review session
    sees the matches, not every scored posting. Use `show` for one posting's
    full text. Refer to postings by title and company when talking to the
    user; pass the ``id`` (or the user's words) to the next tool.

    Args:
        score: Only matches scoring at least this (default: profile/config.json's
            min_score).
        new_only: Only postings first seen since the last `mark_reviewed`
            — the answer to "anything new since I last looked?".
        status: Only postings with this status (``unapplied``, ``prepared``,
            ``applied``, ``interview:screening``, ``interview:impression``,
            ``interview:assessment``, ``interview:technical``, ``ghosted``,
            ``rejected``, ``offer``, ``discarded``) instead of the ones not yet
            acted on; "what did I apply to?". They
            stay listed however old, and `score` defaults to anything above 0.
        ongoing: Only postings still in play (``prepared``, ``applied``,
            any ``interview:<kind>``, ``offer``) — "what's in progress?"; listed like
            `status`, and not together with it.
        closed: Only applications that ended (``rejected``, ``ghosted``, or
            ``discarded`` after being prepared or sent) — "which ones didn't work out?".

    Returns:
        ``{"min_score", "last_reviewed_at", "matches": [{"id",
        "score", "title", "title_en", "company", "location", "status",
        "is_new", "updated_at", "rounds"}, ...]}``, best first; ``updated_at`` is
        when the status last changed, ``rounds`` the interview rounds ``[{"stage", "result"}]``. ``title_en`` is the English
        translation of a title in another language, else ``None``: show it
        next to the title. ``scored`` is how many postings the model has scored. ``weak`` is
        None, or, when no posting has ever reached the bar (default view only), ``{"matches": [the best
        3 below it, rows like the above], "hint": "sources" | "keywords", "sources": [{"key", "label"}]}``:
        present them as weak matches, not as matches, and say the hint (more discovery sources
        serving the city are off, or broaden the search keywords).
    """
    return matches_cmd._list_core(
        min_score=score,
        jobs_dir=workspace.JOBS_DIR,
        profile_dir=workspace.PROFILE_DIR,
        new_only=new_only,
        status=status,
        ongoing=ongoing,
        closed=closed,
    )


@mcp.tool()
@_tool_errors
def show(job_id: str, open: bool = False) -> dict:
    """Return one posting in full — the only tool that returns a description —
    plus, once prepared, everything needed to judge its materials.

    Call it after `prepare` or `revise` to summarise the result: PDF paths,
    page PNG paths (rendered first if missing — read them to see the
    pages), the keywords the tailor emphasised (`% Keywords:` in cv.tex),
    what it cut, kept or condensed per section (`% Tailoring:`), page
    counts and the cover letter's word count. Identical to
    `./door jobs show <job_id> [--open]`.

    Args:
        job_id: The job: its id, or words from its company and title ("trustpilot").
        open: Also open both PDFs in the default viewer of the machine
            hosting the server (`show --open`); only useful on a desktop.

    Returns:
        The posting's fields (title, title_en, company, location, url,
        description, score, score_reason, language, language_requirement,
        ...) plus its ledger ``status``, ``history`` (every status change,
        oldest first: ``{"status", "at", "notes"?, "result"?}``, ``result``
        on each interview round: passed, rejected, ghosted, withdrawn or
        pending) and ``materials``: null until
        prepared, else ``{"output_dir", "pdfs", "pngs", "keywords",
        "tailoring", "page_counts", "cover_letter_words", "rendered", "file_names", "sent"}``
        (``file_names``: what to save each PDF as, the candidate's name first);
        ``sent`` true once the application went out, and then the files are the
        copy taken when it was sent (what the employer has), not ones a later
        ``revise`` changed. ``salary`` is the saved estimate (`salary_estimate`'s
        fields, from ``low`` to ``as_of``) or null; `show` never asks for one.
    """
    return matches_cmd._show_core(job_id, open=open, jobs_dir=workspace.JOBS_DIR)


@mcp.tool()
@_tool_errors
def status_summary() -> dict:
    """Pipeline counts and the applications-ledger breakdown.

    Identical to `./door jobs summary`. A good first
    call in a review session: it says how many postings are on disk, how
    many clear min_score, and how many are still unapplied.

    Returns:
        ``{"min_score", "pipeline": {"total", "excluded", "applicable",
        "above_threshold", "unapplied", "above_threshold_by_status":
        {"unapplied", "prepared", "applied", "discarded"}}, "ledger": {<each status>: count}, "interviews":
        {<stage>: {"passed", "rejected", "ghosted", "withdrawn", "pending"}}, "since_last_review":
        {"last_reviewed_at", "runs", "last_run", "new_matches",
        "site_failures"}, "in_progress": None | {"purpose", "pid",
        "started_at", "message", "done", "total", "site", "stage",
        "updated_at"}}`` — ``since_last_review`` says what the
        runs did since the last `mark_reviewed`, without re-scraping.
        ``in_progress`` is set while a `find` run is going (here or in
        another terminal) and says how far it is — its latest progress event;
        it is null when nothing is running. ``drive`` is ``{"connected",
        "account", "last_synced", "last_error"}``: whether Google Drive sync
        is on, and the last time it worked or why it did not (mention a
        ``last_error`` briefly; do not try to fix it unasked). ``recurring_problem``
        is true when something keeps going wrong (a site failing run after run,
        scoring failing, the server crashing, a tool failing again and again) since
        the last problem report: offer `report_problem` to the user. ``plan`` is null
        until a call has read the Claude plan, then ``{"as_of", "status", "five_hour":
        {"used", "resets_at"}, "seven_day": {...}, "room": {"find", "prepare"} | null,
        "binding", "warning"?, "week": {"activities": [{"label", "share", "count", "of"}],
        "heaviest"}}``: how full the plan's 5-hour and 7-day windows were after the latest
        call (``used`` a 0-1 fraction), about how many more finds and prepares fit before
        the window that binds is full (null until this computer has measured enough), and
        what used the plan this week. It is an estimate as of ``as_of``: the user's own
        Claude chats since then are not in it. Mention it when ``warning`` is set or room is
        short; answer "can I prepare three more?" or "why did I hit my limit?" from it.
    """
    return status_cmd._status_summary_core(jobs_dir=workspace.JOBS_DIR, profile_dir=workspace.PROFILE_DIR)


@mcp.tool()
@_tool_errors
async def prepare(
    job_id: str | None = None, force: bool = False, timeout_min: float = 20, ctx: Context | None = None
) -> dict:
    """Tailor a CV and cover letter for one posting and mark it "prepared".

    Runs the tailor agent through `claude -p` (minutes, not seconds — the
    call blocks until it finishes or `timeout_min` passes). The status only
    becomes "prepared" once posting.json, cv.tex, cover_letter.tex, cv.pdf
    and cover_letter.pdf are all in `jobs/output/<job_id>/`. Identical to
    `./door jobs prepare [job_id]`. Then call `show` to summarise the materials.
    A prepared job also gets its salary estimate (`salary_estimate`, one Haiku web
    search, reused while under 90 days old; skipped when the plan is close to its limit):
    mention the range as an estimate with its sources; say nothing when it is null.

    Args:
        job_id: The job: its id, or words from its company and title ("trustpilot").
            Omit for the single highest-scoring unapplied match.
        force: Regenerate even if complete materials already exist.
        timeout_min: Minutes to wait for the tailor agent.

    Returns:
        ``{"job_id", "outcome": "prepared" | "skipped" | "failed",
        "output_dir", "files", "regenerated_incomplete", "error"?,
        "missing"?, "salary"?}`` (``salary``: the estimate or null), or ``{"job_id": None, "outcome": "no_matches"}``
        when `job_id` is omitted and nothing clears min_score.
    """
    return await _run_long(
        ctx, prepare_cmd._prepare_core, job_id, force, timeout_min * 60, tool="prepare",
        jobs_dir=workspace.JOBS_DIR, profile_dir=workspace.PROFILE_DIR,
    )


@mcp.tool()
@_tool_errors
def show_profile() -> dict:
    """Read the profile in one call: the validated config (or the `errors` lines when it is invalid or missing),
    the CV text with its headline and sections, which of the CV, the two templates and the story bank are still
    profile.example/'s (`is_example`), the enrich sources, and `options` for a profile form (the known `cities`
    with their country and boards, the supported `languages`, the `worldwide_boards`). Read-only; never fails on
    a fresh folder."""
    from door.commands import profile as profile_cmd

    return profile_cmd._show_profile_core()


@mcp.tool()
@_tool_errors
@_with_supported_languages
def init_profile(
    name: str | None = None,
    email: str | None = None,
    location: str | None = None,
    languages: list[str] | None = None,
    role_targets: list[str] | None = None,
    search_keywords: list[str] | None = None,
    topic_terms: list[str] | None = None,
    remote: str | None = None,
    min_score: float | None = None,
    exclude_companies: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
    other: dict | None = None,
) -> dict:
    """Create or update profile/config.json — the non-interactive `init`.

    Ask the user for the values first, then call this once. Missing files
    from profile.example/ (except its example CV and story bank) are copied into
    profile/ (never overwritten);
    the given fields are merged over the current config (or the example
    one on a fresh clone); the result is validated before anything is
    written. Only the arguments you pass change, except that the current
    config's invalid keys you do not pass are dropped (named in `dropped`:
    tell the user).

    Args:
        name: Candidate's full name.
        email: Candidate's email.
        location: City/region to search in (e.g. "Copenhagen"); every job board
            of its country is searched.
        languages: The job-ad languages to consider, any of the supported
            ones: {supported_languages} (the candidate's own language levels
            go in the CV).
        role_targets: Job titles to look for (at least one).
        search_keywords: Broader search terms (default: role_targets).
        topic_terms: Words and phrases that make a job title relevant, in every
            ad language (from `keywords`; default: any word of the keywords).
        remote: "yes", "no" or "hybrid".
        min_score: Match threshold, 0-1.
        exclude_companies: Companies to skip.
        exclude_keywords: Keywords that disqualify a posting.
        other: Any other profile/config.json key, e.g.
            {"max_age_days": 14} or {"min_score": 0.7}
            (`init --set key=value` in a shell).

    Returns:
        ``{"config_path", "copied": [path, ...], "dropped": [key, ...], "disclaimers": [{"key", "text"}, ...]}``,
        or ``{"error": ...}`` with one line per invalid field. A source turned on (`other`, e.g.
        ``{"linkedin_discovery": true}``) comes back with its disclaimer in `disclaimers`: show each text to
        the user verbatim. A source stays off unless the user chose it.
    """
    for key in _PATH_KEYS:  # the tailor reads these files: never one outside the data folder
        if isinstance((other or {}).get(key), str):
            path_scope.check(other[key])
    fields = profile_cmd._profile_fields(
        name=name, email=email, location=location, languages=languages, role_targets=role_targets,
        search_keywords=search_keywords, topic_terms=topic_terms, remote=remote, min_score=min_score,
        exclude_companies=exclude_companies, exclude_keywords=exclude_keywords, other=other,
    )
    return profile_cmd._init_core(fields, profile_dir=workspace.PROFILE_DIR, example_dir=workspace.PROFILE_EXAMPLE_DIR)


@mcp.tool()
@_tool_errors
def keywords(
    role_targets: list[str] | None = None, languages: list[str] | None = None, save: bool = False,
    model: str | None = None,
) -> dict:
    """Propose job-board search terms (`search_keywords`) and title terms (`topic_terms`) from the role targets.

    "Expand my search keywords": one `claude -p` call (Haiku by default)
    proposes 8-15 short terms per job-ad language — each target verbatim, noun
    forms, abbreviations, seniority variants, close synonyms — and the words that
    make a job title relevant (`topic_terms`: the field, its subjects and neighbours,
    never a bare role noun like "analyst"). Show both to the user and confirm (use
    all / drop some / add some); then save the final lists with
    `init_profile(search_keywords=..., topic_terms=...)`, or call this again with
    `save=True` when they take them all. The same call as `./door init`'s
    keywords step.

    Args:
        role_targets: Titles to propose from. Omit for profile/config.json's
            `role_targets`.
        languages: The job-ad languages the terms are given in, besides English
            (`["Hungarian"]`). Omit for profile/config.json's `languages`.
        save: Also write the proposed terms to `search_keywords` and `topic_terms`.
        model: Claude model to ask (default: haiku).

    Returns:
        ``{"role_targets", "keywords", "topic_terms", "saved"}`` plus
        ``"config_path"`` when saved.
    """
    return keywords_cmd._keywords_core(
        role_targets, languages=languages, save=save, model=model, profile_dir=workspace.PROFILE_DIR)


@mcp.tool()
@_tool_errors
def suggest_titles(
    titles: list[str] | None = None, hint: str | None = None, languages: list[str] | None = None, model: str | None = None,
) -> dict:
    """Suggest job titles from the CV and the career progression. "What titles should I look for?"

    One `claude -p` call (Haiku by default) reads `profile/cv.draft.md` (while onboarding) or `profile/cv.md`:
    the latest title, the progression across roles, titles next to the user's field, a seniority that fits. Works
    before profile/config.json exists. Show them with their reasons, let the user pick and add, save the picks as
    `role_targets` with `init_profile`, then call `keywords` on them. The same call as `./door cv titles`.

    Args:
        titles: Titles the user already named: always listed and recommended.
        hint: What they are looking for, in their own words.
        languages: The job-ad languages (`["Danish"]`). Omit for profile/config.json's `languages`.
        model: Claude model to ask (default: haiku).

    Returns:
        ``{"titles": [{"title", "reason", "recommended"}]}``, plus ``"warning"`` when the model failed or
        answered nothing (then only the given `titles` are listed): ask for the titles in free text.
    """
    return titles_cmd._titles_core(titles, hint=hint, languages=languages, model=model, profile_dir=workspace.PROFILE_DIR)


@mcp.tool()
@_tool_errors
def enrich(
    urls: list[str] | None = None, apply: list[int] | None = None, all: bool = False, model: str | None = None
) -> dict:
    """Propose additions to profile/cv.md from public URLs, then add the chosen ones.

    Two calls: first with `urls` (or none, for the profile's
    `enrich_sources`) — one `claude -p` call reads the pages with WebFetch
    and returns numbered `proposals` (section, text, source), evidenced on
    the pages and not already in the CV; nothing is written. Show them,
    ask which to add, then call again with `apply=[n, ...]` or `all=True`,
    which inserts them under their `##` sections (a `.bak` keeps the
    previous CV). Identical to `./door cv enrich`.

    Args:
        urls: Pages to read (portfolio, publication list, course syllabus, GitHub user …).
            Omit for `enrich_sources`.
        apply: Proposal numbers from the previous call to add.
        all: Add every proposal from the previous call.
        model: Claude model to read the pages with (default: sonnet).

    Returns:
        Propose: ``{"outcome": "proposed" | "nothing_new", "urls",
        "proposals": [{"n", "section", "text", "source"}], "unreachable"}``.
        Apply: ``{"outcome": "applied", "added", "cv_path", "backup"}``.
    """
    return enrich_cmd._enrich_core(urls, apply=apply, all=all, model=model, profile_dir=workspace.PROFILE_DIR)


@mcp.tool()
@_tool_errors
def list_stories() -> dict:
    """The story bank (profile/story_bank.md): the CARL (context, action, result, learning) stories the tailor draws on when it
    prepares an application. Identical to `./door cv stories`.

    Returns:
        ``{"path", "exists", "is_example", "stories": [{"title", "context", "action", "result",
        "learning"}]}``. `is_example`: the bank is still the made-up example, which `save_story`
        and `remove_story` refuse to change unless `save_story` is told to replace it.
    """
    return stories_cmd._list_stories_core(profile_dir=workspace.PROFILE_DIR)


@mcp.tool()
@_tool_errors
def save_story(
    title: str, context: str, action: str, result: str, learning: str,
    replace: str | None = None, replace_example: bool = False,
) -> dict:
    """Add a story to the story bank, or replace one. Only what the user said or the CV shows: never invent
    a field. All four text fields are required (an empty one is named in the error); newlines are collapsed.
    Show a drafted story and get the user's go-ahead before saving it. Identical to `./door cv stories add`.

    Args:
        title: The story's headline (past tense, short).
        context: The situation and what was asked of the user.
        action: What the user did.
        result: What came of it, with numbers when there are some.
        learning: What was learned.
        replace: The title of the story to replace; the new `title` renames it. Without it a title already
            in the bank is an error.
        replace_example: True to start the user's own bank in place of the made-up example one (ask first).

    Returns:
        ``{"outcome": "added" | "replaced", "story", "count", "path"}`` or ``{"error"}``.
    """
    return stories_cmd._save_story_core(
        title, context, action, result, learning, replace, replace_example, profile_dir=workspace.PROFILE_DIR
    )


@mcp.tool()
@_tool_errors
def remove_story(title: str) -> dict:
    """Remove a story from the story bank by its title (ask the user first). Identical to
    `./door cv stories remove`.

    Returns:
        ``{"outcome": "removed", "title", "count"}`` or ``{"error"}`` (no such title: the titles are listed).
    """
    return stories_cmd._remove_story_core(title, profile_dir=workspace.PROFILE_DIR)


@mcp.tool()
@_tool_errors
def draft_stories(text: str | None = None, from_cv: bool = False, model: str | None = None) -> dict:
    """Propose stories for the story bank from some text the user wrote about something they did
    (read beside profile/cv.md, which fills in what the text leaves out; where they differ the text wins and
    `conflicts` says what), or (`from_cv`) one story from the CV alone (profile/cv.draft.md while onboarding), to show
    what a story is: the bank holds what the CV does not say, so stories come from the user. One `claude -p` call. Nothing is saved:
    show the proposals and their `conflicts`, let the user fill what is empty (`missing`) and pick, then call `save_story` for each. Exactly one of `text` and
    `from_cv`. Identical to `./door cv stories draft`.

    Args:
        text: The user's account of one thing they did.
        from_cv: Propose one story from the CV (onboarding's example; not one already in the bank).
        model: Claude model to ask (default: sonnet).

    Returns:
        ``{"outcome": "proposed" | "nothing_new", "stories": [{"title", "context", "action",
        "result", "learning", "missing", "conflicts"}]}``.
    """
    return stories_cmd._draft_stories_core(text, from_cv, model, profile_dir=workspace.PROFILE_DIR)


@mcp.tool()
@_tool_errors
def skill_gaps(
    targets: list[str] | None = None, jobs: list[str] | None = None, top: int | None = None, model: str | None = None
) -> dict:
    """A skill-gap report with a WebSearch-cited learning plan, written to
    `upskill/report-<today>.md`.

    "What should I learn for the Trustpilot job?" / `/upskill`: one `claude -p` call (minutes)
    compares the CV with the targets — a hard-skill diff, then broader gaps
    (soft skills, domain depth, tooling maturity, credentials, evidence) —
    searches for real resources and writes the prioritised plan. Read the
    report back to summarise it. Identical to `./door cv gaps`.

    Args:
        targets: Role names ("Senior Accountant") or skills.
        jobs: Postings to analyse: each a job id or words from its company
            and title ("trustpilot"). Never ask the user for an id.
        top: Also analyse the top N matches.
        model: Claude model to analyse with (default: sonnet).

    Returns:
        ``{"report_path", "report" (its Markdown), "targets": [{"kind", "label", "job_id"?}], "plan_items"}``.
    """
    return gaps_cmd._skill_gaps_core(
        targets, jobs=jobs, top=top, model=model, profile_dir=workspace.PROFILE_DIR, jobs_dir=workspace.JOBS_DIR
    )


@mcp.tool()
@_tool_errors
def salary_estimate(job_id: str, refresh: bool = False, model: str | None = None) -> dict:
    """The salary range the user can expect for one job: "What salary can I expect for the Trustpilot one?".

    One Haiku call with a web search (a minute at most), when the user asks (`prepare` asks by itself
    for a job it prepared, so look at `show`'s ``salary`` first): the market range for
    the title, seniority and city, adjusted to the CV's experience against what the ad asks, with the
    pages it was read from. The ad's own figure, when it states one, comes first. Saved in
    `jobs/salary.json`: asking again about the same job makes no call unless `refresh`. Say it is an
    estimate from public pages, with its sources, not advice. Identical to `./door jobs salary`.

    Args:
        job_id: The job: its id, or words from its company and title ("trustpilot").
        refresh: Ask again even if an estimate is saved.
        model: Claude model to ask (default: haiku).

    Returns:
        ``{"job_id", "title", "company", "found": true, "low", "high", "currency", "period"
        ("month"|"year"), "gross", "position" ("below"|"within"|"above"), "basis", "sources":
        [{"title", "url"}], "ad_salary", "as_of", "cached"}``; or ``{"found": false, "message"}`` when no
        source could be cited: say so, give no number.
    """
    return salary_cmd._salary_core(job_id, refresh, model=model, jobs_dir=workspace.JOBS_DIR, profile_dir=workspace.PROFILE_DIR)


@mcp.tool()
@_tool_errors
def ask(question: str, model: str | None = None) -> dict:
    """Answer one question about the jobs data in a sentence or two — the desktop app's question box
    and `./door ask`. In a conversation, call the read tools directly instead. One short Claude call
    (Haiku) with the read tools only: it can never change profile/ or jobs/. Identical to `./door ask`.

    Args:
        question: The question, in the user's words.
        model: Claude model to answer with (default: haiku).

    Returns:
        ``{"answer", "go_to": {"screen": "matches" | "posting" | "applications" | "employers" | "cv",
        "job_ids"?} | None, "sources"}``, or ``{"error"}``.
    """
    return ask_cmd._ask_core(question, model=model, jobs_dir=workspace.JOBS_DIR, profile_dir=workspace.PROFILE_DIR)


@mcp.tool()
@_tool_errors
def query_jobs(
    since: str | None = None,
    until: str | None = None,
    site: str | None = None,
    company: str | None = None,
    status: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    language: str | None = None,
    has_materials: bool | None = None,
    limit: int = 10,
) -> dict:
    """Count and list postings by filter — for questions no other tool answers ("how many
    Teamtailor postings this month?", "average score of the Danish ads in September"). Read only:
    nothing is written. Identical to `./door jobs query`.

    Args:
        since: First seen on or after this day (``2026-09-01``).
        until: First seen on or before this day.
        site: Only postings from this site (``jobindex``, ``teamtailor``, ...).
        company: Only companies whose name contains this (any case).
        status: A ledger status (``applied``, ``rejected``, ...), ``unapplied`` for the untracked,
            or ``interview`` for any round.
        min_score: Only postings scoring at least this.
        max_score: Only postings scoring at most this.
        language: Only ads in this language (a code: ``en``, ``da``, ``hu``).
        has_materials: Only postings with (True) or without (False) a prepared CV and letter.
        limit: How many of the best postings to list (default 10).

    Returns:
        ``{"count", "average_score", "by_site", "by_company", "by_status", "by_month",
        "rows": [{"id", "title", "company", "score", "status", "site", "scraped_at",
        "posted_at"}]}``, the rows best first. Name postings by title and company to the user.
    """
    return query_cmd._query_core(
        since=since, until=until, site=site, company=company, status=status, min_score=min_score,
        max_score=max_score, language=language, has_materials=has_materials, limit=limit,
        jobs_dir=workspace.JOBS_DIR,
    )


@mcp.tool()
@_tool_errors
def market(days: int = 30, save: bool = True, scored_companies: bool = False) -> dict:
    """What the scraped ads ask for: "How does the market look?".

    Counts the ads of the last `days` days (seconds; one Haiku call only for
    skill names not yet in `jobs/skill_aliases.json`, which groups variants like
    "Excel" and "Microsoft Excel" and drops non-skills): the most
    requested skills (and whether the user has each; a trend when both windows
    have 50+ scored ads), near misses (what kept ads just under `min_score`
    below it), titles in the matches that no search keyword covers, and
    companies posting repeatedly. Saved to `jobs/market/report-<date>.md`.
    Next steps: "plan for the top 3 gaps" -> `skill_gaps` with those skills as
    targets; "add those titles" -> confirm, then `init_profile` with
    `search_keywords`. Identical to `./door market`.

    Args:
        days: Window length in days (default 30).
        save: Write the report to `jobs/market/` (default true).
        scored_companies: Count repeat companies over scored ads only (default: all scraped ads).

    Returns:
        ``{"window", "counts": {"scraped", "scored", "above_min_score"},
        "skills": [{"name", "count", "share", "have", "trend"}],
        "near_misses": {"n", "rows": [{"skill", "count"}]},
        "uncovered_titles": [{"title", "count"}],
        "companies": {"population": "scraped"|"scored", "rows": [{"name", "count", "followed"}]},
        "warning" (text when grouping failed, else null), "report_path"}``. An unfollowed repeat employer can be followed with `add_company`.
    """
    return market_cmd._market_core(days, save, scored_companies=scored_companies, jobs_dir=workspace.JOBS_DIR, profile_dir=workspace.PROFILE_DIR)


@mcp.tool()
@_tool_errors
def draft_cv(sources: list[str], write: bool = False, model: str | None = None) -> dict:
    """Draft profile/cv.md from the user's existing CV and public pages.

    `/onboard`'s CV step: give it file paths (their most recent CV as PDF,
    DOCX or Markdown; a LinkedIn "Save to PDF" export) and URLs (a personal
    site or portfolio). The files are read here, the URLs by one
    `claude -p` call with WebFetch, which writes the CV in
    profile.example/cv.md's structure — the newest CV is the backbone, the
    other sources only add, nothing is invented (missing facts are TODOs).
    Works before profile/config.json exists. Writes `profile/cv.draft.md`:
    read it, show it to the user with `provenance` and `todos`, take their
    edits, and only then put it in place (Write to profile/cv.md), or call
    again with `write=True` to replace profile/cv.md directly (the previous
    one is kept as cv.md.bak). The same call as `./door init`'s CV step.

    Args:
        sources: File paths and URLs. A LinkedIn profile URL is never
            fetched; ask for its PDF export instead.
        write: Replace profile/cv.md with the draft instead of writing
            profile/cv.draft.md.
        model: Claude model to draft with (default: sonnet).

    Returns:
        ``{"draft_path" | "cv_path" + "backup", "written", "sources",
        "provenance": [{"source", "contributed"}], "todos", "markdown"}``
        (``markdown`` is the draft text).
    """
    for source in sources:
        if not common._is_url(source):
            path_scope.check(source)
    return cv_cmd._draft_cv_core(sources, write=write, model=model, profile_dir=workspace.PROFILE_DIR)


@mcp.tool()
@_tool_errors
def infer_basics(markdown: str | None = None, model: str | None = None) -> dict:
    """Read the profile basics from the CV: name, email, city, job-ad languages and a `remote` default.

    Onboarding's reading step, right after `draft_cv`. The header is parsed; one `claude -p` call (Haiku by
    default) reads only what parsing leaves. Works before profile/config.json exists. Ask the user only about
    the keys in `missing`, one question each; show the rest in the review. Writes nothing.

    Args:
        markdown: The CV text. Omit for `profile/cv.draft.md`, or `profile/cv.md` when there is no draft.
        model: Claude model to ask (default: haiku).

    Returns:
        ``{"name", "email", "location", "languages", "remote", "missing"}`` (`None` for what was not found),
        plus ``"unsupported_location"`` (a place outside the covered countries, to ask about) and ``"warning"``
        (the model call failed, so what it would have read is in `missing`).
    """
    return cv_cmd._infer_basics_core(markdown, model=model, profile_dir=workspace.PROFILE_DIR)


@mcp.tool()
@_tool_errors
async def preview_matches(
    location: str, role_targets: list[str], search_keywords: list[str] | None = None, topic_terms: list[str] | None = None,
    languages: list[str] | None = None, remote: str | None = None, markdown: str | None = None, limit: int = 5,
) -> dict:
    """Onboarding's first look: score a handful of ads of one board against the CV, in about a minute.

    Call it once the reading step knows the titles and search terms, before the review. Works before
    profile/config.json exists, and writes nothing to `jobs/`; the first run still follows. Show `matches` by title and
    company; `warning` is one friendly line, never a reason to stop.

    Args:
        location: The city.
        role_targets: The titles picked so far.
        search_keywords: The search terms (only the first is searched). Default: `role_targets`.
        topic_terms: What makes a title relevant.
        languages: The job-ad languages.
        remote: `yes`, `no` or `hybrid`.
        markdown: The CV text. Omit for `profile/cv.draft.md`, or `profile/cv.md` when there is no draft.
        limit: How many ads to score.

    Returns:
        ``{"board", "matches": [{"title", "company", "location", "score", "score_reason", "url"}]}``, best first,
        plus ``"warning"`` when there is nothing to show.
    """
    config = {
        "location": location, "role_targets": role_targets, "search_keywords": search_keywords or role_targets,
        "topic_terms": topic_terms or [], "languages": languages or ["English"], "remote": remote or "hybrid",
    }
    cv_text = markdown or cv_cmd._onboarding_cv_text(workspace.PROFILE_DIR, {})
    # On a thread: it reads a board for up to a minute, and the wizard's other calls must not wait for it.
    return await asyncio.to_thread(preview_cmd._preview_core, config, cv_text, limit=limit)


@mcp.tool()
@_tool_errors
def save_cv(markdown: str) -> dict:
    """Put reviewed CV text in place as profile/cv.md (the previous one is kept as cv.md.bak; the scratch
    profile/cv.draft.md is removed). The desktop app's onboarding calls it after the user read and edited the
    text; `./door init`'s CV step does the same. Empty text is refused. Creates profile/ when missing.

    Args:
        markdown: The whole CV, in profile.example/cv.md's structure.

    Returns:
        ``{"cv_path", "backup"}`` (``backup`` None when there was no CV before) or ``{"error"}``.
    """
    from door.commands import profile as profile_cmd

    return profile_cmd._save_cv_core(markdown)


@mcp.tool()
@_tool_errors
def save_photo(path: str) -> dict:
    """Keep a picture as the CV photo: checked (a JPEG or PNG, at most 10 MB, at least 200 px a side), upright,
    with its EXIF and GPS data dropped and scaled to the size a CV photo is printed at, then saved as
    profile/photo.jpg and named in the `photo` key. The user's own file is not touched. Whether a CV carries it
    is up to the country of the job (`prepare` hands the tailor its conventions): never in the UK, optional in
    Denmark, France, Hungary and Sweden. Ask only when the city's country has `photo` "optional" or "expected"
    (its `cv` block in `show_profile`'s `options`), once, and the user may skip it. The desktop app's file
    picker and `./door init`'s photo question do the same.

    Args:
        path: The picture; a path inside the data folder (the desktop app passes the one its file dialog chose).

    Returns:
        ``{"photo_path"}`` or ``{"error": <why the picture was refused>}``.
    """
    from door.commands import profile as profile_cmd

    path_scope.check(path)
    return profile_cmd._save_photo_core(path)


@mcp.tool()
@_tool_errors
def remove_photo() -> dict:
    """Delete the CV photo (profile/photo.jpg) and clear the `photo` key: later CVs carry none.

    Returns:
        ``{"removed"}``: False when there was none.
    """
    from door.commands import profile as profile_cmd

    return profile_cmd._remove_photo_core()


@mcp.tool()
@_tool_errors
def mark_reviewed() -> dict:
    """Mark the end of a review session (stamps jobs/last_review.json).

    Call it when the user says they are done reviewing: the next
    `status_summary`'s ``since_last_review`` and `list_matches(new_only=True)`
    count from this moment. Conversation-only: there is no command.

    Returns:
        ``{"reviewed_at", "previous"}``.
    """
    return status_cmd._mark_reviewed_core(jobs_dir=workspace.JOBS_DIR)


@mcp.tool()
@_tool_errors
def mark_seen(job_id: str) -> dict:
    """Mark one match as seen: it is no longer new (`list_matches`' ``is_new``,
    ``new_only``, `status_summary`'s ``new_matches``).

    The desktop app calls it when the user opens a posting; `mark_reviewed`
    marks every match at once. Conversation-only: there is no command.

    Args:
        job_id: The job's id, or words from its company and title.

    Returns:
        ``{"job_id"}``.
    """
    return status_cmd._mark_seen_core(job_id, jobs_dir=workspace.JOBS_DIR)


@mcp.tool()
@_tool_errors
def revise(job_id: str, file: str = "cover_letter", instruction: str | None = None, undo: bool = False) -> dict:
    """One targeted edit to the CV or cover letter, recompiled and re-rendered.

    For "tighten the letter's second paragraph" — no full tailor re-run.
    One `claude -p` call rewrites the document body (never the preamble);
    the previous version is kept as `<file>.tex.bak`, and ``undo=True``
    restores it. Call `show` afterwards to check the pages. This is the
    only way to change a prepared document: never edit a `.tex` with Write
    or Edit, since `revise` is what recompiles and re-renders the PDF.
    Conversation-only: there is no command.

    Args:
        job_id: The job: its id, or words from its company and title ("trustpilot").
        file: "cover_letter" or "cv".
        instruction: What to change, in the user's words. Required unless
            ``undo``.
        undo: Restore the version before the last revise instead.

    Returns:
        ``{"outcome": "revised" | "undone", "job_id", "file", "backup",
        "compile", "render"}``.
    """
    return revise_cmd._revise_core(
        job_id, file, instruction, undo=undo, jobs_dir=workspace.JOBS_DIR, profile_dir=workspace.PROFILE_DIR
    )


@mcp.tool()
@_tool_errors
def doctor(probe: bool = False) -> dict:
    """Check every prerequisite: Python, profile, LaTeX, the `claude` CLI,
    the MCP server entry and dev deps.

    Instant and offline by default. With ``probe=True`` it also probes each
    configured site's live scraper (one ``scraper: <site>`` check per site,
    page 1 only; live requests, so it can take a
    while) and saves the raw response of a suspicious probe under
    ``jobs/drift/<site>/``. Call it when a command fails for an environment
    reason, or first thing in a setup conversation; pass ``probe`` when a
    site returned nothing and the user wants to know whether its scraper
    broke. Identical to `./door doctor [--probe]`.

    Args:
        probe: Also run the live ``scraper: <site>`` probes.

    Returns:
        ``{"ok", "checks": [{"name", "status": "ok" | "missing" | "warn" |
        "drift", "required", "detail", "fix"}], "last_run", "last_scrape"}`` —
        ``fix`` is the command to run for a failed check. ``drift`` means a
        site's page no longer has the structure its scraper reads (offered a
        fix by `setup` with ``probe=True``); a ``scraper:`` ``warn`` is an unreachable site, a
        login/bot wall or a result count far from the recent runs. Neither
        makes ``ok`` false.
    """
    return setup_cmd._doctor_core(profile_dir=workspace.PROFILE_DIR, jobs_dir=workspace.JOBS_DIR, probe=probe)


@mcp.tool()
@_tool_errors
def setup(
    install: list[str] | None = None, yes: bool = False, fix_scrapers: list[str] | None = None, probe: bool = False
) -> dict:
    """Install missing prerequisites (TeX, the `claude` CLI).

    Call it first WITHOUT `yes`: nothing runs, and ``plan`` lists the exact
    command(s) per tool. Show them to the user, then call again with
    ``yes=True`` and ``install`` = the tools they approved. Nothing here
    needs sudo; a step that fails can be run in a terminal, or via `./scripts/setup.sh`.
    The profile is not created here: collect the fields and call
    `init_profile`. Same logic as `./door doctor --fix`.

    Args:
        install: Tools to install: "latex", "claude". Omit
            for every tool `doctor` reports missing.
        yes: The user approved the plan — run it.
        probe: Probe each configured site live (as `doctor` with
            ``probe=True``) so ``fixes`` can offer a drifted scraper.
            Off by default — the installs need no network.
        fix_scrapers: Sites whose drifted scraper to repair
            (``doctor`` with ``probe=True`` shows them as ``scraper: <site>``
            with status ``drift``; the plan's ``fixes`` lists the offers). Only with
            ``yes``, and only for sites the user approved: each runs the
            headless scraper-fixer on a new branch, gates it on the offline
            tests plus a fresh probe, then pushes and opens a PR. Refused
            while a run is in progress or the working tree is dirty.

    Returns:
        ``{"outcome": "needs_confirmation" | "ok" | "incomplete", "platform",
        "plan", "results", "doctor", "todo", "fixes"}``. ``fixes`` holds the
        offers (``[{"site", "check"}]``) until fixes run, then one outcome
        per site: ``pr`` (with ``url``), ``local_branch`` (with ``branch``
        and the ``commands`` to finish by hand), ``gate_failed``,
        ``fixer_failed`` or ``refused``.
    """
    return setup_cmd._setup_core(
        install, yes=yes, skip_profile=True, interactive=False,
        profile_dir=workspace.PROFILE_DIR, jobs_dir=workspace.JOBS_DIR,
        fix_scrapers=fix_scrapers, probe_sites=probe,
    )


@mcp.tool()
@_tool_errors
def import_posting(
    path: str | None = None,
    text: str | None = None,
    title: str | None = None,
    company: str | None = None,
    url: str | None = None,
    location: str | None = None,
    force: bool = False,
) -> dict:
    """Import a job ad the user found outside the scraped boards.

    Give the ad as pasted ``text`` (the usual case in a conversation — ask
    for the title and company if the ad doesn't make them obvious), as a
    ``path`` to a text/Markdown file or a JSON posting, or as its ``url``
    alone ("here's a link": pass only the url — the page is fetched, its
    readable text becomes the description and Haiku reads the title,
    company and location off it; a login-walled or JavaScript-only page comes
    back as an error — paste the text then). It becomes an
    ordinary posting (``source="manual"``) under jobs/postings/<today>/manual/,
    scored right away (Haiku, like `find_jobs`): tell the user its score and
    reason; `show`, `prepare` and `set_status` work on its ``job_id``.
    Identical to `./door jobs add`.

    Args:
        path: A file with the ad. Exactly one of path/text/url.
        text: The ad's text.
        url: Where the ad lives; with no path/text, the ad is fetched from it.
        title, company: Required for a text ad; read off the page for a url.
        location: Optional.
        force: Replace a posting already stored under the same id.

    Returns:
        ``{"job_id", "path", "replaced", "score", "score_reason",
        "score_error"?}`` — ``score`` is None when scoring failed (the
        posting is kept; the next `find_jobs` scores it).
    """
    if path is not None:
        path_scope.check(path)
    return add_cmd._add_core(
        path, text=text, title=title, company=company, url=url, location=location,
        force=force, jobs_dir=workspace.JOBS_DIR,
    )


@mcp.tool()
@_tool_errors
def list_companies(status: str | None = None, found_via: str | None = None) -> dict:
    """The employers The other door follows (profile/companies.json), one entry each.

    Use it for "which companies do I follow?", "which ones couldn't be followed?".
    Identical to `./door companies` / `companies list`.

    Args:
        status: Only employers with this status: "followed", "unfollowable" or "unresolved".
        found_via: Only employers found this way: "manual", "ai", or the
            board or discovery source that brought them in (e.g. "jobindex", "linkedin").

    Returns:
        ``{"companies": [{"name", "feed": {"platform", "id"} | None, "status", "reason",
        "refusal", "found_via", "evidence", "first_seen", "last_checked"}], "counts": {status: n}}``;
        ``refusal`` on an unfollowable employer is ``"must_not"`` (its terms forbid it) or ``"cant_yet"``
        (no way in yet), else None.
    """
    return companies_cmd._list_core(status=status, found_via=found_via, profile_dir=workspace.PROFILE_DIR)


@mcp.tool()
@_tool_errors
def add_company(inputs: list[str], dry_run: bool = False, probe: bool = True) -> dict:
    """Follow employers: find each one's job feed and record it in profile/companies.json.

    "Add Trustpilot", "follow careers.trackman.com": give each company name,
    careers link or career host. Public signals only: the link's shape, the
    host's DNS CNAME, the careers page (robots.txt honoured), and for a bare
    name each feed's public endpoint with the name's likely slugs. A feed The other door
    can follow is recorded as followed (and its site enabled); a platform it
    cannot follow (HR-ON, or Phenom with no readable Workday site behind it) as
    unfollowable with its ``refusal`` ("must_not" or "cant_yet"), and a
    miss as unresolved, each with the reason. Use `dry_run=True` to show the
    user what would be recorded first. Identical to `./door companies add`.

    Args:
        inputs: Company names, careers links or career hosts.
        dry_run: Show what would be recorded; write nothing.
        probe: Probe feed endpoints for a bare name and read careers pages;
            False uses only the links' own shape and DNS.

    Returns:
        ``{"dry_run", "results": [{"input", "name", "status", "platform", "entry",
        "reason", "refusal", "evidence", "candidates", "new"}]}``.
    """
    return companies_cmd._add_core(inputs, dry_run=dry_run, probe=probe, profile_dir=workspace.PROFILE_DIR,
                                   jobs_dir=workspace.JOBS_DIR)


@mcp.tool()
@_tool_errors
def remove_company(names: list[str]) -> dict:
    """Stop following employers: remove each named one from profile/companies.json.

    Identical to `./door companies remove`.

    Args:
        names: Employer names (case and company suffixes such as A/S are ignored).

    Returns:
        ``{"removed": [{"name", "feed"}], "not_found": [name, ...]}``.
    """
    return companies_cmd._remove_core(names, profile_dir=workspace.PROFILE_DIR, jobs_dir=workspace.JOBS_DIR)


@mcp.tool()
@_tool_errors
def merge_companies(names: list[str] | None = None) -> dict:
    """Merge two employers on the list that are really one (LEGO and LEGO System A/S).

    With no `names`, nothing is changed: it returns the groups of entries that share a feed or a name, for
    you to show the user. Merge only what the user confirms, one pair at a time: give two names, the employer
    to keep and the one to fold into it (its name and aliases become aliases of the first). Two employers
    followed on different feeds are not merged. Identical to `./door companies merge`.

    Args:
        names: Nothing, or exactly two employer names (case and suffixes such as A/S are ignored).

    Returns:
        ``{"candidates": [{"names": [...], "reason"}]}``, or ``{"merged": <the entry kept>, "removed": <name folded in>}``.
    """
    return companies_cmd._merge_core(names, profile_dir=workspace.PROFILE_DIR, jobs_dir=workspace.JOBS_DIR)


@mcp.tool()
@_tool_errors
def why_company(name: str) -> dict:
    """Everything known about one employer: its feed, status, the reason or evidence, how it
    was found, when, and how many postings in jobs/ came from it.

    Identical to `./door companies why`.

    Args:
        name: The employer's name.

    Returns:
        ``{"company": {...its list entry...}, "postings": n, "by_source": {site: n}}``,
        or ``{"error": ...}`` when it is not on the list.
    """
    return companies_cmd._why_core(name, profile_dir=workspace.PROFILE_DIR, jobs_dir=workspace.JOBS_DIR)


@mcp.tool()
@_tool_errors
def export_data(path: str | None = None) -> dict:
    """Pack profile/ and jobs/ into one .tar.gz to carry to another computer.

    Never overwrites an existing file.
    Identical to `./door data export`.

    Args:
        path: The archive to write, or a directory to write
            door-export-<date>.tar.gz into. Omit for the repo root.

    Returns:
        ``{"path", "files", "bytes"}``.
    """
    if path is not None:
        path_scope.check(path)
    return archive_cmd._export_core(path, profile_dir=workspace.PROFILE_DIR, jobs_dir=workspace.JOBS_DIR)


@mcp.tool()
@_tool_errors
def import_data(archive: str) -> dict:
    """Replace profile/ and jobs/ with an archive made by `export_data`.

    Destructive: the current profile, postings, ledgers and materials are
    replaced (moved to backups/<timestamp>/ first, so nothing is lost).
    Confirm with the user before calling. Identical to `./door data import`.

    Args:
        archive: Path to the .tar.gz.

    Returns:
        ``{"archive", "files", "profile_dir", "jobs_dir", "backup_dir",
        "warnings"}`` — tell the user about each warning (a
        config path this computer doesn't have) and where the backup is.
    """
    path_scope.check(archive)
    return archive_cmd._import_core(archive, profile_dir=workspace.PROFILE_DIR, jobs_dir=workspace.JOBS_DIR)


@mcp.tool()
@_tool_errors
def report_problem(path: str | None = None) -> dict:
    """Save one archive to send to whoever helps with The other door when something went wrong.

    It holds the problem log (`logs/door.log`: failed tool calls, failed sites, unscored ads,
    warnings, crashes), the last few run records cut to counts, outcomes and errors, doctor's
    checks, and the version and OS. Emails and home folders are masked; nothing from profile/
    (no CV, no profile values), no postings and no applications. Never overwrites a file.
    Identical to `./door data report`.

    Args:
        path: The .zip to write, or a directory to write door-report-<date>.zip into.
            Omit for the current directory.

    Returns:
        ``{"path", "files": [names in the archive], "bytes"}``.
    """
    if path is not None:
        path_scope.check(path)
    return report_cmd._report_core(path)


@mcp.tool()
@_tool_errors
def connect_drive() -> dict:
    """Connect this computer to the user's Google Drive, once.

    A browser window opens for the user to allow access (The other door then sees only
    its own folder `door/` on Drive); the call waits for them, up to five
    minutes. After that profile/ and jobs/ are pulled before and pushed after
    every command that writes, by themselves. Identical to `./door data connect`.
    If Drive already holds The other door data, call `sync_data` next to bring it here.

    Returns:
        ``{"account"}`` or ``{"error": ...}`` (e.g. not configured in this build).
    """
    return archive_cmd._connect_core()


@mcp.tool()
@_tool_errors
def sync_data(keep_local: bool = False, keep_drive: bool = False) -> dict:
    """Push or pull profile/ and jobs/ to or from Google Drive now, whichever is needed.

    Identical to `./door data sync`. When both sides changed it refuses and says so
    (``{"error": ...}``): ask the user which side to keep, then call again with
    ``keep_local`` (replace Drive with this computer) or ``keep_drive`` (replace
    this computer with Drive; its data goes to backups/).

    Args:
        keep_local: After a both-sides change, keep this computer's data.
        keep_drive: After a both-sides change, keep Drive's data.

    Returns:
        ``{"action": "push" | "pull" | "nothing" | "skipped", ...}``.
    """
    return archive_cmd._sync_core(keep_local, keep_drive)


@mcp.tool()
@_tool_errors
def disconnect_drive() -> dict:
    """Forget this computer's Google Drive connection. The archive on Drive stays.

    Identical to `./door data disconnect`.

    Returns:
        ``{"disconnected"}``: False when it was not connected.
    """
    return archive_cmd._disconnect_core()


def _startup_pull() -> None:
    """One best-effort pull when the server starts, so a conversation sees what the other computer did.

    Skipped when this computer is not connected or something holds the ledger lock; never raises
    (a conflict shows up at the next write, offline is silent).
    """
    try:
        if drive.read_state() is None or lock_holder(workspace.JOBS_DIR) is not None:
            return
        with ledger_lock(workspace.JOBS_DIR, "sync"):
            sync.on_acquire("startup", workspace.JOBS_DIR)
    except Exception:  # noqa: BLE001 - startup must not fail because Drive is down
        return


def main() -> None:
    """Serve over stdio: the problem log first (#593), then a pull from Drive, then the tools."""
    problem_log.setup()
    _startup_pull()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
