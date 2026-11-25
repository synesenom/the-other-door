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


def test_model_and_employer_text_printed_by_other_commands_has_no_control_characters(capsys):
    from door.commands import companies as companies_cmd
    from door.commands import enrich as enrich_cmd

    evil = "Acme \x1b]0;pwn\x07 Ltd"
    enrich_cmd._echo_proposals({"unreachable": [evil, evil + "x"], "not_given": [evil + "x"], "proposals": [{"n": 1, "section": evil, "text": evil, "source": evil}]})
    enrich_cmd._echo_applied({"added": [{"section": evil, "text": evil}], "cv_path": "cv.md", "backup": None})
    line = companies_cmd._company_line({"status": "unresolved", "name": evil, "feed": None, "found_via": evil, "aliases": [evil], "reason": "x"})
    assert "Acme ]0;pwn Ltd" in line
    out = capsys.readouterr().out
    assert "Acme ]0;pwn Ltd" in out and "\x1b]" not in out + line and "\x07" not in out + line


def test_the_first_look_ad_titles_have_no_control_characters(capsys, monkeypatch):
    from door.commands import cv as cv_cmd
    from door.commands import preview as preview_cmd
    from door.commands import profile as profile_cmd

    look = {"matches": [{"title": "Lead\x1b]0;pwn\x07", "company": "Acme\x1b", "score_reason": "r\x07"}]}
    monkeypatch.setattr(preview_cmd, "_preview_core", lambda *a, **k: look)
    monkeypatch.setattr(cv_cmd, "_onboarding_cv_text", lambda *a, **k: "")
    profile_cmd._first_look({})
    out = capsys.readouterr().out
    assert "Lead" in out and "\x1b" not in out and "\x07" not in out
