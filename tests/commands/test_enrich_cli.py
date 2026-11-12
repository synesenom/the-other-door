"""`enrich`: propose additions to profile/cv.md from public URLs, then apply the
ones the user picks — the core behind `/expand`, usable from a shell.

Offline: `claude_cli.run` is replaced; nothing is fetched.
"""

import json
import types

import pytest
from click.testing import CliRunner

import door.mcp_server as server
from door.cli import cli
from door.commands import enrich as enrich_cmd
from door.core import claude_cli, workspace
from cli_utils import result_text
from profile_utils import write_config

CV = """# Jane Doe

## Profile

Data scientist.

## Skills

Python, SQL.

## Projects

- Built a churn model.
"""

PROPOSALS = [
    {"section": "Skills", "text": "Rust (used in github.com/jane/kv)", "source": "https://github.com/jane"},
    {"section": "Projects", "text": "Built a distributed key-value store in Go (github.com/jane/kv)", "source": "https://github.com/jane"},
    {"section": "Talks", "text": "Spoke at PyData Copenhagen 2025", "source": "https://jane.example"},
]


@pytest.fixture
def env(tmp_path, monkeypatch):
    profile_dir = tmp_path / "profile"
    write_config(profile_dir, {"role_targets": ["Data Scientist"], "enrich_sources": ["https://github.com/jane"]})
    cv_path = profile_dir / "cv.md"
    cv_path.write_text(CV)
    config = json.loads((profile_dir / "config.json").read_text())
    config["cv_content"] = str(cv_path)
    (profile_dir / "config.json").write_text(json.dumps(config))
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    return types.SimpleNamespace(profile_dir=profile_dir, cv_path=cv_path, proposals_path=profile_dir / ".enrich_proposals.json")


def _answer(monkeypatch, proposals=PROPOSALS, unreachable=(), calls=None):
    def fake_run(args, *, input=None, timeout_s=None, profile_dir=None, **_):
        if calls is not None:
            calls.append({"args": args, "input": input, "profile_dir": profile_dir})
        return json.dumps({"result": json.dumps({"proposals": proposals, "unreachable": list(unreachable)})})
    monkeypatch.setattr(claude_cli, "run", fake_run)


# --------------------------------------------------------------------------- #
# propose
# --------------------------------------------------------------------------- #

def test_propose_asks_claude_with_webfetch_the_cv_and_the_urls(env, monkeypatch):
    calls = []
    _answer(monkeypatch, calls=calls, unreachable=["https://down.example"])
    result = enrich_cmd._enrich_core(["https://github.com/jane", "https://down.example"], profile_dir=env.profile_dir)

    assert result["outcome"] == "proposed"
    assert result["urls"] == ["https://github.com/jane", "https://down.example"]
    assert result["unreachable"] == ["https://down.example"]
    assert [p["n"] for p in result["proposals"]] == [1, 2, 3]
    assert result["proposals"][0] == {"n": 1, **PROPOSALS[0]}
    assert result["proposals_path"] == str(env.proposals_path)
    assert json.loads(env.proposals_path.read_text())["proposals"] == result["proposals"]
    assert env.cv_path.read_text() == CV  # nothing written yet

    args = calls[0]["args"]
    assert args[args.index("--allowedTools") + 1] == "WebFetch"
    assert args[args.index("--system-prompt") + 1] == enrich_cmd._RULES
    assert "never fabricate" in enrich_cmd._RULES.lower() or "never invent" in enrich_cmd._RULES.lower()
    assert json.loads(args[args.index("--json-schema") + 1]) == enrich_cmd._SCHEMA
    assert args[args.index("--model") + 1] == enrich_cmd._DEFAULT_MODEL
    assert "Built a churn model" in calls[0]["input"]
    assert "Data Scientist" in calls[0]["input"]
    assert "https://github.com/jane\nhttps://down.example" in calls[0]["input"]
    assert calls[0]["profile_dir"] == env.profile_dir


