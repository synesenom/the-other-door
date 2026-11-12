"""CV drafting (`_draft_cv_core`, the `draft_cv` tool and `init`'s CV step): turn an existing CV (PDF, DOCX, Markdown) and public pages into a
profile/cv.md draft with one `claude -p` call — the core behind /onboard's CV step.

Offline: `claude_cli.run` is replaced; files are extracted for real (a tiny PDF
made with pypdfium2, a tiny DOCX made with zipfile).
"""

import json
import types
import zipfile

import pytest

import door.mcp_server as server
from door.commands import cv as cv_cmd
from door.core import claude_cli, workspace
from paths import REPO_ROOT
from pdf_utils import make_pdf
from profile_utils import write_config

DRAFT = "# Jane Doe\n\n## Profile\n\nData scientist.\n\n## Education\n\n- TODO: dates\n"
ANSWER = {
    "cv_markdown": DRAFT,
    "provenance": [{"source": "https://github.com/jane", "contributed": "two named projects"}],
    "todos": ["education dates"],
}


def _pdf(path, text):
    make_pdf(path, [text])


def _docx(path, paragraphs):
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", xml)


@pytest.fixture
def env(tmp_path, monkeypatch):
    profile_dir = tmp_path / "profile"
    write_config(profile_dir, {"name": "Jane Doe", "role_targets": ["Data Scientist"]})
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile_dir)
    monkeypatch.setattr(workspace, "PROFILE_EXAMPLE_DIR", REPO_ROOT / "profile.example")
    _pdf(tmp_path / "old-cv.pdf", "Jane Doe, Lead Data Scientist at Acme since 2021")
    _docx(tmp_path / "old-cv.docx", ["Jane Doe", "Senior Data Scientist at Big Bank"])
    (tmp_path / "notes.md").write_text("PhD Copenhagen 2015")
    return types.SimpleNamespace(profile_dir=profile_dir, tmp=tmp_path, draft_path=profile_dir / "cv.draft.md")


def _answer(monkeypatch, answer=ANSWER, calls=None):
    def fake_run(args, *, input=None, timeout_s=None, profile_dir=None, **_):
        if calls is not None:
            calls.append({"args": args, "input": input, "profile_dir": profile_dir})
        return json.dumps({"result": json.dumps(answer)})
    monkeypatch.setattr(claude_cli, "run", fake_run)


def test_extract_text_reads_pdf_docx_and_text(env):
    assert "Lead Data Scientist at Acme" in cv_cmd._extract_text(env.tmp / "old-cv.pdf")
    assert cv_cmd._extract_text(env.tmp / "old-cv.docx") == "Jane Doe\nSenior Data Scientist at Big Bank"
    assert cv_cmd._extract_text(env.tmp / "notes.md") == "PhD Copenhagen 2015"
    with pytest.raises(ValueError, match="PDF, DOCX, Markdown or text"):
        cv_cmd._extract_text(env.tmp / "x.xlsx")
    with pytest.raises(FileNotFoundError):
        cv_cmd._extract_text(env.tmp / "missing.pdf")


def test_core_drafts_from_files_and_urls(env, monkeypatch):
    calls = []
    _answer(monkeypatch, calls=calls)
    sources = [str(env.tmp / "old-cv.pdf"), str(env.tmp / "old-cv.docx"), "https://github.com/jane", str(env.tmp / "notes.md")]
    result = cv_cmd._draft_cv_core(sources, profile_dir=env.profile_dir)

    assert result["draft_path"] == str(env.draft_path)
    assert env.draft_path.read_text() == DRAFT
    assert result["written"] is False and "cv_path" not in result
    assert result["provenance"] == ANSWER["provenance"] and result["todos"] == ["education dates"]
    assert [s["kind"] for s in result["sources"]] == ["file", "file", "url", "file"]
    assert result["sources"][0]["source"] == str(env.tmp / "old-cv.pdf") and result["sources"][0]["chars"] > 10
    assert result["sources"][2] == {"source": "https://github.com/jane", "kind": "url"}

    call = calls[0]
    args = call["args"]
    assert args[args.index("--system-prompt") + 1] == cv_cmd._RULES
    assert json.loads(args[args.index("--json-schema") + 1]) == cv_cmd._SCHEMA
    assert args[args.index("--allowedTools") + 1] == "WebFetch"
    assert args[args.index("--model") + 1] == cv_cmd._DEFAULT_MODEL
    for needle in ("Lead Data Scientist at Acme", "Senior Data Scientist at Big Bank", "PhD Copenhagen 2015", "https://github.com/jane"):
        assert needle in call["input"], needle
    assert "## Work Experience" in call["input"]  # the example CV's structure is the template
    assert "Jane Doe" in call["input"] and "Data Scientist" in call["input"]  # the profile's own fields
    assert call["profile_dir"] == env.profile_dir
    for word in ("backbone", "subpages", "api.github.com", "never invent", "TODO"):
        assert word in cv_cmd._RULES, word


