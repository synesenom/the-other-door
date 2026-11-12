"""Title suggestions (`_titles_core`, the `suggest_titles` tool and `cv titles`): one `claude -p` call reads the
CV and proposes job titles with a reason each, before or after the profile exists.

Offline: `claude_cli.run` is replaced; nothing is executed.
"""

import json
import types

import pytest
from click.testing import CliRunner

import door.mcp_server as server
from cli_utils import result_text
from door.cli import cli
from door.commands import titles as titles_cmd
from door.core import claude_cli, workspace
from paths import REPO_ROOT
from profile_utils import write_config

CV = "# Jane Doe\n\n### Team Lead | Acme — 2021 - present\n\n### Analyst | Bank — 2015 - 2021\n"


@pytest.fixture
def env(tmp_path, monkeypatch):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(workspace, "PROFILE_EXAMPLE_DIR", REPO_ROOT / "profile.example")
    (profile_dir / "cv.draft.md").write_text(CV)
    return types.SimpleNamespace(profile_dir=profile_dir)


def _answer(monkeypatch, titles, calls=None):
    def fake_run(args, *, input=None, timeout_s=None, profile_dir=None, **_):
        if calls is not None:
            calls.append({"args": args, "input": input, "profile_dir": profile_dir})
        return json.dumps({"result": json.dumps({"titles": titles})})
    monkeypatch.setattr(claude_cli, "run", fake_run)


def _title(title, reason="why", recommended=True):
    return {"title": title, "reason": reason, "recommended": recommended}


def test_core_asks_claude_with_the_rules_the_cv_and_the_languages(env, monkeypatch):
    calls = []
    _answer(monkeypatch, [_title("Team Lead")], calls)
    result = titles_cmd._titles_core(languages=["Danish"], hint="something with people", profile_dir=env.profile_dir)

    assert result == {"titles": [_title("Team Lead")]}
    args, prompt = calls[0]["args"], calls[0]["input"]
    assert args[args.index("--system-prompt") + 1] == titles_cmd._RULES
    assert json.loads(args[args.index("--json-schema") + 1]) == titles_cmd._SCHEMA
    assert args[args.index("--model") + 1] == titles_cmd._DEFAULT_MODEL
    assert args[args.index("--tools") + 1] == ""
    assert calls[0]["profile_dir"] == env.profile_dir
    assert CV.strip() in prompt
    assert "English, Danish" in prompt and "something with people" in prompt
    for rule in ("latest title", "progression", "seniority"):
        assert rule in titles_cmd._RULES


def test_core_reads_the_cv_when_no_draft_is_left(env, monkeypatch):
    calls = []
    _answer(monkeypatch, [_title("Team Lead")], calls)
    (env.profile_dir / "cv.draft.md").unlink()
    (env.profile_dir / "cv.md").write_text("# Written later\n")
    titles_cmd._titles_core(profile_dir=env.profile_dir)
    assert "Written later" in calls[0]["input"]


def test_core_uses_the_profiles_languages_and_cv_path(env, tmp_path, monkeypatch):
    calls = []
    _answer(monkeypatch, [_title("Team Lead")], calls)
    (env.profile_dir / "cv.draft.md").unlink()
    write_config(env.profile_dir, {"languages": ["English", "Hungarian"]})
    cv_path = json.loads((env.profile_dir / "config.json").read_text())["cv_content"]
    with open(cv_path, "w") as f:
        f.write("# In another place\n")
    titles_cmd._titles_core(profile_dir=env.profile_dir)
    assert "English, Hungarian" in calls[0]["input"] and "In another place" in calls[0]["input"]


def test_the_users_own_titles_are_always_in_and_recommended(env, monkeypatch):
    calls = []
    _answer(monkeypatch, [_title("Head of Data", "led 5 people"), _title("data scientist", "matches", False)], calls)
    result = titles_cmd._titles_core(["Data Scientist", "Quant"], profile_dir=env.profile_dir)
    assert result["titles"] == [
        _title("Data Scientist", "matches"),
        _title("Quant", titles_cmd._OWN_REASON),
        _title("Head of Data", "led 5 people"),
    ]
    assert "Data Scientist; Quant" in calls[0]["input"]


