"""Keyword proposal (`_keywords_core`, the `keywords` tool and `init`'s keywords step): propose job-board search terms from the role targets, through one
`claude -p` call — the shell and tool form of "expand my search keywords".

Offline: `claude_cli.run` is replaced; nothing is executed.
"""

import json
import types

import pytest

import door.mcp_server as server
from door.commands import keywords as keywords_cmd
from door.core import claude_cli, workspace
from profile_utils import write_config


@pytest.fixture
def env(tmp_path, monkeypatch):
    profile_dir = tmp_path / "profile"
    write_config(profile_dir, {"role_targets": ["Data Scientist", "ML Engineer"]})
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(workspace, "PROFILE_EXAMPLE_DIR", profile_dir)
    return types.SimpleNamespace(profile_dir=profile_dir, config_path=profile_dir / "config.json")


def _answer(monkeypatch, terms, calls=None, topic=("data",)):
    def fake_run(args, *, input=None, timeout_s=None, profile_dir=None, **_):
        if calls is not None:
            calls.append({"args": args, "input": input, "timeout_s": timeout_s, "profile_dir": profile_dir})
        return json.dumps({"result": json.dumps({"keywords": terms, "topic_terms": list(topic)})})
    monkeypatch.setattr(claude_cli, "run", fake_run)


def test_core_asks_claude_with_the_rules_and_the_role_targets(env, monkeypatch):
    calls = []
    _answer(monkeypatch, ["data science", "ML"], calls)
    result = keywords_cmd._keywords_core(profile_dir=env.profile_dir)

    assert result == {"role_targets": ["Data Scientist", "ML Engineer"], "keywords": ["data science", "ML"],
                      "topic_terms": ["data"], "saved": False}
    call = calls[0]
    args = call["args"]
    assert args[args.index("--system-prompt") + 1] == keywords_cmd._RULES
    assert "8" in keywords_cmd._RULES and "15" in keywords_cmd._RULES and "noun form" in keywords_cmd._RULES
    assert "institute" in keywords_cmd._RULES and "department" in keywords_cmd._RULES
    assert json.loads(args[args.index("--json-schema") + 1]) == keywords_cmd._SCHEMA
    assert args[args.index("--model") + 1] == keywords_cmd._DEFAULT_MODEL
    assert "--tools" in args and args[args.index("--tools") + 1] == ""
    assert "Data Scientist" in call["input"] and "ML Engineer" in call["input"]
    assert call["profile_dir"] == env.profile_dir
    assert (env.profile_dir / "config.json").exists()
    assert "search_keywords" not in json.loads(env.config_path.read_text())


def test_keywords_come_in_every_ad_language_of_the_profile(env, monkeypatch):
    """Someone reading Danish ads too gets each term as Danish boards write it; English only is the default."""
    calls = []
    _answer(monkeypatch, ["data science"], calls)
    keywords_cmd._keywords_core(profile_dir=env.profile_dir)
    assert "Ad languages: English" in calls[-1]["input"] and "Danish" not in calls[-1]["input"]

    write_config(env.profile_dir, {"role_targets": ["Data Scientist"], "languages": ["English", "da"]})
    keywords_cmd._keywords_core(profile_dir=env.profile_dir)
    assert "Ad languages: English, Danish" in calls[-1]["input"]
    assert "each ad language" in keywords_cmd._RULES

    server.keywords(["Data Scientist"], languages=["English"])   # onboarding: before the profile has them
    assert "Ad languages: English" in calls[-1]["input"] and "Danish" not in calls[-1]["input"]


def test_core_cleans_the_terms(env, monkeypatch):
    _answer(monkeypatch, [" data science ", "ML", "ml", "", "Data Science", "head of data"])
    assert keywords_cmd._keywords_core(profile_dir=env.profile_dir)["keywords"] == ["data science", "ML", "head of data"]


def test_core_takes_explicit_role_targets_and_a_model(env, monkeypatch):
    calls = []
    _answer(monkeypatch, ["x"], calls)
    result = keywords_cmd._keywords_core(["Quant"], model="sonnet", profile_dir=env.profile_dir)
    assert result["role_targets"] == ["Quant"]
    assert "Quant" in calls[0]["input"] and "Data Scientist" not in calls[0]["input"]
    assert calls[0]["args"][calls[0]["args"].index("--model") + 1] == "sonnet"


