"""`compile` on the Chromium print (#146): the body fragment is filled, guarded, given its photo and its language's
typography, wrapped in the template and printed; the file on disk stays the body, unwrapped."""

import io
import json

import pytest
from PIL import Image

from compile_utils import install
from door.commands import _common as common
from door.commands import compile as compile_cmd
from door.core import workspace
from door.core.downloads import chromium
from door.render import readability
from paths import TESTS_DIR

NB = " "
POSTING = {"title": "T", "company": "C", "location": "Copenhagen"}


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A profile (with a photo and a name), the code's templates and fonts, a job folder, a fake print."""
    profile = tmp_path / "profile"
    profile.mkdir()
    buf = io.BytesIO()
    Image.new("RGB", (300, 400), "tan").save(buf, "JPEG")
    (profile / "photo.jpg").write_bytes(buf.getvalue())
    (profile / "config.json").write_text(json.dumps(
        {"name": "Jane Doe", "location": "Copenhagen", "photo": str(profile / "photo.jpg")}))
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
        if posting is not None:
            (out / "posting.json").write_text(json.dumps(posting))
        if cv is not None:
            (out / "cv.html").write_text(cv, encoding="utf-8")
        if letter is not None:
            (out / "cover_letter.html").write_text(letter, encoding="utf-8")
        return jobs

    return type("World", (), {"make": staticmethod(make), "out": out, "print": printed, "profile": profile,
                              "example": example, "jobs": jobs, "tmp": tmp_path})


def _compile(world, **kw):
    return compile_cmd._compile_core("job1", jobs_dir=world.jobs, **kw)


# --- the result and the print --------------------------------------------------------------------------------------

def test_a_body_is_wrapped_in_the_template_and_printed_to_a_pdf(world):
    world.make(cv="<h2>Experience</h2><p>Jane Doe</p>")
    result = _compile(world)
    cv, letter = result["results"]
    assert cv["status"] == "compiled" and cv["pdf"] == str(world.out / "cv.pdf") and "compiler" not in cv
    assert letter == {"file": "cover_letter.html", "status": "skipped"}
    html = world.print.calls[0]["html"]
    assert html.startswith('<html lang="en">') and "<h2>Experience</h2>" in html and "<<body>>" not in html
    assert (world.out / "cv.pdf").is_file()


def test_the_chosen_style_is_in_the_cv_and_the_letter(world):
    (world.profile / "config.json").write_text(json.dumps(
        {"name": "Jane Doe", "location": "Copenhagen", "cv_accent": "burgundy", "cv_fonts": "friendly"}))
    (world.example / "cv.template.html").write_text("<html><head></head><body><<body>></body></html>")
    (world.example / "cover-letter.template.html").write_text("<html><head></head><body><<body>></body></html>")
    world.make(cv="<h2>Experience</h2>", letter="<p>Dear</p>")
    _compile(world)
    assert len(world.print.calls) == 2
    for call in world.print.calls:
        assert "#8a1c3c" in call["html"] and "Montserrat" in call["html"]


def test_no_style_keys_add_no_style_block(world):
    world.make(cv="<h2>Experience</h2>")
    _compile(world)
    assert "<style>:root{" not in world.print.calls[0]["html"]


def test_the_file_on_disk_stays_the_body_and_no_print_page_is_left_in_the_folder(world):
    world.make(cv="<<photo>><h2>Experience</h2>")
    _compile(world)
    assert (world.out / "cv.html").read_text(encoding="utf-8") == "<<photo>><h2>Experience</h2>"
    assert sorted(p.name for p in world.out.iterdir() if p.suffix == ".html") == ["cv.html"]


def test_fonts_are_served_from_the_examples_when_the_profile_has_none(world):
    world.make(cv="<p>Jane Doe</p>")
    _compile(world)
    assert world.print.calls[0]["assets"] == {"fonts": sorted((world.example / "fonts").glob("*.ttf"))}
    assert not any("font" in name for name in world.print.calls[0]["files"])