def test_core_returns_the_draft_text(env, monkeypatch):
    _answer(monkeypatch)
    result = cv_cmd._draft_cv_core([str(env.tmp / "notes.md")], profile_dir=env.profile_dir)
    assert result["markdown"] == DRAFT == env.draft_path.read_text()
    assert result["todos"] == ["education dates"]


def test_core_works_before_the_profile_exists(env, monkeypatch):
    """/onboard drafts the CV before writing the config; the draft goes under profile/ anyway."""
    _answer(monkeypatch)
    (env.profile_dir / "config.json").unlink()
    result = cv_cmd._draft_cv_core([str(env.tmp / "notes.md")], profile_dir=env.profile_dir)
    assert env.draft_path.read_text() == DRAFT
    assert result["written"] is False


def test_core_write_replaces_the_cv_and_keeps_a_backup(env, monkeypatch):
    _answer(monkeypatch)
    (env.profile_dir / "cv.md").write_text("OLD")
    result = cv_cmd._draft_cv_core([str(env.tmp / "notes.md")], write=True, profile_dir=env.profile_dir)
    assert result["written"] is True
    assert result["cv_path"] == str(env.profile_dir / "cv.md")
    assert result["backup"] == str(env.profile_dir / "cv.md.bak")
    assert (env.profile_dir / "cv.md").read_text() == DRAFT
    assert (env.profile_dir / "cv.md.bak").read_text() == "OLD"
    assert not env.draft_path.exists()


def test_core_errors(env, monkeypatch):
    _answer(monkeypatch)
    with pytest.raises(ValueError, match="source"):
        cv_cmd._draft_cv_core([], profile_dir=env.profile_dir)
    with pytest.raises(FileNotFoundError, match="missing.pdf"):
        cv_cmd._draft_cv_core([str(env.tmp / "missing.pdf")], profile_dir=env.profile_dir)
    monkeypatch.setattr(claude_cli, "run", lambda *a, **k: json.dumps({"result": json.dumps({"cv_markdown": "  "})}))
    with pytest.raises(claude_cli.ClaudeError, match="cv_markdown"):
        cv_cmd._draft_cv_core([str(env.tmp / "notes.md")], profile_dir=env.profile_dir)
    assert not env.draft_path.exists()


def test_core_never_prints(env, monkeypatch, capsys):
    _answer(monkeypatch)
    cv_cmd._draft_cv_core([str(env.tmp / "notes.md")], write=True, profile_dir=env.profile_dir)
    assert capsys.readouterr().out == ""


def test_tool_delegates(env, monkeypatch):
    seen = {}

    def fake(sources, *, write=False, model=None, profile_dir=None):
        seen.update(sources=sources, write=write, model=model, profile_dir=profile_dir)
        return {"draft_path": "d"}

    monkeypatch.setattr(cv_cmd, "_draft_cv_core", fake)
    assert server.draft_cv(sources=["a.pdf"], write=True, model="opus") == {"draft_path": "d"}
    assert seen == {"sources": ["a.pdf"], "write": True, "model": "opus", "profile_dir": env.profile_dir}
    monkeypatch.setattr(cv_cmd, "_draft_cv_core", lambda *a, **k: (_ for _ in ()).throw(ValueError("no source")))
    assert server.draft_cv(sources=[]) == {"error": "no source"}


def _draft_answering(env, monkeypatch, markdown, todos=()):
    answer = {"cv_markdown": markdown, "todos": list(todos)}
    monkeypatch.setattr(claude_cli, "run", lambda *a, **k: json.dumps({"result": json.dumps(answer)}))
    return cv_cmd._draft_cv_core([str(env.tmp / "notes.md")], profile_dir=env.profile_dir)


@pytest.mark.parametrize("line", ["TODO", "- TODO", "TODO: add your skills", "**Tools:** TODO"])
def test_draft_never_asks_for_a_skills_section_the_sources_did_not_show(env, monkeypatch, line):
    result = _draft_answering(
        env, monkeypatch, f"# Ada\n\n## Skills\n\n{line}\n\n## Languages\n\n- English\n",
        ["Add your skills", "Add the year of your MSc"],
    )
    assert result["markdown"] == "# Ada\n\n## Languages\n\n- English\n"
    assert result["todos"] == ["Add the year of your MSc"]
    assert env.draft_path.read_text() == result["markdown"]


def test_draft_keeps_the_skills_it_found_beside_a_todo(env, monkeypatch):
    result = _draft_answering(env, monkeypatch, "## Kompetencer\n\nPython, SQL, TODO\n- TODO\n- Excel\n")
    assert result["markdown"] == "## Kompetencer\n\nPython, SQL\n- Excel\n"


def test_draft_keeps_a_todo_in_any_other_section(env, monkeypatch):
    result = _draft_answering(env, monkeypatch, "## Skills\n\nPython\n\n## Education\n\nMSc, TODO year\n", ["Add your skills list", "x"])
    assert "MSc, TODO year" in result["markdown"]
    assert result["todos"] == ["Add your skills list", "x"]  # nothing was taken out of Skills
