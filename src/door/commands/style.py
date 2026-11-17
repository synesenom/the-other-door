"""`cv style build FILE`: build a CV template from the style of a CV PDF (#205, epic #144; the builder is
`tailoring/style_build.py`, #149).

Two cores. `_build_core` is the build itself, in the foreground (the command, with progress). `_start_core` is what the
`build_style` tool calls: it takes the file in (intake, a copy at `HOME/.style/source.pdf`), ends a build already
running, starts `python -m door cv style build <copy>` as a process of its own (`core/phone.py`'s way, so it outlives
the server or the app that asked) and returns at once. Its state is `HOME/.style/run.json` (`pid`, `state`
building|ready|failed, `started_at`, `result`; the start's pending record names the process it `spawned`), its folder `HOME/.style/work` and its log `HOME/.style/build.log`.
Both the starter and the build write run.json, on purpose: the starter's `building` (no pid yet) covers the gap until
the build takes its lock and writes its own. A build is alive while it holds the OS lock `HOME/.style/build.lock`
(dropped by the OS when it dies, so a record left by a crash or a reboot, or a pid since reused, never reads as a build
and is never ended); `status` reads that for `status_summary`'s `style` block. A build writes only `profile/style/`
and never takes the ledger lock, so it runs beside a `find`.

A build writes the candidate, `profile/style.next/`, never `profile/style/`. The style in use is the two template keys
(`cv_template`, `cover_letter_template`) pointing into `profile/style/`; `_use_core` (`use_style`, `cv style use`)
changes them and moves a candidate in or ends it (#151). `_stop_core` (`stop_style_build`) ends a running build, as the
app does before an update installs (#215).
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import sys
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import click
from pypdfium2 import PdfiumError

from door.commands import _common as common
from door.commands import _progress
from door.core import doctor, lock, phone, templates, tracker, workspace
from door.tailoring import style_build, style_extract, style_preview

LOCK_WAIT = 20.0  # seconds a build waits for the one it replaced to let go
PENDING_SECONDS = 30  # a started build that has not yet taken its lock still reads as building this long


def _style_dir(home: Path) -> Path:
    return Path(home) / ".style"


def _read(home: Path) -> dict | None:
    try:
        run = json.loads((_style_dir(home) / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return run


def _write(home: Path, run: dict) -> None:
    path = _style_dir(home) / "run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _look(path: Path) -> None:
    """Raise ValueError, in words, when the file at `path` has no style to copy (whatever this machine can print)."""
    if not path.is_file():
        raise ValueError(f"{path} is not a file")
    if refused := style_extract.not_pdf(path):
        raise ValueError(refused["detail"])
    try:
        verdict = style_extract.extract(path)["verdict"]
    except (PdfiumError, OSError) as exc:
        raise ValueError(f"{path.name} could not be read as a PDF ({exc})") from exc
    if not verdict["copyable"]:
        raise ValueError(verdict["detail"] or f"no style to copy ({verdict['reason']})")


def _intake(path: Path) -> None:
    """Raise ValueError, in words, when a build of the file at `path` cannot start: no Chromium to print with, or no style."""
    if not common._chromium_available():
        raise ValueError(f"no Chromium to print with: {doctor._CHROMIUM_FIX}")
    _look(path)


def _lock_path(home: Path) -> Path:
    return _style_dir(home) / "build.lock"


@contextmanager
def _building(home: Path):
    """Hold the build lock for the block, waiting up to `LOCK_WAIT` seconds for a build being ended to let go."""
    _style_dir(home).mkdir(parents=True, exist_ok=True)
    try:
        with lock.hold(_lock_path(home), LOCK_WAIT):
            yield
    except TimeoutError:
        raise ValueError("a build of a CV style is still running") from None


def _end_running(home: Path) -> dict | None:
    """End the build that is running (its process group), unless it is this process or its launcher; its record, or
    None when there was none to end."""
    run = _read(home)
    if run and run["state"] == "building" and run.get("pid") not in (None, os.getpid(), os.getppid()) and lock.held(_lock_path(home)):
        phone.kill_tree(run["pid"])
        return run
    return None


def _stop_core(*, home: Path | None = None) -> dict:
    """End the build that is running, wait for it to let go of its lock (its process is gone, no file of the install
    stays held: the app calls this before an update installs, #215) and record it failed. The style in use and a
    waiting candidate are left alone. A build started a moment ago that has not taken its lock yet (still reading the
    file) is ended by the pid its start recorded (`spawned`). A build that finished meanwhile keeps its ``ready``.

    Returns ``{"stopped": bool}``, False when no build was running. Raises ValueError, in words, when the build does
    not let go of its lock within `LOCK_WAIT` seconds; its record is then left as it was."""
    home = Path(home or workspace.HOME)
    run = _end_running(home)
    if run is None:
        run = _read(home)
        if not (run and run["state"] == "building" and "pid" not in run and "spawned" in run
                and _age(run["started_at"]) < PENDING_SECONDS):
            return {"stopped": False}
        phone.kill_tree(run["spawned"])
    with _building(home):
        now = _read(home) or {}
        if now == run or now.get("state") == "failed":  # not over a result written meanwhile
            _write(home, {**run, "state": "failed", "result": {"problems": ["the build was stopped"]}})
    return {"stopped": True}


def _fail_pending(home: Path, exc: Exception) -> None:
    """A start's `building` record (no pid yet) of a process that was refused the file is a failure, not a build."""
    run = _read(home)
    if run and run["state"] == "building" and "pid" not in run:
        _write(home, {**run, "state": "failed", "result": {"problems": [str(exc)]}})


def _terminate(signum, frame):
    raise SystemExit(128 + signum)


def _build_core(file: str, *, progress=None, home: Path | None = None, profile_dir: Path | None = None) -> dict:
    """Build a CV template from the PDF at `file` here and now, recording the build in `HOME/.style/run.json`.

    Returns `style_build.build`'s result. Raises ValueError (intake: nothing is written, but a start's pending record
    turns failed) or whatever the builder raises, after recording the build as failed. SIGTERM, from the build that
    replaces this one, unwinds like an exception, so the print's `finally` ends Chromium (a session of its own)."""
    home = Path(home or workspace.HOME)
    pdf = Path(file).expanduser()
    try:
        _intake(pdf)
    except ValueError as exc:
        _fail_pending(home, exc)
        raise
    _end_running(home)
    run = {"pid": os.getpid(), "state": "building", "started_at": _now()}

    def record(state: dict) -> None:
        # not over a newer build's record: this one was replaced
        if (_read(home) or {}).get("pid") == os.getpid():
            _write(home, state)

    main = threading.current_thread() is threading.main_thread()
    before = signal.signal(signal.SIGTERM, _terminate) if main else None
    try:
        with _building(home):
            _write(home, run)
            try:
                result = style_build.build(
                    pdf, work_dir=_style_dir(home) / "work", profile_dir=profile_dir or workspace.PROFILE_DIR, progress=progress)
            except BaseException as exc:
                record({**run, "state": "failed", "result": {"problems": [f"{type(exc).__name__}: {exc}"]}})
                raise
            record({**run, "state": result["state"], "result": result})
    finally:
        if main:
            signal.signal(signal.SIGTERM, before)
    return result


def _spawn(home: Path, copy: Path) -> None:
    folder = _style_dir(home)
    pending = {"state": "building", "started_at": _now()}
    _write(home, pending)
    env = {**os.environ, "DOOR_HOME": str(home), "PYTHONPATH": str(workspace.REPO_ROOT / "src")}
    process = phone.spawn_detached([sys.executable, "-m", "door", "cv", "style", "build", str(copy)],
                                   log=folder / "build.log", env=env, hidden_console=True)
    if _read(home) == pending:  # the build has not written its own yet: `_stop_core` can end it before it does
        _write(home, {**pending, "spawned": process.pid})


def _start_core(file: str, *, home: Path | None = None) -> dict:
    """Start a build of the PDF at `file` in a process of its own and return ``{"started": True}`` at once.

    Raises ValueError, in words, when the file has no style to copy or there is no Chromium to print with: nothing starts and
    the style in use is untouched."""
    home = Path(home or workspace.HOME)
    pdf = Path(file).expanduser()
    _intake(pdf)
    _end_running(home)
    copy = _style_dir(home) / "source.pdf"
    copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pdf, copy)
    _spawn(home, copy)
    return {"started": True}