def test_the_profiles_own_truetype_fonts_win(world):
    (world.profile / "fonts").mkdir()
    (world.profile / "fonts" / "Mine.ttf").write_bytes(b"\x00\x01\x00\x00")
    world.make(cv="<p>Jane Doe</p>")
    _compile(world)
    assert world.print.calls[0]["assets"] == {"fonts": [world.profile / "fonts" / "Mine.ttf"]}


def test_a_profile_fonts_folder_without_truetype_is_not_used(world):
    (world.profile / "fonts").mkdir()
    (world.profile / "fonts" / "Old.otf").write_bytes(b"OTTO")
    world.make(cv="<p>Jane Doe</p>")
    _compile(world)
    assert world.print.calls[0]["assets"] == {"fonts": sorted((world.example / "fonts").glob("*.ttf"))}


def test_a_user_template_that_is_html_is_the_one_printed(world):
    (world.profile / "cv.template.html").write_text("<html lang=\"<<lang>>\"><body>MINE <<body>></body></html>")
    world.make(cv="<p>Jane Doe</p>")
    _compile(world)
    assert "MINE <p>Jane Doe</p>" in world.print.calls[0]["html"]


def test_a_template_without_the_body_token_is_an_error(world):
    (world.profile / "cv.template.html").write_text("<html><body>nothing</body></html>")
    world.make(cv="<p>x</p>")
    cv = _compile(world)["results"][0]
    assert cv["status"] == "error" and "<<body>>" in cv["stderr"] and world.print.calls == []


def test_a_print_failure_is_an_error_with_its_words(world, monkeypatch):
    install(monkeypatch, fail="Chromium did not finish printing in 60 s")
    world.make(cv="<p>x</p>", letter="<p>y</p>")
    cv, letter = _compile(world)["results"]
    assert cv["status"] == "error" and "Chromium did not finish printing" in cv["stderr"]
    assert letter["status"] == "error"
    assert not (world.out / "cv.pdf").exists()


def test_no_chromium_raises_the_shared_words(world, monkeypatch):
    monkeypatch.setattr(common, "_chromium_available", lambda: False)
    world.make(cv="<p>x</p>")
    with pytest.raises(common.NoChromium):
        _compile(world)


def test_neither_file_is_two_skips_and_no_print(world):
    world.make()
    assert _compile(world)["results"] == [
        {"file": "cv.html", "status": "skipped"}, {"file": "cover_letter.html", "status": "skipped"}]
    assert world.print.calls == []


def test_a_stale_pdf_is_kept_when_the_next_print_fails(world, monkeypatch):
    world.make(cv="<p>Jane Doe</p>")
    (world.out / "cv.pdf").write_bytes(b"%PDF-stale")
    install(monkeypatch, fail="boom")
    _compile(world)
    assert (world.out / "cv.pdf").read_bytes() == b"%PDF-stale"


# --- render ------------------------------------------------------------------------------------------------------

def test_render_gives_page_pngs_for_the_pdfs_that_compiled(world):
    world.make(cv="<p>Jane Doe resume with enough text to count</p>")
    result = _compile(world, render=True)
    assert [r["file"] for r in result["render"]] == ["cv.pdf"]
    assert result["render"][0]["page_count"] == 1 and (world.out / "cv_page_1.png").is_file()


def test_without_render_nothing_is_rendered(world):
    world.make(cv="<p>Jane Doe</p>")
    assert "render" not in _compile(world)


# --- placeholders ---------------------------------------------------------------------------------------------

def test_company_and_title_are_filled_escaped_and_written_back(world):
    posting = json.loads((TESTS_DIR / "tailoring" / "fixtures" / "injected_posting.json").read_text(encoding="utf-8"))
    world.make(cv="<p>Applying for <<title>> at <<company>>.</p>", posting=posting)
    result = _compile(world)
    body = (world.out / "cv.html").read_text(encoding="utf-8")
    assert "<<title>>" not in body and "<<company>>" not in body
    assert "<script" not in body.lower()
    assert result["results"][0]["status"] == "compiled"
    assert "<p>Applying for" in body


