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
    enrich_cmd._echo_proposals({"unreachable": [evil, evil + "x"], "proposals": [{"n": 1, "section": evil, "text": evil, "source": evil}]})
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


# --------------------------------------------------------------------------- #
# #589: every command prints outside text through `common.plain`
# --------------------------------------------------------------------------- #

BAD = "\x1b]0;pwned\x07"


def _no_control(text: str) -> None:
    assert "\x1b" not in text and "\x07" not in text, repr(text)


def _prepared(cli_env, monkeypatch, job_id="job-1"):
    import facts_utils

    out = cli_env.jobs_dir / "output" / job_id
    out.mkdir(parents=True)
    (out / "cv.html").write_text(f"<ul><li>Cut churn by 97%{BAD}</li></ul>")
    (out / "cover_letter.html").write_text("<p>Hi</p>")
    (cli_env.profile_dir / "cv.md").write_text("Cut churn by 38%.")
    facts_utils.checked(monkeypatch, out, cli_env.profile_dir, [facts_utils.finding(f"97%{BAD}", f"Cut churn by 97%{BAD}")])


def test_the_sent_status_warning_has_no_control_characters(cli_env, monkeypatch):
    _prepared(cli_env, monkeypatch)
    result = CliRunner().invoke(cli, ["jobs", "status", "job-1", "applied"])
    _no_control(result_text(result))


def _capture_prompts(monkeypatch):
    from door.commands import _prompts

    seen = []

    def ask(q):
        seen.append(q)
        first = (q.choices or [""])[0]
        return getattr(first, "value", first)

    monkeypatch.setattr(_prompts, "_ask", ask)
    return seen


def _shown(seen) -> str:
    return "\n".join(str(q.message) + "\n" + "\n".join(str(c) for c in q.choices or []) for q in seen)


def test_the_job_pickers_show_titles_as_text(cli_env, monkeypatch):
    from door.commands import _common as common

    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-evil", score=0.9, title=f"Lead{BAD}", company=f"Acme{BAD}")
    seen = _capture_prompts(monkeypatch)
    CliRunner().invoke(cli, ["jobs", "status", "job-evil"])
    common._pick_job()
    assert "Lead]0;pwned" in _shown(seen)
    _no_control(_shown(seen))


def test_the_ambiguous_job_list_shows_titles_as_text(cli_env, monkeypatch):
    from door.commands import _common as common

    for i in (1, 2):
        write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", f"job-{i}", score=0.9, title=f"Lead{BAD}", company="Acme")
    monkeypatch.setattr(common, "_stdout_is_tty", lambda: True)
    seen = _capture_prompts(monkeypatch)
    common._job_ref_cli("Lead", cli_env.jobs_dir)
    assert "Lead]0;pwned" in _shown(seen)
    _no_control(_shown(seen))


def test_a_progress_line_with_an_ad_title_has_no_control_characters():
    import io

    from door.commands import _progress
    from door.core import progress as progress_mod

    buf = io.StringIO()
    live = _progress.LiveLine(buf, animate=False)
    with progress_mod.activate(live):
        progress_mod.report(f"tailoring Lead{BAD} — Acme{BAD}", stage="prepare")
        progress_mod.report(f"top match Lead{BAD}", stage="prepare", site="x", outcome="ok")
    assert "\x1b]" not in buf.getvalue() and "\x07" not in buf.getvalue()
    assert "Lead]0;pwned" in buf.getvalue()


def test_a_failed_site_error_has_no_control_characters(capsys):
    rec = {"search": None, "collect": {"sites": [{"site": "beetween", "outcome": "failed", "count": 0,
                                                  "errors": [f"job 12{BAD} of 'acme' has no ad data"]}]}}
    find_cmd._echo_site_problems(rec)
    _no_control(capsys.readouterr().err)


def test_plain_steps_lines_have_no_control_characters():
    import io

    from door.core import progress as progress_mod
    from door.pipeline import display

    buf = io.StringIO()
    reporter = display.PlainSteps(buf)
    reporter.report(progress_mod.Progress("plan", stage="steps", detail="search"))
    reporter.report(progress_mod.Progress("search", stage="step", site="search", outcome="failed", detail=f"x{BAD}"))
    _no_control(buf.getvalue())
    assert "failed - x]0;pwned" in buf.getvalue()


def test_suggested_titles_have_no_control_characters(cli_env, monkeypatch):
    from door.commands import titles

    answer = {"titles": [{"title": f"Dev{BAD}", "reason": f"r{BAD}", "recommended": True}], "warning": f"w{BAD}"}
    monkeypatch.setattr(titles, "_titles_core", lambda *a, **k: answer)
    result = CliRunner().invoke(cli, ["cv", "titles", "x"])
    assert result.exit_code == 0, result_text(result)
    _no_control(result_text(result))
    assert "Dev]0;pwned" in result_text(result)


def test_drafted_and_saved_stories_have_no_control_characters(cli_env, monkeypatch):
    from door.commands import stories

    story = {"title": f"T{BAD}", "context": f"c{BAD}", "action": "a", "result": "r", "learning": "l",
             "conflicts": [f"x{BAD}"], "missing": [f"m{BAD}"]}
    monkeypatch.setattr(stories, "_draft_stories_core", lambda *a, **k: {"stories": [story]})
    monkeypatch.setattr(stories, "_save_story_core", lambda **k: {"outcome": "saved", "story": story, "count": 1})
    monkeypatch.setattr(stories, "_remove_story_core", lambda *a, **k: {"title": f"T{BAD}", "count": 0})
    for args in (["cv", "stories", "draft", "text"], ["cv", "stories", "add", "--title", "t"], ["cv", "stories", "remove", "t"]):
        result = CliRunner().invoke(cli, args)
        _no_control(result_text(result))
    assert "T]0;pwned" in result_text(CliRunner().invoke(cli, ["cv", "stories", "draft", "text"]))


def test_the_profile_review_has_no_control_characters(capsys):
    from door.commands import profile as profile_cmd

    answers = {"location": "Copenhagen", "role_targets": ["x"], "languages": ["en"], "discovery": [], "draft_path": "cv.draft.md",
               "provenance": [{"source": f"s{BAD}", "contributed": f"c{BAD}"}], "todos": [f"t{BAD}"]}
    profile_cmd._print_review(answers)
    _no_control(capsys.readouterr().out)
    state = {"path": "p", "exists": True, "is_example": False}
    profile_cmd._print_profile({"path": "p", "errors": [], "config": {}, "enrich_sources": [],
                                "templates": {"cv": state, "cover_letter": state}, "story_bank": state,
                                "cv": {**state, "headline": f"H{BAD}", "sections": [{"title": f"S{BAD}", "bullets": 1, "roles": []}]}})
    _no_control(capsys.readouterr().out)
