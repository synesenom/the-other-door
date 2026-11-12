"""`cv stories`: see, add, replace, remove and draft the story bank (profile/story_bank.md).

Offline: `claude_cli.ask` is replaced; nothing is asked of a model.
"""

import pytest
from click.testing import CliRunner

from door.cli import cli
from door.commands import _common as common
from door.commands import stories as stories_cmd
from door.core import claude_cli, workspace
from door.tailoring import StoryBank
from cli_utils import result_text
from profile_utils import write_config

STORY = {
    "title": "Cut the build time",
    "context": "Builds took an hour and had to be halved.",
    "action": "Cached dependencies.",
    "result": "Down to twenty minutes.",
    "learning": "Measure first.",
}
OTHER = {**STORY, "title": "Ran the migration"}


@pytest.fixture
def env(cli_env):
    write_config(cli_env.profile_dir, {"role_targets": ["x"], "cv_content": str(cli_env.profile_dir / "cv.md")})
    return cli_env


def _bank(env):
    return StoryBank(env.profile_dir / "story_bank.md")


def _seed(env, *stories):
    bank = _bank(env)
    for s in stories:
        bank.append(s)
    bank.save()


def _save(env, **kw):
    return stories_cmd._save_story_core(**{**STORY, **kw}, profile_dir=env.profile_dir)


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #

def test_list_missing_file(env):
    result = stories_cmd._list_stories_core(profile_dir=env.profile_dir)
    assert result == {"path": str(env.profile_dir / "story_bank.md"), "exists": False, "is_example": False, "stories": []}


def test_list_stories_have_the_five_carl_keys(env):
    _seed(env, STORY, OTHER)
    stories = stories_cmd._list_stories_core(profile_dir=env.profile_dir)["stories"]
    assert set(stories[0]) == {"title", "context", "action", "result", "learning"}


def test_list_flags_the_example_bank(env):
    (env.profile_dir / "story_bank.md").write_bytes((workspace.PROFILE_EXAMPLE_DIR / "story_bank.md").read_bytes())
    result = stories_cmd._list_stories_core(profile_dir=env.profile_dir)
    assert result["is_example"] is True and result["stories"]


# --------------------------------------------------------------------------- #
# save
# --------------------------------------------------------------------------- #

def test_save_adds(env):
    result = _save(env)
    assert result["outcome"] == "added" and "skills" not in result["story"]
    assert [s["title"] for s in _bank(env).stories] == ["Cut the build time"]


def test_save_names_the_empty_fields(env):
    with pytest.raises(ValueError, match="context.*result|result.*context") as exc:
        _save(env, context="  ", result="")
    assert "title" not in str(exc.value)
    assert not (env.profile_dir / "story_bank.md").exists()


def test_save_collapses_newlines_and_strips_markup(env):
    _save(env, title="## A title\nwith a break", action="**Action**: did\n\nthis\nand that")
    story = _bank(env).stories[0]
    assert story["title"] == "A title with a break"
    assert story["action"] == "did this and that"


def test_save_replace_renames_and_replaces(env):
    _seed(env, STORY, OTHER)
    result = _save(env, title="Cut the build time by half", result="Ten minutes.", replace="Cut the build time")
    assert result["outcome"] == "replaced"
    stories = _bank(env).stories
    assert [s["title"] for s in stories] == ["Cut the build time by half", "Ran the migration"]
    assert stories[0]["result"] == "Ten minutes."


def test_save_replace_unknown_is_an_error(env):
    _seed(env, STORY)
    with pytest.raises(ValueError, match="Nope"):
        _save(env, replace="Nope")


def test_save_existing_title_without_replace_is_an_error(env):
    _seed(env, STORY)
    with pytest.raises(ValueError, match="already"):
        _save(env, result="Different.")
    assert _bank(env).stories[0]["result"] == STORY["result"]


def _example_bank(env):
    (env.profile_dir / "story_bank.md").write_bytes((workspace.PROFILE_EXAMPLE_DIR / "story_bank.md").read_bytes())


def test_save_on_the_example_bank_is_refused(env):
    _example_bank(env)
    with pytest.raises(ValueError, match="made-up example"):
        _save(env)


def test_save_replace_example_starts_an_empty_bank(env):
    _example_bank(env)
    _save(env, replace_example=True)
    assert [s["title"] for s in _bank(env).stories] == ["Cut the build time"]


# --------------------------------------------------------------------------- #
# remove
# --------------------------------------------------------------------------- #

def test_remove_by_slug(env):
    _seed(env, STORY, OTHER)
    result = stories_cmd._remove_story_core("cut the BUILD time", profile_dir=env.profile_dir)
    assert result["outcome"] == "removed"
    assert [s["title"] for s in _bank(env).stories] == ["Ran the migration"]


def test_remove_miss_lists_the_titles(env):
    _seed(env, STORY, OTHER)
    with pytest.raises(ValueError, match="Ran the migration"):
        stories_cmd._remove_story_core("nope", profile_dir=env.profile_dir)


