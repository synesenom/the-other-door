"""`cv style use` and the `use_style` tool (#151): which CV style is in use (the two template keys pointing into
profile/style/), the candidate a build leaves in profile/style.next/, and the re-render of prepared applications. The
print is stood in; no model is called."""

import asyncio
import json
import shutil
import time

import pytest
from click.testing import CliRunner

from door import mcp_server
from door.cli import cli
from door.commands import compile as compile_cmd
from door.commands import style as style_cmd
from door.core import templates, tracker, workspace
from door.core.profile_loader import load_config
from cli_utils import result_text
from paths import REPO_ROOT

CV = "cv.template.html"
LETTER = "cover-letter.template.html"


@pytest.fixture
def home(cli_env, tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    return tmp_path


def _folder(cli_env, name, mark="x"):
    folder = cli_env.profile_dir / name
    folder.mkdir()
    for file in (CV, LETTER):
        shutil.copyfile(REPO_ROOT / "profile.example" / file, folder / file)
    (folder / "mark.txt").write_text(mark)
    return folder


def _keys(cli_env):
    config = json.loads((cli_env.profile_dir / "config.json").read_text())
    return config.get("cv_template"), config.get("cover_letter_template")


def _set_keys(cli_env, cv, letter):
    path = cli_env.profile_dir / "config.json"
    config = json.loads(path.read_text())
    path.write_text(json.dumps({**config, "cv_template": cv, "cover_letter_template": letter}))


IN_USE = ("profile/style/cv.template.html", "profile/style/cover-letter.template.html")


def test_like_moves_the_candidate_in_and_sets_both_keys_relative_to_the_home(home, cli_env):
    _folder(cli_env, "style.next", "new")
    result = style_cmd._use_core("like")
    assert result["in_use"] == "like"
    assert (cli_env.profile_dir / "style" / "mark.txt").read_text() == "new" and not (cli_env.profile_dir / "style.next").exists()
    assert _keys(cli_env) == IN_USE
    config = load_config(cli_env.profile_dir / "config.json")
    assert templates.resolve("cv_template", config).resolve() == (cli_env.profile_dir / "style" / CV).resolve()


def test_like_replaces_an_earlier_style_with_the_candidate(home, cli_env):
    _folder(cli_env, "style", "old")
    _folder(cli_env, "style.next", "new")
    style_cmd._use_core("like")
    assert (cli_env.profile_dir / "style" / "mark.txt").read_text() == "new"
    assert not (cli_env.profile_dir / ".style.old").exists()


def test_like_without_a_candidate_goes_back_to_the_kept_style(home, cli_env):
    _folder(cli_env, "style", "kept")
    assert style_cmd._use_core("like")["in_use"] == "like"
    assert _keys(cli_env) == IN_USE and (cli_env.profile_dir / "style" / "mark.txt").read_text() == "kept"


def test_like_with_nothing_built_is_an_error_in_words(home, cli_env):
    with pytest.raises(ValueError, match="no CV style is built"):
        style_cmd._use_core("like")


def test_default_clears_keys_that_point_into_the_style_folder_and_keeps_the_style(home, cli_env):
    _folder(cli_env, "style", "kept")
    _set_keys(cli_env, *IN_USE)
    assert style_cmd._use_core("default")["in_use"] == "default"
    assert _keys(cli_env) == (None, None) and (cli_env.profile_dir / "style" / "mark.txt").read_text() == "kept"


def test_default_leaves_a_template_of_the_users_own_alone(home, cli_env):
    own = home / "mine.html"
    own.write_text("<html></html>")
    _set_keys(cli_env, str(own), None)
    style_cmd._use_core("default")
    assert _keys(cli_env) == (str(own), None)


def test_default_deletes_the_candidate_when_a_built_style_is_already_kept(home, cli_env):
    _folder(cli_env, "style", "kept")
    _folder(cli_env, "style.next", "new")
    style_cmd._use_core("default")
    assert not (cli_env.profile_dir / "style.next").exists() and (cli_env.profile_dir / "style" / "mark.txt").read_text() == "kept"


def test_default_keeps_the_first_candidate_as_the_style_to_switch_to_later(home, cli_env):
    _folder(cli_env, "style.next", "new")
    assert style_cmd._use_core("default")["in_use"] == "default"
    assert (cli_env.profile_dir / "style" / "mark.txt").read_text() == "new" and not (cli_env.profile_dir / "style.next").exists()
    assert _keys(cli_env) == (None, None)


def test_current_changes_nothing_in_use_and_ends_the_candidate(home, cli_env):
    _folder(cli_env, "style", "old")
    _folder(cli_env, "style.next", "new")
    _set_keys(cli_env, *IN_USE)
    assert style_cmd._use_core("current")["in_use"] == "like"
    assert _keys(cli_env) == IN_USE and (cli_env.profile_dir / "style" / "mark.txt").read_text() == "old"
    assert not (cli_env.profile_dir / "style.next").exists()


def test_current_with_the_default_in_use_and_a_first_candidate_keeps_it_unused(home, cli_env):
    _folder(cli_env, "style.next", "new")
    assert style_cmd._use_core("current")["in_use"] == "default"
    assert (cli_env.profile_dir / "style" / "mark.txt").read_text() == "new" and _keys(cli_env) == (None, None)


def test_a_template_of_the_users_own_reads_as_the_default_in_use(home, cli_env):
    own = home / "mine.html"
    own.write_text("<html></html>")
    _set_keys(cli_env, str(own), None)
    _folder(cli_env, "style", "kept")
    assert templates.in_use(cli_env.profile_dir, json.loads((cli_env.profile_dir / "config.json").read_text())) == "default"


def test_like_overwrites_the_users_own_keys(home, cli_env):
    own = home / "mine.html"
    own.write_text("<html></html>")
    _set_keys(cli_env, str(own), str(own))
    _folder(cli_env, "style.next")
    style_cmd._use_core("like")
    assert _keys(cli_env) == IN_USE


# ----------------------------------------------------------------------------- re-render
def _job(home, job_id, status, *, html=True, tex=False):
    out = home / "jobs" / "output" / job_id
    out.mkdir(parents=True)
    (out / "posting.json").write_text(json.dumps({"title": "T", "company": "C"}))
    if html:
        (out / "cv.html").write_text("<h1>A</h1>")
    if tex:
        (out / "cv.tex").write_text("x")
    ledger = tracker.ApplicationTracker(home / "jobs" / "applications.json")
    ledger.set_status(job_id, status)
    ledger.save()


@pytest.fixture
def compiled(monkeypatch):
    calls = []

    def fake(job_id, render=False, jobs_dir=None):
        calls.append((job_id, render))
        if job_id.endswith("bad"):
            raise ValueError("no way")
        if job_id.endswith("err"):
            return {"job_id": job_id, "results": [{"file": "cv.html", "status": "error", "stderr": "refused"}]}
        return {"job_id": job_id, "results": []}

    monkeypatch.setattr(compile_cmd, "_compile_core", fake)
    return calls


def test_prepared_jobs_are_counted_whether_or_not_they_are_rerendered(home, cli_env, compiled):
    _folder(cli_env, "style.next")
    _job(home, "a.1", "prepared")
    _job(home, "a.2", "applied")
    _job(home, "a.3", "unapplied")
    _job(home, "a.4", "prepared", html=False, tex=True)
    result = style_cmd._use_core("like")
    assert result["prepared"] == 1 and "rerendered" not in result and compiled == []


def test_rerender_prints_the_prepared_jobs_again_and_only_those(home, cli_env, compiled):
    _folder(cli_env, "style")
    _job(home, "a.1", "prepared")
    _job(home, "a.2", "applied")
    _job(home, "a.4", "prepared", html=False, tex=True)
    result = style_cmd._use_core("like", rerender=True)
    assert compiled == [("a.1", True)] and result["rerendered"] == ["a.1"] and result["failed"] == []


def test_a_job_that_fails_to_print_is_listed_and_the_rest_go_on(home, cli_env, compiled):
    _folder(cli_env, "style")
    _job(home, "a.bad", "prepared")
    _job(home, "b.1", "prepared")
    result = style_cmd._use_core("like", rerender=True)
    assert result["rerendered"] == ["b.1"] and result["failed"] == ["a.bad"]


def test_a_job_whose_compile_answers_an_error_is_failed_not_rerendered(home, cli_env, compiled):
    _folder(cli_env, "style")
    _job(home, "a.err", "prepared")
    _job(home, "b.1", "prepared")
    result = style_cmd._use_core("like", rerender=True)
    assert result["rerendered"] == ["b.1"] and result["failed"] == ["a.err"]


def test_rerender_never_moves_in_or_ends_a_candidate(home, cli_env, compiled):
    _folder(cli_env, "style", "kept")
    _set_keys(cli_env, *IN_USE)
    _folder(cli_env, "style.next", "newer")
    assert style_cmd._use_core("current", rerender=True)["in_use"] == "like"
    assert (cli_env.profile_dir / "style.next" / "mark.txt").read_text() == "newer"
    assert (cli_env.profile_dir / "style" / "mark.txt").read_text() == "kept"


def test_like_without_a_profile_refuses_in_words_and_writes_nothing(home, cli_env):
    _folder(cli_env, "style.next")
    (cli_env.profile_dir / "config.json").unlink()
    with pytest.raises(ValueError, match="profile"):
        style_cmd._use_core("like")
    assert not (cli_env.profile_dir / "config.json").exists()
    assert (cli_env.profile_dir / "style.next").is_dir()


def _crash(cli_env):
    """A swap that died between setting the style in use aside and moving the candidate in."""
    _folder(cli_env, "style", "earlier")
    (cli_env.profile_dir / "style").rename(cli_env.profile_dir / ".style.old")
    _folder(cli_env, "style.next", "new")
    _set_keys(cli_env, *IN_USE)


def test_use_after_an_interrupted_swap_brings_the_earlier_style_back(home, cli_env):
    _crash(cli_env)
    assert style_cmd._use_core("current")["in_use"] == "like"
    assert (cli_env.profile_dir / "style" / "mark.txt").read_text() == "earlier"
    assert not (cli_env.profile_dir / "style.next").exists()


def test_show_after_an_interrupted_swap_brings_the_earlier_style_back(home, cli_env):
    _crash(cli_env)
    assert style_cmd._show_core(home=home, profile_dir=cli_env.profile_dir)["in_use"] == "like"
    assert (cli_env.profile_dir / "style" / "mark.txt").read_text() == "earlier"
    assert (cli_env.profile_dir / "style.next").is_dir()


def test_status_after_an_interrupted_swap_brings_the_earlier_style_back(home, cli_env):
    _crash(cli_env)
    style_cmd.status(home, cli_env.profile_dir)
    assert (cli_env.profile_dir / "style" / "mark.txt").read_text() == "earlier"


def test_an_interrupted_end_of_a_candidate_never_leaves_it_to_be_chosen(home, cli_env, monkeypatch):
    from door.tailoring import style_build
    _folder(cli_env, "style", "kept")
    _folder(cli_env, "style.next", "new")

    def killed(path, *a, **k):
        if (cli_env.profile_dir / "style.next").exists() or not path.exists():
            return None  # only the delete of what was renamed away is cut short
        raise OSError("killed")

    monkeypatch.setattr(style_cmd.shutil, "rmtree", killed)
    with pytest.raises(OSError):
        style_cmd._use_core("current")
    style_build.restore(cli_env.profile_dir)
    assert not (cli_env.profile_dir / "style.next").exists()


# ----------------------------------------------------------------------------- command and tool
def test_the_command_says_which_style_is_in_use(home, cli_env, compiled):
    _folder(cli_env, "style.next")
    result = CliRunner().invoke(cli, ["cv", "style", "use"])
    assert result.exit_code == 0 and "Your own style is in use" in result_text(result)
    result = CliRunner().invoke(cli, ["cv", "style", "use", "default"])
    assert result.exit_code == 0 and "The other door's style is in use" in result_text(result)


def test_the_command_exits_non_zero_when_nothing_is_built(home, cli_env):
    result = CliRunner().invoke(cli, ["cv", "style", "use", "like"])
    assert result.exit_code == 1 and "no CV style is built" in result_text(result)


def test_the_command_chooses_then_rerenders_with_the_flag(home, cli_env, compiled):
    _folder(cli_env, "style.next")
    _job(home, "a.1", "prepared")
    result = CliRunner().invoke(cli, ["cv", "style", "use", "like", "--rerender"])
    assert result.exit_code == 0 and compiled == [("a.1", True)] and "1" in result_text(result)
    assert (cli_env.profile_dir / "style" / CV).is_file() and not (cli_env.profile_dir / "style.next").exists()


def test_the_tool_is_a_writing_tool_the_phone_does_not_get_and_answers_in_words(home, cli_env, compiled):
    from door import serve_policy
    assert "use_style" in mcp_server.WRITING_TOOLS and "use_style" not in serve_policy.PHONE_TOOLS
    assert "error" in asyncio.run(mcp_server.use_style("like"))
    _folder(cli_env, "style.next")
    assert asyncio.run(mcp_server.use_style("like", rerender=False))["in_use"] == "like"
    assert "error" in asyncio.run(mcp_server.use_style("sideways"))
