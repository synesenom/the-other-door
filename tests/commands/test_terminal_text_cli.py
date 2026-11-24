"""Text from ads and from the model reaches the terminal as text: never markup, never a control character."""

import json

import click
from click.testing import CliRunner

from cli_utils import result_text, stub_blocks, stub_steps, write_list_posting
from door.cli import cli
from door.commands import find as find_cmd
from door.core import claude_cli, workspace

MARKUP = "[link=https://evil.example]x[/link]"
HOSTILE = f"{MARKUP}\x1b]0;pwn\x07"


def _clean(text: str) -> str:
    assert "\x1b]" not in text and "\x07" not in text
    return text


def test_a_title_with_markup_prints_as_text(cli_env):
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-evil", score=0.9, title=HOSTILE, company=HOSTILE,
                       source=MARKUP, matching_skills=[MARKUP], missing_skills=[HOSTILE])
    for args in (["jobs"], ["jobs", "show", "job-evil"], ["jobs", "query"]):
        result = CliRunner().invoke(cli, args)
        assert result.exit_code == 0, result_text(result)
        text = _clean(result_text(result))
        assert MARKUP in text, (args, text)


def test_an_answer_with_markup_prints_as_text(cli_env, monkeypatch):
    write_list_posting(cli_env.jobs_dir, "2026-09-03", "jobindex", "jobindex.1", title=HOSTILE, company="Acme")
    answer = {"answer": HOSTILE, "go_to": {"screen": "posting", "job_ids": ["jobindex.1"]}, "sources": []}
    monkeypatch.setattr(claude_cli, "run", lambda *a, **k: json.dumps({"type": "result", "is_error": False, "result": json.dumps(answer)}))
    monkeypatch.setattr(workspace, "ensure_mcp_config", lambda: workspace.REPO_ROOT / ".mcp.json")
    result = CliRunner().invoke(cli, ["ask", "q"])
    assert result.exit_code == 0, result_text(result)
    text = _clean(result_text(result))
    assert text.count(MARKUP) == 2, text


def test_the_top_matches_of_a_run_print_as_text(cli_env, monkeypatch):
    top = {"id": "job-a", "score": 0.9, "title": HOSTILE, "company": HOSTILE, "location": MARKUP}
    match = {**stub_blocks(cli_env.jobs_dir)["match"], "top": [top], "new_above_threshold": ["job-a"]}
    stub_steps(monkeypatch, cli_env.jobs_dir, match=match)
    monkeypatch.setattr(find_cmd, "_stdout_is_tty", lambda: True)
    text = _clean(click.unstyle(result_text(CliRunner().invoke(cli, ["find"]))))
    assert MARKUP in text