def test_remove_on_the_example_bank_is_refused(env):
    _example_bank(env)
    with pytest.raises(ValueError, match="made-up example"):
        stories_cmd._remove_story_core("Halved the Month-End Close at Acme Corp", profile_dir=env.profile_dir)


# --------------------------------------------------------------------------- #
# draft
# --------------------------------------------------------------------------- #

def _model(monkeypatch, stories, calls=None):
    def fake_ask(system, input, **kwargs):
        if calls is not None:
            calls.append({"system": system, "input": input, **kwargs})
        return {"stories": stories}
    monkeypatch.setattr(claude_cli, "ask", fake_ask)


def test_draft_needs_exactly_one_source(env, monkeypatch):
    _model(monkeypatch, [])
    with pytest.raises(ValueError):
        stories_cmd._draft_stories_core(profile_dir=env.profile_dir)
    with pytest.raises(ValueError):
        stories_cmd._draft_stories_core("text", True, profile_dir=env.profile_dir)


def test_draft_from_cv_without_a_cv_is_an_error(env, monkeypatch):
    _model(monkeypatch, [])
    with pytest.raises(FileNotFoundError, match="cv.md"):
        stories_cmd._draft_stories_core(from_cv=True, profile_dir=env.profile_dir)


def test_draft_from_text_asks_sonnet_without_tools_and_writes_nothing(env, monkeypatch):
    calls = []
    _model(monkeypatch, [{**STORY, "missing": []}], calls)
    result = stories_cmd._draft_stories_core("I cut the build time.", profile_dir=env.profile_dir)
    assert result["outcome"] == "proposed" and result["stories"][0]["title"] == STORY["title"]
    assert calls[0]["model"] == "sonnet" and not calls[0].get("allowed_tools")
    assert calls[0]["schema"] == stories_cmd._SCHEMA
    assert "I cut the build time." in calls[0]["input"]
    assert not (env.profile_dir / "story_bank.md").exists()


def test_draft_post_processing(env, monkeypatch):
    _seed(env, OTHER)
    _model(monkeypatch, [
        {**STORY, "missing": ["wrong"]},
        {**STORY, "title": "cut the BUILD time"},  # duplicate in proposals
        {"title": "", "context": "x"},  # untitled
        {"title": "Half drafted", "context": "s"},  # empty fields
    ])
    result = stories_cmd._draft_stories_core("I cut the build time.", profile_dir=env.profile_dir)
    titles = [s["title"] for s in result["stories"]]
    assert titles == ["Cut the build time", "Half drafted"]
    assert result["stories"][0]["missing"] == []
    assert result["stories"][1]["missing"] == ["action", "result", "learning"]


def test_draft_from_cv_is_one_story_to_show_what_a_story_is(env, monkeypatch):
    # onboarding's showcase: the CV only lists an achievement; one story shows what the bank adds to it
    _seed(env, OTHER)
    (env.profile_dir / "cv.md").write_text("# Jane\n\n- Cut the build time.\n- Ran the migration.\n")
    calls = []
    _model(monkeypatch, [{**OTHER}, {**STORY}, {**STORY, "title": "A third"}], calls)
    result = stories_cmd._draft_stories_core(from_cv=True, profile_dir=env.profile_dir)
    assert [s["title"] for s in result["stories"]] == ["Cut the build time"]  # the bank's own left out, then the first
    assert "exactly one story" in calls[0]["system"]


def test_draft_from_cv_reads_the_onboarding_draft(env, monkeypatch):
    (env.profile_dir / "cv.md").unlink(missing_ok=True)
    (env.profile_dir / "cv.draft.md").write_text("# Jane\n\n- Halved the close.\n")
    calls = []
    _model(monkeypatch, [STORY], calls)
    stories_cmd._draft_stories_core(from_cv=True, profile_dir=env.profile_dir)
    assert "Halved the close." in calls[0]["input"]


def test_draft_nothing_new(env, monkeypatch):
    _model(monkeypatch, [])
    assert stories_cmd._draft_stories_core("text", profile_dir=env.profile_dir) == {"outcome": "nothing_new", "stories": []}


def test_draft_bad_answer_is_a_claude_error(env, monkeypatch):
    monkeypatch.setattr(claude_cli, "ask", lambda *a, **k: {"nope": 1})
    with pytest.raises(claude_cli.ClaudeError):
        stories_cmd._draft_stories_core("text", profile_dir=env.profile_dir)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _run(*args, input=None):
    return CliRunner().invoke(cli, ["cv", "stories", *args], input=input)


def test_cli_bare_lists(env):
    _seed(env, STORY)
    result = _run()
    assert result.exit_code == 0 and "Cut the build time" in result.output


def test_cli_list_empty(env):
    assert "No stories" in _run("list").output


_FLAGS = ["--title", "Cut the build time", "--context", "S", "--action", "A", "--result", "R", "--learning", "X"]


def test_cli_add_with_flags(env):
    result = _run("add", *_FLAGS)
    assert result.exit_code == 0, result_text(result)
    assert _bank(env).stories[0]["context"] == "S"


def test_cli_add_replace(env):
    _seed(env, STORY)
    result = _run("add", *_FLAGS[:-2], "--learning", "New", "--replace", "Cut the build time")
    assert result.exit_code == 0, result_text(result)
    assert _bank(env).stories[0]["learning"] == "New"