def test_a_title_made_of_markup_is_text_on_the_page(world):
    world.make(cv="<p><<title>> at <<company>></p>",
               posting={"title": "<script>alert(1)</script> R&D", "company": "Evil \"&\" <b>Co</b>"})
    cv = _compile(world)["results"][0]
    body = (world.out / "cv.html").read_text(encoding="utf-8")
    assert cv["status"] == "compiled"
    assert "<script>" not in body and "&lt;script&gt;" in body and "R&amp;D" in body and "&lt;b&gt;Co&lt;/b&gt;" in body


def test_placeholders_without_a_posting_are_an_error(world):
    world.make(cv="<p>At <<company>>.</p>", posting=None)
    cv = _compile(world)["results"][0]
    assert cv["status"] == "error" and "posting.json" in cv["stderr"] and world.print.calls == []


def test_a_body_without_placeholders_is_left_unchanged(world):
    world.make(cv="<p>Plain &amp; more.</p>")
    _compile(world)
    assert (world.out / "cv.html").read_text(encoding="utf-8") == "<p>Plain &amp; more.</p>"


def test_the_letters_date_is_filled_in_the_ads_language(world):
    from datetime import date

    world.make(letter='<p class="date"><<date>></p><p>Cher monsieur</p>', posting={**POSTING, "language": "fr"})
    _compile(world)
    from door import i18n

    assert i18n.format_date(date.today(), "fr") in (world.out / "cover_letter.html").read_text(encoding="utf-8")
    assert "<<date>>" not in world.print.calls[0]["html"]


# --- the guard ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("body, named", [
    ("<script>alert(1)</script>", "<script>"), ('<p onclick="x()">a</p>', "onclick"),
    ('<img src="file:///etc/passwd">', "<img>"), ('<a href="javascript:x">a</a>', "href"),
    ("<p style=\"background:url(x)\">a</p>", "style"), ('<iframe src="x"></iframe>', "<iframe>"),
])
def test_a_body_outside_the_vocabulary_is_refused_and_never_printed(world, body, named):
    world.make(cv=body)
    cv = _compile(world)["results"][0]
    assert cv["status"] == "error" and cv["stderr"].startswith("refused: cv.html uses ") and named in cv["stderr"]
    assert world.print.calls == [] and not (world.out / "cv.pdf").exists()


def test_a_title_cannot_smuggle_markup_past_the_guard(world):
    world.make(cv="<p><<title>></p>", posting={"title": "</p><script>x</script>", "company": "C"})
    assert _compile(world)["results"][0]["status"] == "compiled"
    assert "<script>" not in world.print.calls[0]["html"]


# --- the photo ---------------------------------------------------------------------------------------------------

def _img(html):
    return '<img class="photo" src="photo.jpg" alt="">' in html


def test_the_photo_token_becomes_the_image_and_the_file_is_copied_beside_the_page(world):
    world.make(cv="<header class=\"cv-header\"><<photo>><h1>Jane Doe</h1></header>")
    result = _compile(world)["results"][0]
    assert result["photo"] == "photo.jpg" and _img(world.print.calls[0]["html"])
    assert (world.out / "photo.jpg").read_bytes() == (world.profile / "photo.jpg").read_bytes()
    assert "photo.jpg" in world.print.calls[0]["files"]


def test_the_body_on_disk_keeps_the_token_so_a_recompile_passes_the_guard(world):
    world.make(cv="<<photo>><p>Jane Doe</p>")
    _compile(world)
    assert "<<photo>>" in (world.out / "cv.html").read_text(encoding="utf-8")
    assert "<img" not in (world.out / "cv.html").read_text(encoding="utf-8")
    assert _compile(world)["results"][0]["status"] == "compiled"