def test_core_save_writes_search_keywords_in_place(env, monkeypatch):
    _answer(monkeypatch, ["data science", "ML"])
    result = keywords_cmd._keywords_core(save=True, profile_dir=env.profile_dir)
    assert result["saved"] is True
    assert result["config_path"] == str(env.config_path)
    data = json.loads(env.config_path.read_text())
    assert data["search_keywords"] == ["data science", "ML"]
    assert data["topic_terms"] == ["data"]
    assert data["role_targets"] == ["Data Scientist", "ML Engineer"]


def test_topic_terms_come_with_the_keywords_in_every_ad_language(env, monkeypatch):
    """The words that make a title relevant to this profile, neighbouring fields and compound prefixes
    included, so a shared role noun ("analyst") alone does not count (`title_fit.topic_terms`)."""
    _answer(monkeypatch, ["data scientist"], topic=[" data ", "BI", "bi", "adat*", ""])
    assert keywords_cmd._keywords_core(profile_dir=env.profile_dir)["topic_terms"] == ["data", "BI", "adat*"]
    assert "topic_terms" in keywords_cmd._SCHEMA["required"]
    rules = keywords_cmd._RULES
    assert "topic_terms" in rules and "role noun" in rules and "*" in rules


def test_the_rules_leave_compounds_and_plurals_to_the_matcher(env):
    """#428: the matcher finds a field word inside a Danish compound and in a plural, so the prompt asks
    for plain field words; `*x`, `x*` stay allowed, and an abbreviation that is also a word is kept in
    capitals or paired with its field word."""
    rules = keywords_cmd._RULES
    assert "matcher" in rules and "compound" in rules and "plural" in rules
    assert "*" in rules and "trailing *" not in rules
    assert "all-caps" in rules and "MEAL" in rules


def test_an_answer_without_topic_terms_still_gives_keywords(env, monkeypatch):
    monkeypatch.setattr(claude_cli, "run", lambda *a, **k: json.dumps({"result": json.dumps({"keywords": ["a"]})}))
    assert keywords_cmd._keywords_core(profile_dir=env.profile_dir)["topic_terms"] == []


def test_core_without_role_targets_is_an_error(env, monkeypatch):
    _answer(monkeypatch, ["x"])
    write_config(env.profile_dir, {"role_targets": ["x"]})
    with pytest.raises(ValueError, match="role targets"):
        keywords_cmd._keywords_core(role_targets=["  "], profile_dir=env.profile_dir)


def test_core_rejects_an_answer_that_is_not_a_list_of_terms(env, monkeypatch):
    monkeypatch.setattr(claude_cli, "run", lambda *a, **k: json.dumps({"result": json.dumps({"keywords": "nope"})}))
    with pytest.raises(claude_cli.ClaudeError, match="keywords"):
        keywords_cmd._keywords_core(profile_dir=env.profile_dir)


def test_core_never_prints(env, monkeypatch, capsys):
    _answer(monkeypatch, ["a"])
    keywords_cmd._keywords_core(save=True, profile_dir=env.profile_dir)
    assert capsys.readouterr().out == ""


def test_tool_delegates_and_returns_errors_as_dicts(env, monkeypatch):
    seen = {}

    def fake_core(role_targets=None, *, languages=None, save=False, model=None, profile_dir=None):
        seen.update(role_targets=role_targets, save=save, model=model, profile_dir=profile_dir)
        return {"keywords": ["a"]}

    monkeypatch.setattr(keywords_cmd, "_keywords_core", fake_core)
    assert server.keywords(role_targets=["Quant"], save=True, model="sonnet") == {"keywords": ["a"]}
    assert seen == {"role_targets": ["Quant"], "save": True, "model": "sonnet", "profile_dir": env.profile_dir}

    def boom(*a, **k):
        raise claude_cli.ClaudeError("claude exited 1: x")
    monkeypatch.setattr(keywords_cmd, "_keywords_core", boom)
    assert server.keywords() == {"error": "claude exited 1: x"}


def test_core_works_before_the_profile_exists(tmp_path, monkeypatch):
    calls = []
    _answer(monkeypatch, ["quant"], calls)
    profile_dir = tmp_path / "fresh"
    result = keywords_cmd._keywords_core(["Quant"], languages=["Danish"], profile_dir=profile_dir)
    assert result["keywords"] == ["quant"] and not profile_dir.exists()
    assert "English, Danish" in calls[0]["input"]