def _age(started_at: str) -> float:
    return (datetime.now(UTC) - datetime.fromisoformat(started_at)).total_seconds()


def status(home: Path, profile_dir: Path) -> dict:
    """`status_summary`'s `style` block: ``{"state": "building" | "ready" | "failed" | "none", ...}``, in that order.

    building: the build holds its lock (or was started a moment ago and has not taken it yet). ready: a candidate is
    waiting, `profile/style.next/cv.template.html` exists (``fonts`` and ``dropped_icons`` of the last build's result
    when it was that one's), even when a later build failed. failed: the last build failed (``problems`` say why) or its
    process died before it finished. none: no candidate waits."""
    style_build.restore(Path(profile_dir))
    run = _read(home) or {}
    state = run.get("state")
    if state == "building":
        if lock.held(_lock_path(home)) or ("pid" not in run and _age(run["started_at"]) < PENDING_SECONDS):
            return {"state": "building", "started_at": run["started_at"]}
        return {"state": "failed", "problems": ["the build stopped before it finished"]}
    if templates.liked(Path(profile_dir)).name == templates.CANDIDATE:
        out = {"state": "ready"}
        if state == "ready":
            out.update({k: run["result"][k] for k in ("fonts", "dropped_icons") if k in run["result"]})
        return out
    if state == "failed":
        return {"state": "failed", "problems": run["result"]["problems"]}
    return {"state": "none"}