def test_cli_add_missing_without_tty_names_the_fields(env, monkeypatch):
    monkeypatch.setattr(common, "_stdout_is_tty", lambda: False)
    result = _run("add", "--title", "T")
    assert result.exit_code == 1
    assert "context" in result_text(result) and "learning" in result_text(result)


def test_cli_add_prompts_for_missing_fields_on_a_tty(env, monkeypatch, prompts):
    monkeypatch.setattr(common, "_stdout_is_tty", lambda: True)
    prompts.answers.update(context="S", action="A", result="R", learning="X")
    result = _run("add", "--title", "Cut the build time")
    assert result.exit_code == 0, result_text(result)
    assert prompts.order == ["context", "action", "result", "learning"]
    assert _bank(env).stories[0]["action"] == "A"


def test_cli_add_from_text_drafts_prompts_for_gaps_and_saves(env, monkeypatch, prompts):
    monkeypatch.setattr(common, "_stdout_is_tty", lambda: True)
    _model(monkeypatch, [{**STORY, "learning": ""}])
    prompts.answers.update(learning="Measure.", save_story=True)
    result = _run("add", "--from-text", "I cut the build time.")
    assert result.exit_code == 0, result_text(result)
    assert prompts.order == ["learning", "save_story"]
    assert _bank(env).stories[0]["learning"] == "Measure."


def test_cli_add_from_text_declined_saves_nothing(env, monkeypatch, prompts):
    monkeypatch.setattr(common, "_stdout_is_tty", lambda: True)
    _model(monkeypatch, [STORY])
    prompts.answers["save_story"] = False
    result = _run("add", "--from-text", "x")
    assert result.exit_code == 0 and not (env.profile_dir / "story_bank.md").exists()


def test_cli_remove(env):
    _seed(env, STORY, OTHER)
    result = _run("remove", "Cut the build time")
    assert result.exit_code == 0, result_text(result)
    assert [s["title"] for s in _bank(env).stories] == ["Ran the migration"]
    assert _run("remove", "nope").exit_code == 1


def test_cli_draft_prints_proposals_and_writes_nothing(env, monkeypatch):
    _model(monkeypatch, [{**STORY, "learning": ""}])
    result = _run("draft", "I cut the build time.")
    assert result.exit_code == 0, result_text(result)
    assert "Cut the build time" in result.output and "learning" in result.output
    assert not (env.profile_dir / "story_bank.md").exists()


def test_cli_draft_from_cv(env, monkeypatch):
    (env.profile_dir / "cv.md").write_text("# Jane\n")
    _model(monkeypatch, [STORY])
    assert _run("draft", "--from-cv").exit_code == 0


def test_cli_draft_without_source_is_an_error(env):
    assert _run("draft").exit_code == 1


# --------------------------------------------------------------------------- #
# draft: the CV is read beside the text; conflicts
# --------------------------------------------------------------------------- #

def test_draft_from_text_also_reads_the_cv_as_data(env, monkeypatch):
    (env.profile_dir / "cv.md").write_text("# Jane\n\n- Cut the build time at Acme.\n")
    calls = []
    _model(monkeypatch, [{**STORY, "conflicts": []}], calls)
    stories_cmd._draft_stories_core("I cut the build time.", profile_dir=env.profile_dir)
    assert "I cut the build time." in calls[0]["input"] and "Cut the build time at Acme" in calls[0]["input"]
    assert "text wins" in calls[0]["system"].lower() or "text is right" in calls[0]["system"].lower()


def test_draft_from_text_without_a_cv_uses_the_text_only(env, monkeypatch):
    calls = []
    _model(monkeypatch, [STORY], calls)
    result = stories_cmd._draft_stories_core("I cut the build time.", profile_dir=env.profile_dir)
    assert result["outcome"] == "proposed"
    assert "I cut the build time." in calls[0]["input"] and "The CV" not in calls[0]["input"]


def test_draft_returns_conflicts_beside_missing(env, monkeypatch):
    (env.profile_dir / "cv.md").write_text("# Jane\n\n- Cut build time by 30%.\n")
    _model(monkeypatch, [
        {**STORY, "conflicts": ["The text says 50%, the CV says 30%.", 3, " "]},
        {**OTHER, "context": "", "conflicts": "not a list"},
    ])
    result = stories_cmd._draft_stories_core("Cut it by half.", profile_dir=env.profile_dir)
    first, second = result["stories"]
    assert first["conflicts"] == ["The text says 50%, the CV says 30%."] and first["missing"] == []
    assert second["conflicts"] == [] and second["missing"] == ["context"]


def test_cli_add_from_text_shows_conflicts(env, monkeypatch, prompts):
    monkeypatch.setattr(common, "_stdout_is_tty", lambda: True)
    _model(monkeypatch, [{**STORY, "conflicts": ["Text says 50%, CV says 30%."]}])
    prompts.answers["save_story"] = False
    result = _run("add", "--from-text", "x")
    assert "Text says 50%, CV says 30%." in result.output
