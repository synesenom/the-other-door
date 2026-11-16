"""`compile` places a template's side-column sections (#147): a template.json `columns.side` names the section kinds
that go in a narrow column; the CV body is wrapped as the header, then `div.main` and `div.side`, each in the order
`cv.md` gives; the file on disk and the letter are never split."""

import json

import pytest

from compile_utils import install
from door.commands import compile as compile_cmd
from door.tailoring import html_doc
from door.core import workspace

POSTING = {"title": "T", "company": "C", "location": "Copenhagen"}


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A profile, the code's templates, a job folder and a fake print (a smaller twin of test_compile_unit's)."""
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "config.json").write_text(json.dumps({"name": "Jane Doe", "location": "Copenhagen"}))
    example = tmp_path / "profile.example"
    (example / "fonts").mkdir(parents=True)
    (example / "cv.template.html").write_text(
        '<html lang="<<lang>>"><style>.photo { width: 2cm }</style><body>\n<<body>>\n</body></html>')
    (example / "cover-letter.template.html").write_text('<html lang="<<lang>>"><body><<body>></body></html>')
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile)
    monkeypatch.setattr(workspace, "PROFILE_EXAMPLE_DIR", example)
    printed = install(monkeypatch)
    jobs = tmp_path / "jobs"
    out = jobs / "output" / "job1"
    out.mkdir(parents=True)

    def make(cv=None, letter=None, posting=POSTING):
        (out / "posting.json").write_text(json.dumps(posting))
        if cv is not None:
            (out / "cv.html").write_text(cv, encoding="utf-8")
        if letter is not None:
            (out / "cover_letter.html").write_text(letter, encoding="utf-8")

    return type("World", (), {"make": staticmethod(make), "out": out, "print": printed, "example": example,
                              "jobs": jobs})


def _compile(world):
    return compile_cmd._compile_core("job1", jobs_dir=world.jobs)

CV = """<!-- Keywords: IFRS -->
<header class="cv-header"><h1>Jane Doe</h1><p class="contact"><span>x</span></p></header>
<h2>Profile</h2><p>A controller.</p>
<h2>Experience</h2><div class="entry"><h3>Controller | Acme - 2021</h3><ul><li>Closed books.</li></ul></div>
<h2>Skills</h2><p>IFRS, SQL</p>
<h2>Education</h2><div class="entry"><h3>MSc | CBS - 2015</h3></div>
<h2>Languages</h2><ul><li><strong>Danish</strong> <span class="level level-5">native</span></li></ul>
"""


def _columns(world, side=("skills", "languages")):
    (world.example / "template.json").write_text(json.dumps({"columns": {"side": list(side)}}))


def _html(world):
    return world.print.calls[0]["html"].split("<body>", 1)[1]


def _order(html, *names):
    return [html.index(n) for n in names]


def test_the_side_sections_go_in_a_side_div_after_the_main_one_in_cv_order(world):
    _columns(world)
    world.make(cv=CV)
    assert _compile(world)["results"][0]["status"] == "compiled"
    html = _html(world)
    assert html.index("</header>") < html.index('<div class="main">') < html.index('<div class="side">')
    main, side = html.split('<div class="side">')
    assert all(f"<h2>{h}</h2>" in main for h in ("Profile", "Experience", "Education"))
    assert all(f"<h2>{h}</h2>" in side for h in ("Skills", "Languages"))
    assert side.index("<h2>Skills</h2>") < side.index("<h2>Languages</h2>")
    assert main.index("<h2>Experience</h2>") < main.index("<h2>Education</h2>")


def test_the_file_on_disk_is_left_as_written(world):
    _columns(world)
    world.make(cv=CV)
    _compile(world)
    assert (world.out / "cv.html").read_text(encoding="utf-8") == CV


def test_an_unknown_heading_stays_in_the_main_column(world):
    _columns(world)
    world.make(cv=CV + "<h2>Publications</h2><p>One.</p>")
    _compile(world)
    main = _html(world).split('<div class="side">')[0]
    assert "<h2>Publications</h2>" in main


def test_a_danish_ad_finds_its_side_sections_by_their_danish_titles(world):
    _columns(world)
    cv = CV.replace("<h2>Skills</h2>", "<h2>Kompetencer</h2>").replace("<h2>Languages</h2>", "<h2>Sprog</h2>")
    world.make(cv=cv, posting={**POSTING, "language": "da"})
    _compile(world)
    side = _html(world).split('<div class="side">')[1]
    assert "<h2>Kompetencer</h2>" in side and "<h2>Sprog</h2>" in side


def test_the_heading_is_matched_whole_and_without_case(world):
    _columns(world, side=("skills",))
    cv = CV.replace("<h2>Skills</h2>", "<h2>KEY SKILLS</h2>").replace("<h2>Education</h2>", "<h2>Skills I want to learn</h2>")
    world.make(cv=cv)
    _compile(world)
    main, side = _html(world).split('<div class="side">')
    assert "<h2>KEY SKILLS</h2>" in side and "<h2>Skills I want to learn</h2>" in main


def test_a_template_without_columns_gets_the_body_as_it_was(world):
    world.make(cv=CV)
    _compile(world)
    html = _html(world)
    assert 'class="main"' not in html and 'class="side"' not in html and "<h2>Skills</h2>" in html


def test_a_manifest_with_no_columns_key_is_not_split_either(world):
    (world.example / "template.json").write_text(json.dumps({"max_pages": 2}))
    world.make(cv=CV)
    _compile(world)
    assert 'class="side"' not in _html(world)


def test_the_letter_is_never_split(world):
    _columns(world)
    world.make(letter="<h2>Skills</h2><p>Dear team</p>")
    _compile(world)
    assert 'class="main"' not in _html(world) and 'class="side"' not in _html(world)


@pytest.mark.parametrize("cls", ["main", "side"])
def test_a_column_class_written_by_the_model_is_refused(world, cls):
    _columns(world)
    world.make(cv=f'<h2>Skills</h2><div class="{cls}"><p>x</p></div>')
    entry = _compile(world)["results"][0]
    assert entry["status"] == "error" and "class" in entry["stderr"] and world.print.calls == []


def test_the_photo_stays_in_the_header_before_the_columns(world, tmp_path):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (300, 400), "tan").save(buf, "JPEG")
    (tmp_path / "profile" / "photo.jpg").write_bytes(buf.getvalue())
    (tmp_path / "profile" / "config.json").write_text(json.dumps(
        {"name": "Jane Doe", "location": "Copenhagen", "photo": str(tmp_path / "profile" / "photo.jpg")}))
    _columns(world)
    world.make(cv=CV.replace('<header class="cv-header">', '<header class="cv-header"><<photo>>'))
    _compile(world)
    html = _html(world)
    assert html.index('class="photo"') < html.index('<div class="main">')


def test_the_readback_follows_the_placed_order(world, monkeypatch):
    seen = {}

    def check(pdf, body, name, **kw):
        seen["headings"] = html_doc.headings(body)
        return []

    _columns(world)
    monkeypatch.setattr(compile_cmd.readability, "check_pdf", check)
    world.make(cv=CV)
    _compile(world)
    assert seen["headings"] == ["Profile", "Experience", "Education", "Skills", "Languages"]


def test_without_columns_the_readback_keeps_the_bodys_own_order(world, monkeypatch):
    seen = {}
    monkeypatch.setattr(compile_cmd.readability, "check_pdf",
                        lambda pdf, body, name, **kw: seen.setdefault("headings", html_doc.headings(body)) or [])
    world.make(cv=CV)
    _compile(world)
    assert seen["headings"] == ["Profile", "Experience", "Skills", "Education", "Languages"]


def test_a_side_of_interests_alone_with_no_interests_section_leaves_main_whole_and_side_empty(world, monkeypatch):
    seen = {}

    def check(pdf, body, name, **kw):
        seen["headings"] = html_doc.headings(body)
        return []

    monkeypatch.setattr(compile_cmd.readability, "check_pdf", check)
    _columns(world, side=("interests",))
    world.make(cv=CV)
    result = _compile(world)["results"][0]
    main, side = _html(world).split('<div class="side">')
    assert all(f"<h2>{h}</h2>" in main for h in ("Profile", "Experience", "Skills", "Education", "Languages"))
    assert side.split("</div>")[0].strip() == ""
    assert seen["headings"] == ["Profile", "Experience", "Skills", "Education", "Languages"]
    assert result["status"] == "compiled" and not result.get("readable")
