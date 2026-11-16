"""`cv style build` and the `build_style` tool (#205): intake, a build run in the foreground, a build started detached
with its state in HOME/.style/run.json, and the `style` block of `status_summary`. The builder (`style_build.build`)
and the process are stood in; no model is called."""

import json
import shutil
import sys

import pytest
from click.testing import CliRunner

from door import mcp_server
from door.cli import cli
from door.commands import status as status_cmd
from door.commands import style as style_cmd
from door.core import workspace
from door.tailoring import style_build
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


def _run(home):
    return json.loads((home / ".style" / "run.json").read_text(encoding="utf-8"))


class Process:
    def __init__(self, pid):
        self.pid = pid


class World:
    """Stand-ins for the process: `spawn` records what it was asked, `alive` is the set of live pids."""

    def __init__(self):
        self.spawned, self.killed, self.alive = [], [], set()

    def spawn(self, argv, *, log, env=None):
        self.spawned.append({"argv": argv, "log": log, "env": env})
        self.alive.add(777)
        return Process(777)

    def is_alive(self, pid):
        return pid in self.alive

    def kill(self, pid):
        self.killed.append(pid)
        self.alive.discard(pid)

    @property
    def deps(self):
        return {"spawn": self.spawn, "is_alive": self.is_alive, "kill": self.kill}


@pytest.fixture
def world():
    return World()


# ----------------------------------------------------------------------------- intake
def test_a_file_that_is_not_a_pdf_is_refused_in_words_and_nothing_starts(home, world, tmp_path):
    docx = tmp_path / "cv.docx"
    docx.write_bytes(b"x")
    with pytest.raises(ValueError, match="no layout to copy"):
        style_cmd._start_core(str(docx), **world.deps)
    assert world.spawned == [] and not (home / ".style").exists()


def test_a_scan_is_refused_with_the_verdict_and_leaves_the_existing_style_and_state_alone(home, world, cli_env):
    (cli_env.profile_dir / "style").mkdir()
    (cli_env.profile_dir / "style" / "cv.template.html").write_text("kept")
    with pytest.raises(ValueError, match="text layer"):
        style_cmd._start_core(str(STYLES / "scan.pdf"), **world.deps)
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
    world.alive.add(4242)
    monkeypatch.setattr(style_build, "build", lambda *a, **k: dict(READY))
    style_cmd._build_core(str(cv_pdf), **world.deps)
    assert world.killed == [4242]


def test_the_command_prints_the_result_and_fails_when_the_build_failed(home, cv_pdf, monkeypatch):
    monkeypatch.setattr(style_build, "build", lambda *a, **k: dict(READY))
    ok = CliRunner().invoke(cli, ["cv", "style", "build", str(cv_pdf)])
    assert ok.exit_code == 0 and "ready" in result_text(ok).lower()
    monkeypatch.setattr(style_build, "build", lambda *a, **k: {**READY, "state": "failed", "problems": ["the stress renders failed"]})
    bad = CliRunner().invoke(cli, ["cv", "style", "build", str(cv_pdf)])
    assert bad.exit_code != 0 and "the stress renders failed" in result_text(bad)


# ----------------------------------------------------------------------------- starting it detached
def test_start_copies_the_pdf_spawns_the_build_detached_and_returns_at_once(home, cv_pdf, world):
    assert style_cmd._start_core(str(cv_pdf), **world.deps) == {"started": True}
    copy = home / ".style" / "source.pdf"
    assert copy.read_bytes() == cv_pdf.read_bytes()
    (spawned,) = world.spawned
    assert spawned["argv"] == [sys.executable, "-m", "door", "cv", "style", "build", str(copy)]
    assert spawned["log"] == home / ".style" / "build.log"
    assert spawned["env"]["DOOR_HOME"] == str(home)
    run = _run(home)
    assert run["state"] == "building" and run["pid"] == 777