def _keys(profile_dir: Path) -> dict:
    folder = Path(profile_dir) / templates.STYLE
    return {key: (folder / name).relative_to(workspace.HOME).as_posix() for key, name in templates.FILES.items()}


def _prepared(jobs_dir: Path) -> list[str]:
    """The jobs prepared and not sent (ledger status exactly ``prepared``) that have a ``cv.html`` to print again."""
    ledger = tracker.ApplicationTracker(jobs_dir / "applications.json")
    return [job for job in ledger.job_ids()
            if ledger.get_status(job) == "prepared" and (jobs_dir / "output" / job / "cv.html").is_file()]


def _use_core(style: str = "like", rerender: bool = False, *, profile_dir: Path | None = None) -> dict:
    """Choose the CV style: ``like`` (the one built from the user's CV: the candidate moves into `profile/style/`
    and both template keys point at it), ``default`` (both keys cleared, only where they point into `profile/style/`)
    or ``current`` (what is in use stays). Any pick ends the candidate: it is deleted when a built style is already
    kept, and moved into `profile/style/` unused when none is.

    With `rerender` the candidate is left alone (choosing it is a call of its own), and the prepared applications (status ``prepared``, not sent) are printed again in the style in use by
    `compile`: no model, a failing job listed and the rest done.

    Returns ``{"in_use": "like" | "default", "prepared": N}`` and, with `rerender`, ``"rerendered"`` and ``"failed"``
    (job ids). Raises ValueError, in words, when ``like`` has no style built."""
    from door.commands import compile as compile_cmd
    from door.commands import profile as profile_cmd

    profile_dir = Path(profile_dir or workspace.PROFILE_DIR)
    candidate, kept = profile_dir / templates.CANDIDATE, profile_dir / templates.STYLE
    if style not in ("like", "default", "current"):
        raise ValueError(f"unknown style {style!r}: like, default or current")
    config = common._load_config_or_defaults(profile_dir)
    style_build.restore(profile_dir)
    if style == "like" and not (kept.is_dir() or (candidate.is_dir() and not rerender)):
        raise ValueError("no CV style is built yet: build one from a CV of yours first")
    if style != "current" and not (profile_dir / "config.json").is_file():
        raise ValueError("there is no profile yet: set one up first, then choose a style")
    if candidate.is_dir() and not rerender:
        if style == "like" or not kept.is_dir():
            style_build.move_in(candidate, profile_dir, templates.STYLE)
        else:
            style_build.end(candidate, profile_dir)
    fields: dict = {}
    if style == "like":
        fields = _keys(profile_dir)
    elif style == "default":
        fields = {key: None for key in templates.FILES if config.get(key) and templates.points_into(config[key], kept)}
    if fields:
        profile_cmd._init_core(fields, profile_dir=profile_dir, example_dir=workspace.PROFILE_EXAMPLE_DIR)
    result = {"in_use": templates.in_use(profile_dir, common._load_config_or_defaults(profile_dir))}
    jobs = _prepared(workspace.JOBS_DIR)
    result["prepared"] = len(jobs)
    if rerender:
        result.update(rerendered=[], failed=[])
        for job in jobs:
            try:
                done = compile_cmd._compile_core(job, render=True)
                ok = not any(r.get("status") == "error" for r in done.get("results", []))
            except Exception:  # noqa: BLE001 - one job that cannot print is listed, the others go on
                ok = False
            result["rerendered" if ok else "failed"].append(job)
    return result