def test_propose_defaults_to_enrich_sources(env, monkeypatch):
    calls = []
    _answer(monkeypatch, calls=calls)
    assert enrich_cmd._enrich_core(profile_dir=env.profile_dir)["urls"] == ["https://github.com/jane"]


def test_propose_without_urls_is_an_error(env, monkeypatch):
    _answer(monkeypatch)
    write_config(env.profile_dir, {"role_targets": ["x"], "cv_content": str(env.cv_path)})
    with pytest.raises(ValueError, match="enrich_sources"):
        enrich_cmd._enrich_core(profile_dir=env.profile_dir)


def test_propose_without_a_cv_is_an_error(env, monkeypatch):
    _answer(monkeypatch)
    env.cv_path.unlink()
    with pytest.raises(FileNotFoundError, match="cv.md"):
        enrich_cmd._enrich_core(profile_dir=env.profile_dir)


def test_propose_with_nothing_new(env, monkeypatch):
    _answer(monkeypatch, proposals=[])
    result = enrich_cmd._enrich_core(profile_dir=env.profile_dir)
    assert result["outcome"] == "nothing_new" and result["proposals"] == []
    assert not env.proposals_path.exists()


def test_propose_drops_malformed_and_duplicate_proposals(env, monkeypatch):
    _answer(monkeypatch, proposals=[
        {"section": "Skills", "text": "Rust", "source": "u"},
        {"section": "Skills", "text": " Rust ", "source": "u"},
        {"section": "Skills", "text": "", "source": "u"},
        {"text": "no section", "source": "u"},
        {"section": "## Projects", "text": "Built a churn model.", "source": "u"},  # already in the CV
        {"section": "## Projects", "text": "New thing", "source": "u"},
    ])
    result = enrich_cmd._enrich_core(profile_dir=env.profile_dir)
    assert [(p["section"], p["text"]) for p in result["proposals"]] == [("Skills", "Rust"), ("Projects", "New thing")]


def test_propose_drops_what_the_cv_already_says_in_other_punctuation_or_markup(env, monkeypatch):
    _answer(monkeypatch, proposals=[
        {"section": "Projects", "text": "Built a churn-model", "source": "u"},  # "- Built a churn model."
        {"section": "Skills", "text": "**Python**, SQL", "source": "u"},  # "Python, SQL."
        {"section": "Projects", "text": "Built a churn model in Python and served it to 3 teams", "source": "u"},  # says more: kept
    ])
    result = enrich_cmd._enrich_core(profile_dir=env.profile_dir)
    assert [p["text"] for p in result["proposals"]] == ["Built a churn model in Python and served it to 3 teams"]


def test_reading_the_pages_again_after_adding_proposes_none_of_it_again(env, monkeypatch):
    _proposed(env, monkeypatch)
    enrich_cmd._enrich_core(all=True, profile_dir=env.profile_dir)
    # the second read words the same things a little differently
    _answer(monkeypatch, proposals=[
        {"section": "Skills", "text": "Rust, used in github.com/jane/kv", "source": "https://github.com/jane"},
        {"section": "Projects", "text": "Built a distributed key value store in Go (github.com/jane/kv).", "source": "https://github.com/jane"},
        {"section": "Talks", "text": "Spoke at PyData Copenhagen, 2025", "source": "https://jane.example"},
    ])
    before = env.cv_path.read_text()
    result = enrich_cmd._enrich_core(profile_dir=env.profile_dir)
    assert result["outcome"] == "nothing_new" and result["proposals"] == []
    assert env.cv_path.read_text() == before


def test_propose_rejects_an_answer_without_proposals(env, monkeypatch):
    monkeypatch.setattr(claude_cli, "run", lambda *a, **k: json.dumps({"result": "{}"}))
    with pytest.raises(claude_cli.ClaudeError, match="proposals"):
        enrich_cmd._enrich_core(profile_dir=env.profile_dir)


