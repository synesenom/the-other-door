"""CV drafting (`_draft_cv_core`, the `draft_cv` tool and `init`'s CV step): turn an existing CV (PDF, DOCX, Markdown) and public pages into a
profile/cv.md draft with one `claude -p` call — the core behind /onboard's CV step.

Offline: `claude_cli.run` is replaced; files are extracted for real (a tiny PDF
made with pypdfium2, a tiny DOCX made with zipfile).
"""

import json
import types
import zipfile

import pytest

from door.commands import cv as cv_cmd
from door.commands import _common as common
from door.core import claude_cli, workspace
from door.render import pdf_draft
from door.scrapers import http_client
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
    monkeypatch.setattr(common, "_read_page", lambda url: (None, []))
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


def test_a_docx_whose_document_expands_past_the_cap_is_refused(tmp_path):
    path = tmp_path / "bomb.docx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", b"<w:document " + _NS.encode() + b">" + b" " * (21 * 1024 * 1024) + b"</w:document>")
    with pytest.raises(ValueError, match="too large"):
        cv_cmd._extract_text(path)


def test_a_docx_whose_header_understates_its_size_is_refused_without_unpacking_it(tmp_path, monkeypatch):
    import struct

    path = tmp_path / "lying.docx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", b"<w:document " + _NS.encode() + b">" + b" " * 200_000 + b"</w:document>")
    raw = bytearray(path.read_bytes())
    raw[22:26] = struct.pack("<I", 10)  # the local header's size
    central = raw.find(b"PK\x01\x02")
    raw[central + 24:central + 28] = struct.pack("<I", 10)  # the central directory's size
    path.write_bytes(bytes(raw))
    monkeypatch.setattr(cv_cmd, "_DOCX_PART_MAX", 1000)
    with pytest.raises(ValueError, match="DOCX"):
        cv_cmd._extract_text(path)


def test_a_broken_docx_is_refused_with_a_message(tmp_path):
    path = tmp_path / "broken.docx"
    path.write_bytes(b"PK\x03\x04 not really a zip")
    with pytest.raises(ValueError, match="not a readable DOCX"):
        cv_cmd._extract_text(path)


def test_a_pdf_past_the_page_cap_is_refused(tmp_path):
    path = tmp_path / "long.pdf"
    make_pdf(path, ["Jane Doe"] * 31)
    with pytest.raises(ValueError, match="pages"):
        cv_cmd._extract_text(path)


def test_a_pdf_past_the_text_cap_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "dense.pdf"
    make_pdf(path, ["\n".join(["x" * 90] * 55)] * 3)
    monkeypatch.setattr(pdf_draft, "MAX_TEXT", 10_000)
    with pytest.raises(ValueError, match="text"):
        cv_cmd._extract_text(path)


_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _run(text, font=None, style=None):
    props = (f'<w:rStyle w:val="{style}"/>' if style else "") + (f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}"/>' if font else "")
    return f"<w:r>{f'<w:rPr>{props}</w:rPr>' if props else ''}<w:t xml:space=\"preserve\">{text}</w:t></w:r>"


