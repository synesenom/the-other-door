"""The test world's stand-in claude answers `skill_gaps` the way the real one does (#33): in an envelope."""

import json
import os
import re
import subprocess
import sys

import pytest

from door.commands import gaps
from door.core import claude_cli, cv_read, usage
from paths import REPO_ROOT

CLAUDE = REPO_ROOT / "app" / "test" / "world" / "claude.py"
REPORT = "## Plan\n\n### 1. Bayesian models (Priority: High)\n- r\n\n### 2. Grid basics\n- r\n\n## Skipped gaps\n- x\n"


def test_the_gaps_answer_is_an_envelope_the_ask_reader_and_the_plan_counter_accept(tmp_path):
    (tmp_path / "world.json").write_text(json.dumps({"answers": {"gaps": REPORT}}))
    argv = [sys.executable, str(CLAUDE), str(tmp_path), "-p", "--model", "haiku", "--system-prompt", claude_cli.prompt("skill-gaps"),
            *claude_cli.STREAM_ARGS, "--tools", "", "--no-session-persistence"]
    out = subprocess.run(argv, input="the CV and the targets", capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    text = claude_cli.envelope_result(out.stdout)
    assert isinstance(text, str) and text.strip() == REPORT.strip()
    assert len(gaps._PLAN_ITEM_RE.findall(text)) == 2


# kind: (system prompt, stdin, the price COST_USD gives it)
_PRICED = {
    "score": ("You are a job-matching scorer.", "### job_id: a\nTitle: Analyst\nCompany: Acme\n", 0.02),
    "translate": ("You translate job titles into English.", json.dumps([{"id": "a", "title": "Analytiker"}]), 0.01),
    "read_ad": ("You read a job ad.", "Analyst at Acme", 0.01),
    "market": ("You group skill names.", json.dumps({"names": ["Python"]}), 0.01),
    "revise": ("", "You are revising the body of an HTML letter.\nCurrent body:\nOne.\n\nTwo.\n\nThree.", 0.05),
    "facts": ("You check a tailored CV and cover letter against the candidate's own sources.", "SOURCE CV:\n<<<\nx\n>>>\n", 0.01),
    "gaps": (claude_cli.prompt("skill-gaps"), "the CV and the targets", 0.03),
    "cv_read": (claude_cli.prompt("cv-reader"), "CV:\n<<<\n# A\n\n## Skills\n\nPython\n>>>\n", 0.01),
}


@pytest.mark.parametrize("kind", sorted(_PRICED))
def test_every_answer_carries_its_price_the_usage_log_weighs(tmp_path, kind):
    """#67: each answer is priced (`total_cost_usd`), so `status_summary`'s `cost` reads in the world."""
    system, stdin, price = _PRICED[kind]
    (tmp_path / "world.json").write_text(json.dumps({"answers": {"gaps": REPORT}}))
    argv = [sys.executable, str(CLAUDE), str(tmp_path), "-p", "--model", "haiku", "--system-prompt", system,
            *claude_cli.STREAM_ARGS, "--tools", "", "--no-session-persistence"]
    out = subprocess.run(argv, input=stdin, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    envelope, _ = claude_cli.read_stream(out.stdout)
    assert usage.weight(envelope) == price


def test_revise_and_facts_answer_in_their_schemas(tmp_path):
    (tmp_path / "world.json").write_text(json.dumps({}))
    for system, stdin, want in (
        ("", "You are revising the body of an HTML letter.\nCurrent body:\nOne.\n\nTwo.\n\nThree.", {"body": "One.\n\nTwo."}),
        ("You check a tailored CV and cover letter against the candidate's own sources.", "SOURCE CV:\n", {"findings": []}),
    ):
        argv = [sys.executable, str(CLAUDE), str(tmp_path), "-p", "--model", "haiku", "--system-prompt", system,
                *claude_cli.STREAM_ARGS, "--tools", "", "--no-session-persistence"]
        out = subprocess.run(argv, input=stdin, capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        assert claude_cli.json_result(out.stdout) == want


def test_the_tailor_answers_with_a_priced_envelope(tmp_path):
    """#67: the tailor's run ends in an envelope too, so a prepare in the world is weighed."""
    world = tmp_path / "world"
    world.mkdir()
    (world / "world.json").write_text(json.dumps({"tailor": {"cv": "cv", "cover_letter": "letter"}, "printer": False}))
    out_dir = tmp_path / "jobs" / "output" / "acme.1"
    out_dir.mkdir(parents=True)
    (tmp_path / "jobs" / ".tailor" / "acme.1").mkdir(parents=True)
    (tmp_path / "jobs" / ".tailor" / "acme.1" / "posting.json").write_text(json.dumps({"id": "acme.1"}))
    stub = tmp_path / "stub" / "door" / "commands"  # door's compile, stood in: nothing prints here
    stub.mkdir(parents=True)
    (stub.parent / "__init__.py").write_text("")
    (stub / "__init__.py").write_text("")
    (stub / "compile.py").write_text("def _compile_core(*args, **kwargs):\n    return {}\n")
    env = {**os.environ, "PYTHONPATH": str(tmp_path / "stub"), "DOOR_WORLD_PYTHON": sys.executable}
    argv = [sys.executable, str(CLAUDE), str(world), "-p", "--agent", "tailor", *claude_cli.STREAM_ARGS]
    out = subprocess.run(argv, cwd=out_dir, env=env, input="", capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    envelope, _ = claude_cli.read_stream(out.stdout)
    assert usage.weight(envelope) == 0.40
    assert (out_dir / "cover_letter.html").read_text() == "letter"


def test_the_stylist_answers_with_the_template_blocks_in_a_priced_envelope(tmp_path):
    """#205: a CV style build in the world gets the shipped template over the builder's fonts, and is weighed."""
    world = tmp_path / "world"
    world.mkdir()
    (world / "world.json").write_text(json.dumps({}))
    call = tmp_path / "call"
    call.mkdir()
    (call / "fonts.css").write_text('@font-face { font-family: "Lato"; }\n')
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src"), "DOOR_WORLD_PYTHON": sys.executable}
    argv = [sys.executable, str(CLAUDE), str(world), "-p", "--agent", "stylist", *claude_cli.STREAM_ARGS]
    out = subprocess.run(argv, cwd=call, env=env, input="", capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    envelope, _ = claude_cli.read_stream(out.stdout)
    assert usage.weight(envelope) == 0.30
    answer = claude_cli.envelope_result(out.stdout)
    assert "```template" in answer and "```cv" in answer and '"Lato"' in answer


CV = """# Léa Moreau

**Téléphone :** +33 6 00 00 00 00 | **Email :** lea@example.com | **Location :** Lyon

## Expérience professionnelle

### Contrôleuse de gestion | Acme — 2018 - présent

- Budget.

## Compétences

SAP CO (S/4HANA), Power BI, Excel avancé (VBA, Power Query)

## Langues

- **Français** — langue maternelle
"""


def test_the_cv_read_answer_is_a_reading_cv_read_accepts_in_any_language(tmp_path):
    """#430: the world's stand-in reads the CV on stdin, its values are stretches of it, and the world says the rest."""
    world = {"reading": {"languages": [{"language": "Français", "code": "fr", "level": "native"}, {"language": "Anglais", "code": "en", "level": "fluent"}],
                         "kinds": {"Expérience professionnelle": "experience", "Compétences": "skills", "Langues": "languages"}}}
    (tmp_path / "world.json").write_text(json.dumps(world))
    argv = [sys.executable, str(CLAUDE), str(tmp_path), "-p", "--model", "haiku", "--system-prompt", claude_cli.prompt("cv-reader"),
            *claude_cli.STREAM_ARGS, "--tools", "", "--no-session-persistence"]
    out = subprocess.run(argv, input=f"CV:\n<<<\n{CV.strip()}\n>>>\n", capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    reading = claude_cli.envelope_result(out.stdout)
    reading = json.loads(reading) if isinstance(reading, str) else reading
    cv_read.check(reading, CV.strip())
    assert reading["name"] == "Léa Moreau" and reading["city"] == "Lyon" and reading["email"] == "lea@example.com"
    assert [s["kind"] for s in reading["sections"]] == ["experience", "skills", "languages"]
    assert reading["skills"] == ["SAP CO (S/4HANA)", "Power BI", "Excel avancé (VBA, Power Query)"]
    assert reading["languages"] == [{"language": "Français", "code": "fr", "level": "native"}]  # Anglais is not in this CV
    assert reading["entries"][0]["start_year"] == 2018 and reading["entries"][0]["end_year"] is None