def test_no_photo_in_the_profile_means_nothing_in_the_cv(world):
    (world.profile / "config.json").write_text(json.dumps({"name": "Jane Doe", "location": "Copenhagen"}))
    world.make(cv="<<photo>><p>Jane Doe</p>")
    result = _compile(world)["results"][0]
    assert "<img" not in world.print.calls[0]["html"] and "<<photo>>" not in world.print.calls[0]["html"]
    assert "photo" not in result and not (world.out / "photo.jpg").exists()


def test_a_country_that_wants_no_photo_gets_none(world):
    world.make(cv="<<photo>><p>Jane Doe</p>", posting={**POSTING, "location": "London, United Kingdom"})
    _compile(world)
    assert "<img" not in world.print.calls[0]["html"] and not (world.out / "photo.jpg").exists()


def test_a_template_without_the_photo_class_prints_no_photo(world):
    (world.profile / "cv.template.html").write_text(
        '<html lang="<<lang>>"><style>/* .photo is not styled here */</style><body><<body>></body></html>')
    world.make(cv="<<photo>><p>Jane Doe</p>")
    _compile(world)
    assert "<img" not in world.print.calls[0]["html"] and not (world.out / "photo.jpg").exists()


def test_a_photo_that_is_not_a_picture_is_left_out(world):
    (world.profile / "photo.jpg").write_bytes(b"%PDF-1.4")
    world.make(cv="<<photo>><p>Jane Doe</p>")
    _compile(world)
    assert "<img" not in world.print.calls[0]["html"] and not (world.out / "photo.jpg").exists()


def test_only_the_first_token_gets_the_photo(world):
    world.make(cv="<<photo>><p>A</p><<photo>><p>B</p>")
    _compile(world)
    assert world.print.calls[0]["html"].count("<img") == 1


def test_a_job_without_a_country_follows_the_profiles(world):
    world.make(cv="<<photo>><p>Jane Doe</p>", posting={**POSTING, "location": "Remote"})
    _compile(world)
    assert _img(world.print.calls[0]["html"])


def test_a_stale_photo_is_removed_when_this_compile_uses_none(world):
    world.make(cv="<p>Jane Doe</p>")
    (world.out / "photo.png").write_bytes(b"stale")
    _compile(world)
    assert not (world.out / "photo.png").exists()


def test_a_model_written_image_is_refused(world):
    world.make(cv='<<photo>><img class="photo" src="/etc/passwd" alt="">')
    cv = _compile(world)["results"][0]
    assert cv["status"] == "error" and not (world.out / "photo.jpg").exists()


# --- French ------------------------------------------------------------------------------------------------------

def test_a_french_ad_gets_the_french_language_and_typography(world):
    world.make(cv="<p>Compétences : Python ; « SQL »</p>", posting={**POSTING, "language": "fr"})
    _compile(world)
    html = world.print.calls[0]["html"]
    assert html.startswith('<html lang="fr">')
    assert f"Compétences{NB}: Python{NB}; «{NB}SQL{NB}»" in html
    assert "Compétences :" in (world.out / "cv.html").read_text(encoding="utf-8")  # the file stays as written


def test_an_english_ad_is_not_respaced(world):
    world.make(cv="<p>Skills : Python</p>")
    _compile(world)
    assert "Skills : Python" in world.print.calls[0]["html"]


def test_a_link_stays_as_written_in_french(world):
    world.make(cv='<p><a href="https://x.example/?a=b">arXiv:2408.10754</a></p>', posting={**POSTING, "language": "fr"})
    _compile(world)
    assert 'href="https://x.example/?a=b">arXiv:2408.10754</a>' in world.print.calls[0]["html"]


# --- the read-back -----------------------------------------------------------------------------------------------

def test_the_pdf_is_read_back_for_headings_keywords_and_the_name(world):
    world.make(cv="<!-- Keywords: Kubernetes -->\n<h2>Experience</h2><p>Jane Doe</p>", letter="<p>Dear team, Jane Doe is writing to you about the role</p>")
    cv, letter = _compile(world)["results"]
    assert "Kubernetes" in " ".join(p["detail"] for p in cv["readable"])  # the fake print holds the text only
    assert letter["readable"] == []