def _show_core(*, home: Path | None = None, profile_dir: Path | None = None) -> dict:
    """The previews of the profile's `cv.md` and a sample letter in the default style and, once one is built, in the
    rebuilt one (`style_preview.show`): ``{"styles": {"default" | "like": {"cv": [png], "letter": [png]}}, "in_use":
    "like" | "default", "candidate": bool}``, made again only where stale, no model. ``like`` is the candidate when one
    waits, else the style kept in `profile/style/`. A style that could not be printed (no Chromium) is left out."""
    profile_dir = Path(profile_dir or workspace.PROFILE_DIR)
    style_build.restore(profile_dir)
    config = common._load_config_or_defaults(profile_dir)
    shown = style_preview.show(Path(home or workspace.HOME), profile_dir, config)
    shown.update(in_use=templates.in_use(profile_dir, config), candidate=templates.liked(profile_dir).name == templates.CANDIDATE)
    return shown


@click.group("style")
def style_group():
    """Build a CV template from the look of a CV PDF of yours."""


@style_group.command("build")
@click.argument("file", type=click.Path(dir_okay=False))
def build_style(file):
    """Build a template from FILE's look (a CV as a PDF): fonts, colours, layout, in a few minutes of the model's time.

    Runs here and now; the `build_style` tool starts the same thing in the background. The result is written to
    profile/style.next/ only when it passes; nothing uses it until `cv style use` chooses it."""
    interactive = common._stdout_is_tty()
    try:
        with _progress.live_progress(enabled=interactive) as reporter:
            result = _build_core(file, progress=reporter)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    for font in result["fonts"]:
        if font.get("source") == "none":
            click.echo(f"No free font for {font['family']}: {font['reason']}")
        elif font.get("faked"):
            click.echo(f"{font['family']}: no file for some of its faces; they are not used")
    for icon in result["dropped_icons"]:
        click.echo(f"Icon left out ({icon['near'] or 'unlabelled'}): {icon['reason']}")
    if result["state"] != "ready":
        for problem in result["problems"] or ["the build failed"]:
            click.echo(f"Error: {problem}", err=True)
        sys.exit(1)
    click.echo(f"The template is ready after {result['rounds']} rounds: profile/style.next/; `cv style use` chooses it.")


_USE_WORDS = {"like": "Your own style is in use: the one built from your CV.", "default": "The other door's style is in use."}


@style_group.command("use")
@click.argument("style", type=click.Choice(["like", "default", "current"]), default="like")
@click.option("--rerender", is_flag=True, help="Print the prepared applications again in the style in use (no model).")
def use_style(style, rerender):
    """Choose the CV style: like (the one built from your CV, the default), default (The other door's) or current (keep
    what you use now and drop the one just built).

    Applications already prepared keep their old look unless --rerender prints them again; sent ones never change."""
    try:
        result = _use_core(style)
        if rerender:  # choosing and printing again are two calls: the second never touches a candidate
            result = _use_core("current", True)
    except (ValueError, common.ConfigError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    click.echo(_USE_WORDS[result["in_use"]])
    if rerender:
        click.echo(f"{len(result['rerendered'])} of {result['prepared']} prepared applications printed again.")
        if result["failed"]:
            click.echo(f"Could not print: {', '.join(result['failed'])}", err=True)
    elif result["prepared"]:
        click.echo(f"{result['prepared']} prepared applications keep their look; --rerender prints them again.")


@style_group.command("show")
def show_style():
    """Print your CV and a sample letter in the default style and in the one built from your CV, as page images.

    Made again only when your CV, photo or style changed; no model is used."""
    styles = _show_core()["styles"]
    if not styles:
        click.echo("Nothing could be printed. Run `./door doctor --fix` to install the browser that prints pages.")
        return
    for name, sets in styles.items():
        click.echo(f"{'Like your CV' if name == 'like' else 'The default'}:")
        for kind, images in sets.items():
            for image in images:
                click.echo(f"  {kind}: {common._display_path(Path(image))}")