def _styled_docx(path, paragraphs, styles):
    """A DOCX of `paragraphs` ((paragraph style or None, runs)) and `styles` ((id, type, based on, font[, default]))."""
    body = "".join(
        f"<w:p>{f'<w:pPr><w:pStyle w:val=\"{pstyle}\"/></w:pPr>' if pstyle else ''}{''.join(runs)}</w:p>"
        for pstyle, runs in paragraphs
    )
    defs = "".join(
        f'<w:style w:type="{kind}" w:styleId="{sid}"{' w:default="1"' if default else ""}>'
        + (f'<w:basedOn w:val="{base}"/>' if base else "")
        + (f'<w:rPr><w:rFonts w:ascii="{font}" w:hAnsi="{font}"/></w:rPr>' if font else "") + "</w:style>"
        for sid, kind, base, font, *default in styles
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", f'<?xml version="1.0" encoding="UTF-8"?><w:document {_NS}><w:body>{body}</w:body></w:document>')
        zf.writestr("word/styles.xml", f'<?xml version="1.0" encoding="UTF-8"?><w:styles {_NS}>{defs}</w:styles>')


# a phone or envelope icon set in Wingdings, Webdings or Symbol reads back as a stray "(" or "*": the model would
# copy it into cv.md (#297, the DOCX twin of #266)
def test_extract_text_of_a_docx_leaves_out_runs_in_a_symbol_font(tmp_path):
    path = tmp_path / "cv.docx"
    _styled_docx(path, [
        (None, [_run("Jane Doe", font="Calibri")]),
        (None, [_run("(", font="Wingdings"), _run(" +45 1234 5678"), _run("*", font="Symbol"), _run(" jane@example.com")]),
        (None, [_run("\uf0a7", style="Icon"), _run(" Copenhagen", style="Body")]),
        ("IconLine", [_run("\u00b7")]),
        ("Heading1", [_run("Experience")]),
    ], [
        ("Body", "character", None, "Calibri"),
        ("IconBase", "character", None, "Webdings"),
        ("Icon", "character", "IconBase", None),
        ("SymbolPara", "paragraph", None, "Wingdings 2"),
        ("IconLine", "paragraph", "SymbolPara", None),
        ("Heading1", "paragraph", None, "Cambria"),
    ])
    lines = [line.strip() for line in cv_cmd._extract_text(path).splitlines()]
    assert lines == ["Jane Doe", "+45 1234 5678 jane@example.com", "Copenhagen", "Experience"]


def test_extract_text_of_a_docx_keeps_a_run_whose_own_font_overrides_a_symbol_style(tmp_path):
    path = tmp_path / "cv.docx"
    _styled_docx(path, [("Icons", [_run("Jane Doe", font="Arial")])], [("Icons", "paragraph", None, "Wingdings")])
    assert cv_cmd._extract_text(path) == "Jane Doe"


ICON_FONTS = ["FontAwesome", "Font Awesome 6 Free Solid", "Symbol", "Wingdings 2", "Webdings", "Zapf Dingbats", "MT Extra", "Marlett"]


@pytest.mark.parametrize("font", ICON_FONTS)
def test_the_docx_reader_leaves_out_the_icon_fonts(tmp_path, font):
    path = tmp_path / "cv.docx"
    _styled_docx(path, [(None, [_run("Abc", font=font), _run("+45 1234 5678", font="Calibri")])], [])
    assert cv_cmd._extract_text(path) == "+45 1234 5678"


def test_extract_text_of_a_docx_leaves_out_a_run_of_only_icon_glyphs_whatever_its_font(tmp_path):
    # a font from the theme or the document defaults is not read: the glyphs themselves tell (#297)
    path = tmp_path / "cv.docx"
    _styled_docx(path, [(None, [_run("\uf095"), _run(" +45 1234 5678 "), _run("\u2706", font="Calibri"), _run("Copenhagen")])], [])
    assert cv_cmd._extract_text(path) == "+45 1234 5678 Copenhagen"


def test_extract_text_of_a_docx_keeps_box_drawing_geometric_bullets_and_rating_stars(tmp_path):
    path = tmp_path / "cv.docx"
    _styled_docx(path, [(None, [_run("Python "), _run("\u2502", font="Calibri"), _run(" Rust \u25b8 Go \u2605\u2605\u2605\u2605\u2606")])], [])
    assert cv_cmd._extract_text(path) == "Python \u2502 Rust \u25b8 Go \u2605\u2605\u2605\u2605\u2606"
    icons = tmp_path / "icons.docx"
    _styled_docx(icons, [(None, [_run("\u260e\ufe0f"), _run("\u2709"), _run("\U0001f4de"), _run(" Copenhagen")])], [])
    assert cv_cmd._extract_text(icons) == "Copenhagen"


def test_extract_text_of_a_docx_reads_a_paragraph_without_a_style_in_the_default_one(tmp_path):
    path = tmp_path / "cv.docx"
    _styled_docx(path, [(None, [_run("(")]), ("Body", [_run("Jane Doe")])], [
        ("Icons", "paragraph", None, "Wingdings", True),
        ("Body", "paragraph", None, "Calibri"),
    ])
    assert cv_cmd._extract_text(path) == "Jane Doe"


def test_extract_text_of_a_docx_leaves_out_a_run_naming_a_symbol_font_for_high_ansi_only(tmp_path):
    path = tmp_path / "cv.docx"
    icon = '<w:r><w:rPr><w:rFonts w:hAnsi="Wingdings"/></w:rPr><w:t>(</w:t></w:r>'
    _styled_docx(path, [(None, [icon, _run(" Jane Doe")])], [])
    assert cv_cmd._extract_text(path) == "Jane Doe"


def test_extract_text_of_a_docx_reads_a_style_based_on_itself(tmp_path):
    path = tmp_path / "cv.docx"
    _styled_docx(path, [("Loop", [_run("Jane Doe", style="Ring")])], [
        ("Loop", "paragraph", "Loop", None),
        ("Ring", "character", "Round", None),
        ("Round", "character", "Ring", None),
    ])
    assert cv_cmd._extract_text(path) == "Jane Doe"


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
    assert args[args.index("--system-prompt") + 1] == claude_cli.prompt("cv-drafter", webfetch_rules=common._WEBFETCH_RULES)
    assert json.loads(args[args.index("--json-schema") + 1]) == cv_cmd._SCHEMA
    assert args[args.index("--allowedTools") + 1] == "WebFetch(domain:github.com),WebFetch(domain:www.github.com),WebFetch(domain:api.github.com)"
    assert "--restricted" in args and args[args.index("--tools") + 1] == "WebFetch"
    assert args[args.index("--model") + 1] == claude_cli.model_of("cv-drafter")
    for needle in ("Lead Data Scientist at Acme", "Senior Data Scientist at Big Bank", "PhD Copenhagen 2015", "https://github.com/jane"):
        assert needle in call["input"], needle
    assert "## Work Experience" in call["input"]  # the example CV's structure is the template
    assert "Jane Doe" in call["input"] and "Data Scientist" in call["input"]  # the profile's own fields
    assert call["profile_dir"] == env.profile_dir
    for word in ("backbone", "subpages", "api.github.com", "never invent", "TODO"):
        assert word in claude_cli.prompt("cv-drafter", webfetch_rules=common._WEBFETCH_RULES), word


def test_a_draft_from_files_alone_has_no_tools(env, monkeypatch):
    calls = []
    _answer(monkeypatch, calls=calls)
    cv_cmd._draft_cv_core([str(env.tmp / "notes.md")], profile_dir=env.profile_dir)
    args = calls[0]["args"]
    assert args[args.index("--tools") + 1] == "" and "--allowedTools" not in args


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


def _draft_answering(env, monkeypatch, markdown, todos=(), skills_headings=()):
    answer = {"cv_markdown": markdown, "todos": list(todos), "skills_headings": list(skills_headings)}
    monkeypatch.setattr(claude_cli, "run", lambda *a, **k: json.dumps({"result": json.dumps(answer)}))
    return cv_cmd._draft_cv_core([str(env.tmp / "notes.md")], profile_dir=env.profile_dir)


@pytest.mark.parametrize("line", ["TODO", "- TODO", "TODO: add your skills", "**Tools:** TODO"])
def test_draft_never_asks_for_a_skills_section_the_sources_did_not_show(env, monkeypatch, line):
    result = _draft_answering(
        env, monkeypatch, f"# Ada\n\n## Skills\n\n{line}\n\n## Languages\n\n- English\n",
        ["Add your skills", "Add the year of your MSc"], ["Skills"],
    )
    assert result["markdown"] == "# Ada\n\n## Languages\n\n- English\n"
    assert result["todos"] == ["Add the year of your MSc"]
    assert env.draft_path.read_text() == result["markdown"]


def test_draft_keeps_the_skills_it_found_beside_a_todo(env, monkeypatch):
    result = _draft_answering(env, monkeypatch, "## Kompetencer\n\nPython, SQL, TODO\n- TODO\n- Excel\n", skills_headings=["Kompetencer"])
    assert result["markdown"] == "## Kompetencer\n\nPython, SQL\n- Excel\n"


def test_draft_keeps_a_todo_in_any_other_section(env, monkeypatch):
    result = _draft_answering(env, monkeypatch, "## Skills\n\nPython\n\n## Education\n\nMSc, TODO year\n", ["Add your skills list", "x"], ["Skills"])
    assert "MSc, TODO year" in result["markdown"]
    assert result["todos"] == ["Add your skills list", "x"]  # nothing was taken out of Skills


@pytest.mark.parametrize(
    "data",
    [
        "Ingénieure données – Clermont".encode("utf-8"),
        b"\xef\xbb\xbf" + "Ingénieure données – Clermont".encode("utf-8"),  # UTF-8 with a BOM (Notepad's "UTF-8 with BOM")
        "Ingénieure données – Clermont".encode("utf-16"),  # Notepad's "Unicode": UTF-16 with a BOM
        "Ingénieure données – Clermont".encode("cp1252"),  # Notepad's "ANSI" on a Western Windows
    ],
    ids=["utf-8", "utf-8-bom", "utf-16", "ansi"],
)
def test_extract_text_reads_a_text_cv_in_the_encodings_windows_saves(tmp_path, data):
    (tmp_path / "cv.txt").write_bytes(data)
    assert cv_cmd._extract_text(tmp_path / "cv.txt") == "Ingénieure données – Clermont"


def test_the_draft_rules_allow_a_location_as_the_last_part_of_an_entry_heading():
    from door.commands import cv as cv_cmd

    assert "### Role | Company — dates | Location" in claude_cli.prompt("cv-drafter", webfetch_rules=common._WEBFETCH_RULES)


FIXTURES = REPO_ROOT / "tests" / "commands" / "fixtures"
ICONS_FR = FIXTURES / "scrubbed-altacv-icons-fr.pdf"


def _pdfium_text(pdf):
    from door.render import pdf_render

    return "\n".join(pdf_render.page_texts(pdf)).strip()


# an icon-font glyph reads back as a stray character ("!", "Ó", "½"): the model would copy it into cv.md (#266)
def test_extract_text_of_a_pdf_leaves_out_its_icon_glyphs():
    text = cv_cmd._extract_text(FIXTURES / "scrubbed-pages-header-en.pdf")
    assert "!" not in text
    assert "Merle abeille parapluie lampe les chemise promenade printemps promenade." in text
    assert "petit." in [line.strip() for line in text.splitlines()]


def test_extract_text_of_a_pdf_leaves_out_its_icon_glyphs_in_the_contact_line():
    text = cv_cmd._extract_text(ICONS_FR)
    assert not set("[Ó½¯\x11") & set(text)
    assert "(+89) 079788144 Ours, Tortue (paysage a couteau) bougie-nuageux" in " ".join(text.split())


# a level written as dots is information and a bullet is list structure: neither is an icon, even drawn with the
# icon font (#313)
def test_extract_text_of_a_pdf_keeps_level_dots_and_bullets_drawn_with_the_icon_font():
    text = cv_cmd._extract_text(ICONS_FR)
    assert text.count("○") + text.count("●") == _pdfium_text(ICONS_FR).count("○")
    assert "•" in text


# a level in the dots' colour, not their shape: the same glyph in a dark colour is filled, in a pale one empty
def test_extract_text_of_a_pdf_says_a_level_shown_by_the_colour_of_its_dots():
    text = " ".join(cv_cmd._extract_text(ICONS_FR).split())
    assert "Matinée ●●●●●" in text
    assert "Crayon (IL6) ●●●●○" in text


def test_extract_text_of_a_pdf_with_no_icons_is_pdfiums_text(env):
    assert cv_cmd._extract_text(env.tmp / "old-cv.pdf") == _pdfium_text(env.tmp / "old-cv.pdf")


def test_extract_text_of_a_pdf_keeps_dots_and_bullets_in_a_font_of_their_own_and_drops_its_glyphs(tmp_path):
    from pdf_utils import raw_pdf

    # ZapfDingbats: ( is a plane, l a black circle, 4 a check mark
    content = """BT /F1 11 Tf 50 760 Td (Jane Doe) Tj ET
BT /F6 9 Tf 50 740 Td (\\() Tj ET BT /F1 11 Tf 64 740 Td (+45 1234 5678) Tj ET
BT /F6 9 Tf 50 720 Td (l) Tj ET BT /F1 11 Tf 64 720 Td (Led the team) Tj ET
BT /F1 11 Tf 50 700 Td (Python) Tj ET BT /F6 9 Tf 120 700 Td (l l l) Tj ET
BT /F6 9 Tf 50 680 Td (4) Tj ET BT /F1 11 Tf 64 680 Td (Certified) Tj ET
BT /F1 11 Tf 50 660 Td (Data engineer building pipelines in Copenhagen since 2019.) Tj ET"""
    pdf = tmp_path / "cv.pdf"
    pdf.write_bytes(raw_pdf(content, fonts={"F6": "ZapfDingbats"}))
    lines = [" ".join(line.split()) for line in cv_cmd._extract_text(pdf).splitlines()]
    assert lines == ["Jane Doe", "+45 1234 5678", "● Led the team", "Python ● ● ●", "Certified",
                     "Data engineer building pipelines in Copenhagen since 2019."]


def test_the_draft_rules_keep_the_cvs_own_section_headings_and_groups():
    from door.commands import cv as cv_cmd

    assert "word for word" in claude_cli.prompt("cv-drafter", webfetch_rules=common._WEBFETCH_RULES) and "never renamed" in claude_cli.prompt("cv-drafter", webfetch_rules=common._WEBFETCH_RULES)
    assert "`### Title` line of its own" in claude_cli.prompt("cv-drafter", webfetch_rules=common._WEBFETCH_RULES)


@pytest.mark.parametrize("title", ["Technical & Programming Skills", "Kompetencer og værktøjer", "My toolbox"])
def test_draft_drops_a_skills_todo_under_the_title_the_model_named(env, monkeypatch, title):
    result = _draft_answering(
        env, monkeypatch, f"# Ada\n\n## {title}\n\nTODO\n\n## Languages\n\n- English\n", [f"Add {title}"], [title],
    )
    assert result["markdown"] == "# Ada\n\n## Languages\n\n- English\n"
    assert result["todos"] == []


def test_draft_keeps_a_todo_under_a_title_the_model_did_not_name_a_skills_one(env, monkeypatch):
    result = _draft_answering(env, monkeypatch, "## My toolbox\n\nTODO\n")
    assert "TODO" in result["markdown"]


def test_draft_asks_for_its_skills_headings_and_no_kind_markers():
    assert "skills_headings" in cv_cmd._SCHEMA["required"] and "skills_headings" in claude_cli.prompt("cv-drafter", webfetch_rules=common._WEBFETCH_RULES)
    assert "<!-- kind:" not in claude_cli.prompt("cv-drafter", webfetch_rules=common._WEBFETCH_RULES)


def test_a_todo_goes_with_the_todo_line_it_was_about(env, monkeypatch):
    result = _draft_answering(
        env, monkeypatch, "# Ada\n\n## Technical Skills\n\nTODO: list your tools\n\n## Languages\n\n- English\n",
        ["List your tools and frameworks", "Add the year of your MSc"], ["Technical Skills"],
    )
    assert result["markdown"] == "# Ada\n\n## Languages\n\n- English\n"
    assert result["todos"] == ["Add the year of your MSc"]