def test_a_clean_page_reads_back_clean(world):
    world.make(cv="<!-- Keywords: Kubernetes -->\n<h2>Experience</h2><p>Jane Doe uses Kubernetes in every job she has had</p>")
    assert _compile(world)["results"][0]["readable"] == []


def test_a_failing_check_is_a_warning_not_a_failed_compile(world, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("no pdf")

    monkeypatch.setattr(readability, "check_pdf", boom)
    world.make(cv="<p>x</p>")
    cv = _compile(world)["results"][0]
    assert cv["status"] == "compiled" and cv["readable"] is None and "no pdf" in cv["warning"]


def test_an_errored_entry_has_no_readable(world):
    world.make(cv="<script>x</script>")
    assert "readable" not in _compile(world)["results"][0]


# --- a user's own template ----------------------------------------------------------------------------------------

def test_a_users_own_template_prints_with_the_profiles_fonts_and_ignores_a_template_json_beside_it(world):
    (world.profile / "cv.template.html").write_text("<html lang=\"<<lang>>\"><body><<body>></body></html>")
    (world.profile / "fonts").mkdir()
    (world.profile / "fonts" / "Own.ttf").write_bytes(b"\x00\x01\x00\x00")
    (world.profile / "template.json").write_text(json.dumps({"fonts": ["Other.ttf"], "columns": {"side": ["skills"]}}))
    world.make(cv="<h2 class=\"kind-skills\">Skills</h2><p>Jane Doe</p>")
    assert _compile(world)["results"][0]["status"] == "compiled"
    assert world.print.calls[0]["assets"] == {"fonts": [world.profile / "fonts" / "Own.ttf"]}
    assert "side" not in world.print.calls[0]["html"]


def test_the_cvs_check_is_asked_for_and_the_letters_is_not(world, monkeypatch):
    seen = {}

    def check(pdf, body, name, **kw):
        seen[pdf.name] = kw
        return []

    monkeypatch.setattr(compile_cmd.readability, "check_pdf", check)
    world.make(cv="<h2>Experience</h2><p>Jane Doe</p>", letter="<p>Dear team</p>")
    _compile(world)
    assert seen["cv.pdf"] == {"cv": True}
    assert seen["cover_letter.pdf"] == {"cv": False}


# --- a tagline and the contact kinds (#189) ------------------------------------------------------------------------

def test_a_header_with_a_tagline_and_kinds_compiles_and_the_file_stays_as_written(world):
    body = ('<header class="cv-header"><h1>Jane Doe</h1><p class="tagline">Controller | Reporting</p>'
            '<p class="contact"><span class="phone">+45 1</span><span class="linkedin">'
            '<a href="https://www.linkedin.com/in/jane">LinkedIn</a></span></p></header><h2>Experience</h2>')
    world.make(cv=body)
    cv = _compile(world)["results"][0]
    assert cv["status"] == "compiled", cv
    assert (world.out / "cv.html").read_text(encoding="utf-8") == body
    assert 'class="tagline"' in world.print.calls[0]["html"]


def test_a_plain_span_for_any_other_detail_passes_beside_the_kinded_ones(world):
    body = ('<header class="cv-header"><h1>Jane Doe</h1><p class="contact"><span class="phone">+45 1</span>'
            '<span>Born 1 May 1990</span><span><a href="https://example.com/jane">Portfolio</a></span></p></header>'
            "<h2>Experience</h2>")
    world.make(cv=body)
    assert _compile(world)["results"][0]["status"] == "compiled"


def test_a_hand_edited_location_that_is_no_text_does_not_stop_a_compile_with_no_photo(world):
    (world.profile / "config.json").write_text(json.dumps({"name": "Jane Doe", "location": 5}))
    world.make(cv="<<photo>><p>Jane Doe</p>", posting={"title": "T", "company": "C"})
    assert _compile(world)["results"][0]["status"] == "compiled"
