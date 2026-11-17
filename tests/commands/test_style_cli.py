"""`cv style build` and the `build_style` tool (#205): intake, a build run in the foreground, a build started detached
with its state in HOME/.style/run.json, and the `style` block of `status_summary`. The builder (`style_build.build`)
and the process are stood in; no model is called."""

import asyncio
import contextlib
import json
import os
import re
import shutil
import signal
import sys
import time
from datetime import UTC, datetime, timedelta

import pytest
from click.testing import CliRunner

from door import mcp_server
from door.cli import cli
from door.commands import _common as common
from door.commands import status as status_cmd
from door.commands import style as style_cmd
from door.core import chromium, doctor, lock, phone, workspace
from door.tailoring import style_build, style_preview
from cli_utils import result_text
from paths import TESTS_DIR

STYLES = TESTS_DIR / "tailoring" / "fixtures" / "styles"
READY = {"state": "ready", "rounds": 2, "scores": [0.8, 0.9], "fonts": [{"family": "Lato", "source": "pin"}],
         "dropped_icons": [{"near": "x", "reason": "none"}], "font_error": None, "problems": []}


@pytest.fixture
def home(cli_env, tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    return tmp_path


@pytest.fixture
def cv_pdf(tmp_path):
    path = tmp_path / "my cv.pdf"
    shutil.copyfile(STYLES / "html-plain-single.pdf", path)
    return path


def _now(seconds=0):
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _run(home):
    return json.loads((home / ".style" / "run.json").read_text(encoding="utf-8"))


class Process:
    def __init__(self, pid):
        self.pid = pid


class Holder:
    """Stands in for a build that is running: it holds the build lock."""

    def __init__(self, home):
        (home / ".style").mkdir(exist_ok=True)
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(lock.hold(home / ".style" / "build.lock", 0))

    def release(self):
        self.stack.close()


class World:
    """Stand-ins for the process: `spawn` records what it was asked, `kill` ends the build that holds the lock."""

    def __init__(self):
        self.spawned, self.killed, self.holders = [], [], []

    def spawn(self, argv, *, log, env=None, **kw):
        self.spawned.append({"argv": argv, "log": log, "env": env, **kw})
        return Process(777)

    def kill(self, pid):
        self.killed.append(pid)
        for holder in self.holders:
            holder.release()

    def hold(self, home):
        self.holders.append(Holder(home))


@pytest.fixture
def world(monkeypatch):
    w = World()
    monkeypatch.setattr(phone, "spawn_detached", w.spawn)
    monkeypatch.setattr(phone, "kill_tree", w.kill)
    yield w
    for holder in w.holders:
        holder.release()


# ----------------------------------------------------------------------------- intake
def test_a_file_that_is_not_a_pdf_is_refused_in_words_and_nothing_starts(home, world, tmp_path):
    docx = tmp_path / "cv.docx"
    docx.write_bytes(b"x")
    with pytest.raises(ValueError, match="no layout to copy"):
        style_cmd._start_core(str(docx))
    assert world.spawned == [] and not (home / ".style").exists()


def test_start_refuses_in_words_without_a_chromium_and_starts_nothing(home, world, cv_pdf, monkeypatch):
    monkeypatch.setattr(common, "_chromium_available", lambda: False)
    with pytest.raises(ValueError, match=re.escape(f"no Chromium to print with: {doctor._CHROMIUM_FIX}")):
        style_cmd._start_core(str(cv_pdf))
    assert world.spawned == [] and not (home / ".style").exists()


def test_the_build_command_refuses_without_a_chromium_before_any_model_round(home, cv_pdf, monkeypatch):
    monkeypatch.setattr(common, "_chromium_available", lambda: False)
    monkeypatch.setattr(style_cmd.style_build, "build", lambda *a, **k: pytest.fail("a round ran without Chromium"))
    result = CliRunner().invoke(cli, ["cv", "style", "build", str(cv_pdf)])
    assert result.exit_code != 0
    assert f"no Chromium to print with: {doctor._CHROMIUM_FIX}" in result_text(result)


def test_a_scan_is_refused_with_the_verdict_and_leaves_the_existing_style_and_state_alone(home, world, cli_env):
    (cli_env.profile_dir / "style").mkdir()
    (cli_env.profile_dir / "style" / "cv.template.html").write_text("kept")
    with pytest.raises(ValueError, match="text layer"):
        style_cmd._start_core(str(STYLES / "scan.pdf"))
    assert world.spawned == [] and not (home / ".style").exists()
    assert (cli_env.profile_dir / "style" / "cv.template.html").read_text() == "kept"


def test_the_command_exits_non_zero_with_the_reason(home, tmp_path):
    docx = tmp_path / "cv.docx"
    docx.write_bytes(b"x")
    result = CliRunner().invoke(cli, ["cv", "style", "build", str(docx)])
    assert result.exit_code != 0
    assert "no layout to copy" in result_text(result)


# ----------------------------------------------------------------------------- the foreground build
def test_the_core_builds_in_its_work_folder_and_records_building_then_the_result(home, cli_env, cv_pdf, monkeypatch):
    seen = {}

    def fake_build(pdf, *, work_dir, profile_dir, progress=None, **kw):
        seen.update(pdf=pdf, work_dir=work_dir, profile_dir=profile_dir, during=_run(home))
        return dict(READY)

    monkeypatch.setattr(style_build, "build", fake_build)
    result = style_cmd._build_core(str(cv_pdf))
    assert result == READY
    assert seen["work_dir"] == home / ".style" / "work" and seen["profile_dir"] == cli_env.profile_dir
    assert seen["during"]["state"] == "building" and seen["during"]["pid"] > 0 and seen["during"]["started_at"]
    done = _run(home)
    assert done["state"] == "ready" and done["result"] == READY and done["pid"] == seen["during"]["pid"]


def test_a_failed_result_is_recorded_as_failed(home, cv_pdf, monkeypatch):
    monkeypatch.setattr(style_build, "build", lambda *a, **k: {**READY, "state": "failed", "problems": ["no luck"]})
    style_cmd._build_core(str(cv_pdf))
    assert _run(home)["state"] == "failed" and _run(home)["result"]["problems"] == ["no luck"]


def test_a_build_that_raises_is_recorded_as_failed_and_raised(home, cv_pdf, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("disk")

    monkeypatch.setattr(style_build, "build", boom)
    with pytest.raises(RuntimeError):
        style_cmd._build_core(str(cv_pdf))
    assert _run(home)["state"] == "failed" and "disk" in _run(home)["result"]["problems"][0]


def test_the_core_refuses_intake_before_it_writes_any_state(home, tmp_path):
    docx = tmp_path / "cv.docx"
    docx.write_bytes(b"x")
    with pytest.raises(ValueError):
        style_cmd._build_core(str(docx))
    assert not (home / ".style").exists()


def test_a_foreground_build_ends_one_that_is_running_elsewhere(home, cv_pdf, monkeypatch, world):
    (home / ".style").mkdir()
    (home / ".style" / "run.json").write_text(json.dumps({"pid": 4242, "state": "building", "started_at": "t"}))
    world.hold(home)
    monkeypatch.setattr(style_build, "build", lambda *a, **k: dict(READY))
    style_cmd._build_core(str(cv_pdf))
    assert world.killed == [4242]


def test_the_command_prints_the_result_and_fails_when_the_build_failed(home, cv_pdf, monkeypatch):
    monkeypatch.setattr(style_build, "build", lambda *a, **k: dict(READY))
    ok = CliRunner().invoke(cli, ["cv", "style", "build", str(cv_pdf)])
    assert ok.exit_code == 0 and "ready" in result_text(ok).lower()
    monkeypatch.setattr(style_build, "build", lambda *a, **k: {**READY, "state": "failed", "problems": ["the stress renders failed"]})
    bad = CliRunner().invoke(cli, ["cv", "style", "build", str(cv_pdf)])
    assert bad.exit_code != 0 and "the stress renders failed" in result_text(bad)


def test_a_ready_build_with_no_fonts_downloaded_says_why(home, cv_pdf, monkeypatch):
    monkeypatch.setattr(style_build, "build", lambda *a, **k: {**READY, "font_error": "google/fonts unreachable"})
    ok = CliRunner().invoke(cli, ["cv", "style", "build", str(cv_pdf)])
    assert ok.exit_code == 0 and "google/fonts unreachable" in result_text(ok)


# ----------------------------------------------------------------------------- starting it detached
def test_start_copies_the_pdf_spawns_the_build_detached_and_returns_at_once(home, cv_pdf, world):
    assert style_cmd._start_core(str(cv_pdf)) == {"started": True}
    copy = home / ".style" / "source.pdf"
    assert copy.read_bytes() == cv_pdf.read_bytes()
    (spawned,) = world.spawned
    assert spawned["argv"] == [sys.executable, "-m", "door", "cv", "style", "build", str(copy)]
    assert spawned["log"] == home / ".style" / "build.log"
    assert spawned["env"]["DOOR_HOME"] == str(home)
    assert spawned["hidden_console"] is True
    run = _run(home)
    assert run["state"] == "building" and run["started_at"] and "pid" not in run


def test_start_ends_a_running_build_first(home, cv_pdf, world):
    (home / ".style").mkdir()
    (home / ".style" / "run.json").write_text(json.dumps({"pid": 4242, "state": "building", "started_at": "t"}))
    world.hold(home)
    style_cmd._start_core(str(cv_pdf))
    assert world.killed == [4242] and len(world.spawned) == 1


def test_start_leaves_a_finished_build_alone(home, cv_pdf, world):
    (home / ".style").mkdir()
    (home / ".style" / "run.json").write_text(json.dumps({"pid": 4242, "state": "ready", "started_at": "t"}))
    world.hold(home)  # a reused pid: a finished build is not ended
    style_cmd._start_core(str(cv_pdf))
    assert world.killed == []


def test_the_tool_starts_a_build_and_says_so(home, cv_pdf, monkeypatch, world):
    assert mcp_server.build_style(str(cv_pdf)) == {"started": True}
    assert len(world.spawned) == 1


def test_the_tool_answers_intake_in_words(home, tmp_path):
    docx = tmp_path / "cv.docx"
    docx.write_bytes(b"x")
    assert "no layout to copy" in mcp_server.build_style(str(docx))["error"]


# ----------------------------------------------------------------------------- ending a build
def test_a_build_never_ends_the_process_that_is_itself_or_its_launcher(home, cv_pdf, monkeypatch, world):
    monkeypatch.setattr(style_cmd, "LOCK_WAIT", 0.1)
    for own in (os.getpid(), os.getppid()):
        _state(home, pid=own, state="building", started_at=_now())
        world.hold(home)
        with pytest.raises(ValueError, match="still running"):
            style_cmd._build_core(str(cv_pdf))
        assert world.killed == []
        world.holders.pop().release()


def test_a_stale_building_record_names_a_pid_that_is_not_ended(home, cv_pdf, world):
    _state(home, pid=os.getpid(), state="building", started_at=_now(-3600))  # nothing holds the lock
    style_cmd._start_core(str(cv_pdf))
    assert world.killed == [] and len(world.spawned) == 1


def test_a_build_waits_for_the_one_it_replaced_to_let_go_of_the_lock(home, cv_pdf, monkeypatch, world):
    world.hold(home)
    monkeypatch.setattr(style_build, "build", lambda *a, **k: dict(READY))
    import threading

    threading.Timer(0.5, world.holders[0].release).start()
    assert style_cmd._build_core(str(cv_pdf)) == READY


def test_the_lock_is_held_for_the_whole_build_and_let_go_after(home, cv_pdf, monkeypatch):
    seen = {}
    monkeypatch.setattr(style_build, "build", lambda *a, **k: seen.update(held=lock.held(style_cmd._lock_path(home))) or dict(READY))
    style_cmd._build_core(str(cv_pdf))
    assert seen["held"] is True and lock.held(style_cmd._lock_path(home)) is False


def test_a_build_that_is_asked_to_stop_ends_its_print_and_is_recorded_failed(home, cv_pdf, monkeypatch):
    # SIGTERM must unwind (the print's finally kills Chromium, which has a session of its own), not just end the process
    before = signal.getsignal(signal.SIGTERM)
    cleaned = []

    def build(*a, **k):
        try:
            signal.raise_signal(signal.SIGTERM)
        finally:
            cleaned.append(True)

    monkeypatch.setattr(style_build, "build", build)
    with pytest.raises(SystemExit):
        style_cmd._build_core(str(cv_pdf))
    assert cleaned == [True] and _run(home)["state"] == "failed"
    assert signal.getsignal(signal.SIGTERM) == before


def test_a_build_that_was_replaced_does_not_write_over_the_newer_one(home, cv_pdf, monkeypatch):
    def build(*a, **k):
        _state(home, pid=os.getpid() + 1, state="building", started_at=_now())  # the new build's record
        raise SystemExit(143)

    monkeypatch.setattr(style_build, "build", build)
    with pytest.raises(SystemExit):
        style_cmd._build_core(str(cv_pdf))
    assert _run(home)["state"] == "building" and _run(home)["pid"] == os.getpid() + 1


def test_a_start_whose_process_refuses_the_file_is_recorded_failed_and_the_log_says_why(home, tmp_path, monkeypatch):
    # the real process, no stand-ins but a file where the child looks for Chromium: the copy is not a PDF, so it leaves at once
    key = chromium.platform_key()
    shell = tmp_path / "bin" / "chromium" / f"chrome-headless-shell-{key}" / chromium.exe_name(key)
    shell.parent.mkdir(parents=True)
    shell.write_bytes(b"")
    monkeypatch.setenv("DOOR_BIN", str(tmp_path / "bin"))
    copy = home / ".style" / "source.pdf"
    copy.parent.mkdir()
    copy.write_bytes(b"not a pdf")
    style_cmd._spawn(home, copy)
    deadline = time.monotonic() + 90
    while _run(home)["state"] == "building" and time.monotonic() < deadline:
        time.sleep(0.3)
    assert _run(home)["state"] == "failed"
    assert "could not be read as a PDF" in (home / ".style" / "build.log").read_text()
    assert style_cmd.status(home, home / "profile")["state"] == "failed"


# ----------------------------------------------------------------------------- the status block
def _state(home, **run):
    (home / ".style").mkdir(exist_ok=True)
    (home / ".style" / "run.json").write_text(json.dumps(run))


def _template(cli_env, folder="style.next"):
    (cli_env.profile_dir / folder).mkdir(exist_ok=True)
    (cli_env.profile_dir / folder / "cv.template.html").write_text("x")


def test_status_is_none_without_a_build_or_a_template(home, cli_env):
    assert style_cmd.status(home, cli_env.profile_dir) == {"state": "none"}


def test_status_is_building_while_the_build_holds_its_lock(home, cli_env, world):
    _state(home, pid=5, state="building", started_at="t0")
    world.hold(home)
    assert style_cmd.status(home, cli_env.profile_dir) == {"state": "building", "started_at": "t0"}


def test_status_is_building_in_the_moment_between_the_start_and_the_builds_first_write(home, cli_env):
    _state(home, state="building", started_at=_now())
    assert style_cmd.status(home, cli_env.profile_dir)["state"] == "building"


def test_a_stale_building_with_a_live_unrelated_pid_reads_failed(home, cli_env):
    # a reboot left it, and the pid now belongs to some other process: nothing holds the lock
    _state(home, pid=os.getpid(), state="building", started_at=_now(-3600))
    got = style_cmd.status(home, cli_env.profile_dir)
    assert got["state"] == "failed" and got["problems"]


def test_status_is_failed_with_the_problems_the_build_gave(home, cli_env):
    _state(home, pid=5, state="failed", started_at="t0", result={"problems": ["no luck"]})
    assert style_cmd.status(home, cli_env.profile_dir) == {"state": "failed", "problems": ["no luck"]}


def test_status_is_ready_when_the_template_exists_and_names_the_fonts_and_icons_of_the_last_result(home, cli_env):
    _template(cli_env)
    _state(home, pid=5, state="ready", started_at="t0", result=READY)
    assert style_cmd.status(home, cli_env.profile_dir) == {
        "state": "ready", "fonts": READY["fonts"], "dropped_icons": READY["dropped_icons"]}


def test_a_failed_build_does_not_hide_the_candidate_that_waits(home, cli_env):
    _template(cli_env)
    _state(home, pid=5, state="failed", started_at="t0", result={"problems": ["no luck"]})
    assert style_cmd.status(home, cli_env.profile_dir)["state"] == "ready"


def test_a_build_in_progress_comes_before_a_waiting_candidate(home, cli_env, world):
    _template(cli_env)
    _state(home, pid=5, state="building", started_at="t0")
    world.hold(home)
    assert style_cmd.status(home, cli_env.profile_dir)["state"] == "building"


def test_a_style_in_use_and_no_candidate_is_nothing_to_choose(home, cli_env):
    _template(cli_env, "style")
    _state(home, pid=5, state="ready", started_at="t0", result=READY)
    assert style_cmd.status(home, cli_env.profile_dir) == {"state": "none"}


def test_status_is_ready_with_a_template_and_no_run_record(home, cli_env):
    _template(cli_env)
    assert style_cmd.status(home, cli_env.profile_dir) == {"state": "ready"}


def test_status_summary_carries_the_style_block(home, cli_env):
    assert status_cmd._status_summary_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)["style"] == {"state": "none"}


# ----------------------------------------------------------------------------- `show`
@pytest.fixture
def shown(monkeypatch):
    calls = []

    def fake_show(home, profile_dir, config):
        calls.append((home, profile_dir, config))
        return {"styles": {"default": {"cv": ["/x/cv_page_1.png"], "letter": ["/x/letter_page_1.png"]}}}

    monkeypatch.setattr(style_preview, "show", fake_show)
    return calls


def test_the_show_core_gives_the_previews_of_the_profile_in_the_home(home, cli_env, shown):
    result = style_cmd._show_core()
    assert result["styles"]["default"]["cv"] == ["/x/cv_page_1.png"]
    assert shown[0][0] == home and shown[0][1] == cli_env.profile_dir


def test_the_show_core_says_which_style_is_in_use_and_whether_a_candidate_waits(home, cli_env, shown):
    assert style_cmd._show_core()["in_use"] == "default" and style_cmd._show_core()["candidate"] is False
    _template(cli_env)
    assert style_cmd._show_core()["candidate"] is True
    _template(cli_env, "style")
    config = json.loads((cli_env.profile_dir / "config.json").read_text())
    (cli_env.profile_dir / "config.json").write_text(json.dumps({**config, "cv_template": "profile/style/cv.template.html"}))
    assert style_cmd._show_core()["in_use"] == "like"


def test_the_show_core_works_with_no_config(home, cli_env, shown):
    (cli_env.profile_dir / "config.json").unlink(missing_ok=True)
    assert style_cmd._show_core()["styles"]
    assert shown[0][2] == {}


def test_the_show_command_names_each_image(home, cli_env, shown):
    result = CliRunner().invoke(cli, ["cv", "style", "show"])
    assert result.exit_code == 0
    text = result_text(result)
    assert "default" in text and "cv_page_1.png" in text and "letter_page_1.png" in text


def test_the_show_command_says_when_nothing_could_be_printed(home, cli_env, monkeypatch):
    monkeypatch.setattr(style_preview, "show", lambda *a: {"styles": {}})
    result = CliRunner().invoke(cli, ["cv", "style", "show"])
    assert result.exit_code == 0 and "doctor" in result_text(result)


def test_the_show_tool_is_a_writing_tool_the_phone_does_not_get(home, cli_env, shown):
    from door import serve_policy
    assert "show_style" in mcp_server.WRITING_TOOLS and "show_style" not in serve_policy.PHONE_TOOLS
    assert asyncio.run(mcp_server.show_style())["styles"]["default"]["letter"] == ["/x/letter_page_1.png"]