# --------------------------------------------------------------------------- #
# apply
# --------------------------------------------------------------------------- #

def _proposed(env, monkeypatch):
    _answer(monkeypatch)
    return enrich_cmd._enrich_core(profile_dir=env.profile_dir)


def test_apply_inserts_under_the_section_and_appends_new_sections(env, monkeypatch):
    _proposed(env, monkeypatch)
    result = enrich_cmd._enrich_core(apply=[1, 3], profile_dir=env.profile_dir)

    assert result["outcome"] == "applied"
    assert [a["n"] for a in result["added"]] == [1, 3]
    assert result["cv_path"] == str(env.cv_path)
    assert result["backup"] == str(env.cv_path) + ".bak"
    text = env.cv_path.read_text()
    assert "## Skills\n\nPython, SQL.\n\n- Rust (used in github.com/jane/kv)\n\n## Projects" in text
    assert text.endswith("## Projects\n\n- Built a churn model.\n\n## Talks\n\n- Spoke at PyData Copenhagen 2025\n")
    assert (env.cv_path.with_name("cv.md.bak")).read_text() == CV
    assert not env.proposals_path.exists()


def test_apply_after_the_last_bullet_of_a_section(env, monkeypatch):
    _proposed(env, monkeypatch)
    enrich_cmd._enrich_core(apply=[2], profile_dir=env.profile_dir)
    assert "## Projects\n\n- Built a churn model.\n- Built a distributed key-value store in Go (github.com/jane/kv)\n" in env.cv_path.read_text()


def test_apply_all(env, monkeypatch):
    _proposed(env, monkeypatch)
    result = enrich_cmd._enrich_core(all=True, profile_dir=env.profile_dir)
    assert [a["n"] for a in result["added"]] == [1, 2, 3]


def test_apply_rejects_bad_numbers_and_leaves_the_proposals(env, monkeypatch):
    _proposed(env, monkeypatch)
    with pytest.raises(ValueError, match="1-3"):
        enrich_cmd._enrich_core(apply=[4], profile_dir=env.profile_dir)
    assert env.proposals_path.exists()
    assert env.cv_path.read_text() == CV


def test_apply_without_proposals_is_an_error(env, monkeypatch):
    with pytest.raises(FileNotFoundError, match="no proposals"):
        enrich_cmd._enrich_core(apply=[1], profile_dir=env.profile_dir)


def test_apply_and_urls_together_is_an_error(env, monkeypatch):
    with pytest.raises(ValueError, match="not both"):
        enrich_cmd._enrich_core(["https://x"], apply=[1], profile_dir=env.profile_dir)


def test_apply_refuses_stale_proposals_after_the_cv_changed(env, monkeypatch):
    _proposed(env, monkeypatch)
    env.cv_path.write_text(CV + "\n## Extra\n\n- changed\n")
    with pytest.raises(ValueError, match="changed"):
        enrich_cmd._enrich_core(apply=[1], profile_dir=env.profile_dir)


def test_core_never_prints(env, monkeypatch, capsys):
    _proposed(env, monkeypatch)
    enrich_cmd._enrich_core(all=True, profile_dir=env.profile_dir)
    assert capsys.readouterr().out == ""


# --------------------------------------------------------------------------- #
# CLI and tool
# --------------------------------------------------------------------------- #

def test_cli_proposes_then_asks_which_to_add(env, monkeypatch, prompts):
    _answer(monkeypatch, unreachable=["https://down.example"])
    monkeypatch.setattr(enrich_cmd.common, "_stdout_is_tty", lambda: True)
    prompts.answers["apply"] = "1 3"
    result = CliRunner().invoke(cli, ["cv", "enrich", "https://github.com/jane", "https://down.example"])
    assert result.exit_code == 0, result_text(result)
    out = result_text(result)
    assert "Could not fetch https://down.example" in out
    assert "1. [Skills] Rust (used in github.com/jane/kv)" in out
    assert "Source: https://github.com/jane" in out
    assert "Added 2 item(s) to" in out
    assert "- Rust (used in github.com/jane/kv)" in env.cv_path.read_text()
    assert "Spoke at PyData" in env.cv_path.read_text()
    assert "key-value" not in env.cv_path.read_text()