def test_the_list_is_trimmed_deduplicated_and_capped(env, monkeypatch):
    many = [_title(f"Role {i}", recommended=False) for i in range(30)]
    _answer(monkeypatch, [_title("  Team   Lead "), _title("team lead"), _title(" "), "nonsense", *many])
    titles = titles_cmd._titles_core(profile_dir=env.profile_dir)["titles"]
    assert titles[0]["title"] == "Team Lead"
    assert len(titles) == titles_cmd._MAX_TITLES
    assert [t["title"].lower() for t in titles].count("team lead") == 1


def test_the_cap_never_drops_the_users_own_titles(env, monkeypatch):
    own = [f"Own {i}" for i in range(titles_cmd._MAX_TITLES + 2)]
    _answer(monkeypatch, [_title("Theirs")])
    titles = titles_cmd._titles_core(own, profile_dir=env.profile_dir)["titles"]
    assert [t["title"] for t in titles] == own


def test_something_is_preselected_when_the_model_recommends_nothing(env, monkeypatch):
    _answer(monkeypatch, [_title(f"Role {i}", recommended=False) for i in range(5)])
    titles = titles_cmd._titles_core(profile_dir=env.profile_dir)["titles"]
    assert [t["recommended"] for t in titles] == [True, True, True, False, False]


def test_a_failed_call_is_a_warning_with_the_users_own_titles(env, monkeypatch):
    def boom(*a, **k):
        raise claude_cli.ClaudeError("not logged in")
    monkeypatch.setattr(claude_cli, "run", boom)
    result = titles_cmd._titles_core(["Quant"], profile_dir=env.profile_dir)
    assert result == {"titles": [_title("Quant", titles_cmd._OWN_REASON)], "warning": "not logged in"}


def test_an_empty_answer_is_a_warning(env, monkeypatch):
    _answer(monkeypatch, [])
    result = titles_cmd._titles_core(profile_dir=env.profile_dir)
    assert result["titles"] == [] and "no titles" in result["warning"]


@pytest.mark.parametrize("cv", [None, "example"])
def test_no_cv_of_the_users_own_asks_no_model(env, monkeypatch, cv):
    monkeypatch.setattr(claude_cli, "run", lambda *a, **k: pytest.fail("no CV, no call"))
    (env.profile_dir / "cv.draft.md").unlink()
    if cv:
        (env.profile_dir / "cv.md").write_text((workspace.PROFILE_EXAMPLE_DIR / "cv.md").read_text())
    result = titles_cmd._titles_core(profile_dir=env.profile_dir)
    assert result["titles"] == [] and "no CV" in result["warning"]


def test_tool_passes_its_arguments(env, monkeypatch):
    seen = {}
    monkeypatch.setattr(titles_cmd, "_titles_core", lambda titles, **kw: seen.update(titles=titles, **kw) or {"titles": []})
    assert server.suggest_titles(["Quant"], hint="h", languages=["Danish"], model="sonnet") == {"titles": []}
    assert seen == {"titles": ["Quant"], "hint": "h", "languages": ["Danish"], "model": "sonnet", "profile_dir": env.profile_dir}


def test_cv_titles_prints_the_titles_with_their_reasons(env, monkeypatch):
    _answer(monkeypatch, [_title("Head of Data", "led a team of 5"), _title("Quant", "maths", False)])
    result = CliRunner().invoke(cli, ["cv", "titles", "--hint", "lead"])
    assert result.exit_code == 0, result_text(result)
    text = result_text(result)
    assert "Head of Data" in text and "led a team of 5" in text and "Quant" in text


def test_cv_titles_warns_on_a_failed_call(env, monkeypatch):
    def boom(*a, **k):
        raise claude_cli.ClaudeError("not logged in")
    monkeypatch.setattr(claude_cli, "run", boom)
    result = CliRunner().invoke(cli, ["cv", "titles"])
    assert "not logged in" in result_text(result)