def test_start_ends_a_running_build_first(home, cv_pdf, world):
    (home / ".style").mkdir()
    (home / ".style" / "run.json").write_text(json.dumps({"pid": 4242, "state": "building", "started_at": "t"}))
    world.alive.add(4242)
    style_cmd._start_core(str(cv_pdf), **world.deps)
    assert world.killed == [4242] and len(world.spawned) == 1 and _run(home)["pid"] == 777


def test_start_leaves_a_finished_build_alone(home, cv_pdf, world):
    (home / ".style").mkdir()
    (home / ".style" / "run.json").write_text(json.dumps({"pid": 4242, "state": "ready", "started_at": "t"}))
    world.alive.add(4242)  # a reused pid
    style_cmd._start_core(str(cv_pdf), **world.deps)
    assert world.killed == []


def test_the_tool_refuses_a_path_outside_the_data_folder(home, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere") / "cv.pdf"
    shutil.copyfile(STYLES / "html-plain-single.pdf", outside)
    result = mcp_server.build_style(str(outside))
    assert "outside the data folder" in result["error"]


def test_the_tool_starts_a_build_and_says_so(home, cv_pdf, monkeypatch, world):
    monkeypatch.setattr(style_cmd, "_defaults", lambda: world.deps)
    assert mcp_server.build_style(str(cv_pdf)) == {"started": True}
    assert len(world.spawned) == 1


def test_the_tool_answers_intake_in_words(home, tmp_path):
    docx = tmp_path / "cv.docx"
    docx.write_bytes(b"x")
    assert "no layout to copy" in mcp_server.build_style(str(docx))["error"]


# ----------------------------------------------------------------------------- the status block
def _state(home, **run):
    (home / ".style").mkdir(exist_ok=True)
    (home / ".style" / "run.json").write_text(json.dumps(run))


def _template(cli_env):
    (cli_env.profile_dir / "style").mkdir(exist_ok=True)
    (cli_env.profile_dir / "style" / "cv.template.html").write_text("x")


def test_status_is_none_without_a_build_or_a_template(home, cli_env, world):
    assert style_cmd.status(home, cli_env.profile_dir, is_alive=world.is_alive) == {"state": "none"}


def test_status_is_building_while_the_process_lives(home, cli_env, world):
    _state(home, pid=5, state="building", started_at="t0")
    world.alive.add(5)
    assert style_cmd.status(home, cli_env.profile_dir, is_alive=world.is_alive) == {"state": "building", "started_at": "t0"}


def test_status_is_failed_when_the_process_died_mid_build(home, cli_env, world):
    _state(home, pid=5, state="building", started_at="t0")
    got = style_cmd.status(home, cli_env.profile_dir, is_alive=world.is_alive)
    assert got["state"] == "failed" and got["problems"]


def test_status_is_failed_with_the_problems_the_build_gave(home, cli_env, world):
    _template(cli_env)
    _state(home, pid=5, state="failed", started_at="t0", result={"problems": ["no luck"]})
    assert style_cmd.status(home, cli_env.profile_dir, is_alive=world.is_alive) == {"state": "failed", "problems": ["no luck"]}


def test_status_is_ready_when_the_template_exists_and_names_the_fonts_and_icons_of_the_last_result(home, cli_env, world):
    _template(cli_env)
    _state(home, pid=5, state="ready", started_at="t0", result=READY)
    assert style_cmd.status(home, cli_env.profile_dir, is_alive=world.is_alive) == {
        "state": "ready", "fonts": READY["fonts"], "dropped_icons": READY["dropped_icons"]}


def test_status_is_ready_with_a_template_and_no_run_record(home, cli_env, world):
    _template(cli_env)
    assert style_cmd.status(home, cli_env.profile_dir, is_alive=world.is_alive) == {"state": "ready"}


def test_status_summary_carries_the_style_block(home, cli_env):
    assert status_cmd._status_summary_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir)["style"] == {"state": "none"}