def test_cli_none_makes_no_changes(env, monkeypatch, prompts):
    _answer(monkeypatch)
    monkeypatch.setattr(enrich_cmd.common, "_stdout_is_tty", lambda: True)
    prompts.answers["apply"] = "none"
    result = CliRunner().invoke(cli, ["cv", "enrich"])
    assert result.exit_code == 0, result_text(result)
    assert "No changes made" in result_text(result)
    assert env.cv_path.read_text() == CV
    assert env.proposals_path.exists()  # `enrich --apply 2` can still pick them up


def test_cli_not_a_tty_prints_and_hints(env, monkeypatch, prompts):
    _answer(monkeypatch)
    monkeypatch.setattr(enrich_cmd.common, "_stdout_is_tty", lambda: False)
    result = CliRunner().invoke(cli, ["cv", "enrich"])
    assert result.exit_code == 0, result_text(result)
    assert prompts.order == []
    assert "enrich --apply 1,3" in result_text(result) and "enrich --all" in result_text(result)


def test_cli_apply_and_all_use_the_saved_proposals(env, monkeypatch, prompts):
    _proposed(env, monkeypatch)
    result = CliRunner().invoke(cli, ["cv", "enrich", "--apply", "2"])
    assert result.exit_code == 0, result_text(result)
    assert prompts.order == []
    assert "Added 1 item(s)" in result_text(result)

    _proposed(env, monkeypatch)  # proposal 2 is now in the CV, so only 1 and 3 come back
    result = CliRunner().invoke(cli, ["cv", "enrich", "--all"])
    assert result.exit_code == 0, result_text(result)
    assert "Added 2 item(s)" in result_text(result)


def test_cli_nothing_new(env, monkeypatch, prompts):
    _answer(monkeypatch, proposals=[])
    result = CliRunner().invoke(cli, ["cv", "enrich"])
    assert result.exit_code == 0, result_text(result)
    assert "Nothing new found" in result_text(result)


def test_cli_errors_are_one_line(env, monkeypatch, prompts):
    def boom(*a, **k):
        raise claude_cli.ClaudeError("claude exited 1: x")
    monkeypatch.setattr(claude_cli, "run", boom)
    result = CliRunner().invoke(cli, ["cv", "enrich"])
    assert result.exit_code == 1 and "Error: claude exited 1: x" in result_text(result)
    result = CliRunner().invoke(cli, ["cv", "enrich", "--apply", "1"])
    assert result.exit_code == 1 and "no proposals" in result_text(result)
    result = CliRunner().invoke(cli, ["cv", "enrich", "--apply", "x"])
    assert result.exit_code != 0


def test_tool_delegates(env, monkeypatch):
    seen = {}

    def fake(urls=None, *, apply=None, all=False, model=None, profile_dir=None):
        seen.update(urls=urls, apply=apply, all=all, model=model, profile_dir=profile_dir)
        return {"outcome": "x"}

    monkeypatch.setattr(enrich_cmd, "_enrich_core", fake)
    assert server.enrich(urls=["u"], model="sonnet") == {"outcome": "x"}
    assert seen == {"urls": ["u"], "apply": None, "all": False, "model": "sonnet", "profile_dir": env.profile_dir}
    server.enrich(apply=[1, 2])
    assert seen["apply"] == [1, 2]
    monkeypatch.setattr(enrich_cmd, "_enrich_core", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("no proposals")))
    assert server.enrich(all=True) == {"error": "no proposals"}
