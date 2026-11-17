"""The previews of the CV style (#207): the user's cv.md and a sample letter printed in the rebuilt template and in the
default one, kept in HOME/.style/preview/<default|like>/ and made again only when what they are made from changed. The
print is stood in by a one page PDF; the real one is in test_style_preview.py."""

import io
import json
import shutil
import threading
import time

import pytest
from PIL import Image

from door.core import workspace
from door import version
from door.render import html_pdf
from door.style import style_preview
from paths import REPO_ROOT, TESTS_DIR

PDF = TESTS_DIR / "style" / "fixtures" / "styles" / "html-plain-single.pdf"
CV = "# Ada Lovelace\n\n**Email:** ada@example.com | **Phone:** +45 1234 5678\n\n## Experience\n\n### Analyst | Acme - 2020\n\n- Built things.\n"


class Printer:
    """Stands in for `html_pdf.print_html`: records the page and the assets, writes a one page PDF."""

    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, folder, html, pdf, *, assets=None, **kw):
        if self.fail:
            raise html_pdf.PrintError("no Chromium: run doctor --fix")
        self.calls.append({"html": html, "pdf": pdf.name, "assets": assets})
        shutil.copyfile(PDF, pdf)


@pytest.fixture
def world(tmp_path, monkeypatch):
    home, profile = tmp_path, tmp_path / "profile"
    profile.mkdir()
    (profile / "cv.md").write_text(CV, encoding="utf-8")
    monkeypatch.setattr(workspace, "HOME", home)
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile)
    printer = Printer()
    monkeypatch.setattr(html_pdf, "print_html", printer)
    return home, profile, printer


def _style(profile):
    folder = profile / "style"
    folder.mkdir()
    for name in ("cv.template.html", "cover-letter.template.html"):
        shutil.copyfile(REPO_ROOT / "profile.example" / name, folder / name)
    return folder


def _show(home, profile, config=None):
    return style_preview.show(home, profile, config or {})


def test_the_sample_letter_is_the_users_name_and_contact_with_the_date_filled():
    letter = style_preview.sample_letter(CV)
    assert "<h1>Ada Lovelace</h1>" in letter and "ada@example.com" in letter
    assert "<<date>>" not in letter and "Jane Doe" not in letter
    assert letter.rstrip().endswith("<p>Ada Lovelace</p></div>")


def test_a_cv_with_no_name_gives_a_letter_with_no_header_and_no_signature(world):
    letter = style_preview.sample_letter("## Experience\n\n- x\n")
    assert "letter-header" not in letter and "Jane Doe" not in letter and "<p></p></div>" in letter
    home, profile, printer = world
    (profile / "cv.md").write_text("## Experience\n\n- x\n", encoding="utf-8")
    _show(home, profile)
    assert "Hiring team" in printer.calls[1]["html"] and "<p></p></div>" in printer.calls[1]["html"]
    assert "Jane Doe" not in printer.calls[1]["html"]


def test_the_sample_letter_escapes_the_name():
    assert "<b>" not in style_preview.sample_letter("# A <b>x</b>\n\n## S\n")


def test_without_a_style_only_the_default_is_shown_and_it_is_written_whole(world):
    home, profile, printer = world
    shown = _show(home, profile)
    assert list(shown["styles"]) == ["default"]
    default = shown["styles"]["default"]
    folder = home / ".style" / "preview" / "default"
    assert default["cv"] == [str(folder / "cv_page_1.png")] and default["letter"] == [str(folder / "letter_page_1.png")]
    Image.open(default["cv"][0]).verify()
    assert [c["pdf"] for c in printer.calls] == ["cv.pdf", "letter.pdf"]
    assert "Ada Lovelace" in printer.calls[0]["html"] and "Ada Lovelace" in printer.calls[1]["html"]
    assert list((home / ".style" / "preview").iterdir()) == [folder]  # no staging left
    assert default["version"] and default["two_column"] is False


def test_show_sweeps_a_stale_staging_folder_a_killed_show_left(world):
    import os
    from door.core import utils
    home, profile, printer = world
    stale = home / ".style" / "preview" / ".default.x.part"
    stale.mkdir(parents=True)
    old = time.time() - 2 * utils.STALE_PART_SECONDS
    os.utime(stale, (old, old))
    _show(home, profile)
    assert not stale.exists()


def test_a_second_show_prints_nothing_while_nothing_changed(world):
    home, profile, printer = world
    first = _show(home, profile)
    printed = len(printer.calls)
    assert _show(home, profile) == first and len(printer.calls) == printed


def test_a_saved_cv_prints_again(world):
    home, profile, printer = world
    _show(home, profile)
    (profile / "cv.md").write_text(CV + "- More.\n", encoding="utf-8")
    _show(home, profile)
    assert len(printer.calls) == 4


def test_a_built_style_adds_like_and_a_change_of_it_prints_only_that_set(world):
    home, profile, printer = world
    _show(home, profile)
    folder = _style(profile)
    shown = _show(home, profile)
    assert list(shown["styles"]) == ["default", "like"] and len(printer.calls) == 4
    (folder / "cv.template.html").write_text((folder / "cv.template.html").read_text() + "<!-- x -->", encoding="utf-8")
    _show(home, profile)
    assert len(printer.calls) == 6
    shutil.rmtree(folder)
    assert list(_show(home, profile)["styles"]) == ["default"]
    assert not (home / ".style" / "preview" / "like").exists()


def test_the_default_is_the_template_a_prepare_would_use(world):
    home, profile, printer = world
    (profile / "cv.template.html").write_text("<html lang='<<lang>>'><body>MINE <<body>></body></html>", encoding="utf-8")
    _show(home, profile)
    assert "MINE" in printer.calls[0]["html"]


def test_a_set_that_cannot_print_is_left_out_not_an_error(world, monkeypatch):
    home, profile, _ = world
    monkeypatch.setattr(html_pdf, "print_html", Printer(fail=True))
    assert _show(home, profile) == {"styles": {}}
    assert not (home / ".style" / "preview" / "default").exists()


def test_the_cv_is_printed_in_its_language_the_letter_in_english(world):
    home, profile, printer = world
    (profile / "cv.md").write_text("# Ada\n\n## Profil\n\nJe suis une ingénieure de données avec huit ans d'expérience dans la construction de "
                                   "plateformes fiables pour les équipes de finance et de logistique en France.\n", encoding="utf-8")
    _show(home, profile)
    assert 'lang="fr"' in printer.calls[0]["html"] and 'lang="en"' in printer.calls[1]["html"]


def _jpeg(path):
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), "grey").save(buf, "JPEG")
    path.write_bytes(buf.getvalue())


def test_the_photo_is_in_the_cv_when_the_country_allows_it_and_its_change_prints_again(world):
    home, profile, printer = world
    _jpeg(profile / "photo.jpg")
    config = {"photo": str(profile / "photo.jpg"), "location": "Paris"}
    (profile / "cv.template.html").write_text("<html lang='<<lang>>'><style>.photo{width:2cm}</style><body><<body>></body></html>", encoding="utf-8")
    (profile / "cv.md").write_text("# Ada\n\n**Email:** ada@example.com\n\n## Experience\n\n- x\n", encoding="utf-8")
    _show(home, profile, config)
    assert '<img class="photo"' in printer.calls[0]["html"] and "<img" not in printer.calls[1]["html"]
    assert not list((home / ".style" / "preview" / "default").glob("photo.*"))
    Image.new("RGB", (100, 100), "black").save(profile / "photo.jpg")
    _show(home, profile, config)
    assert len(printer.calls) == 4


def test_a_set_is_made_again_when_the_version_or_a_served_font_changes(world, monkeypatch):
    home, profile, printer = world
    folder = _style(profile)
    (folder / "fonts").mkdir()
    (folder / "fonts" / "F.ttf").write_bytes(b"one")
    (folder / "template.json").write_text(json.dumps({"fonts": ["F.ttf"]}), encoding="utf-8")
    first = _show(home, profile)
    assert len(printer.calls) == 4
    (folder / "fonts" / "F.ttf").write_bytes(b"two")
    second = _show(home, profile)
    assert len(printer.calls) == 6 and second["styles"]["like"]["version"] != first["styles"]["like"]["version"]
    monkeypatch.setattr(version, "VERSION", "9.9.9")
    _show(home, profile)
    assert len(printer.calls) == 10


def test_the_letter_is_printed_with_the_cv_templates_assets(world):
    home, profile, printer = world
    _show(home, profile)
    assert printer.calls[0]["assets"] == printer.calls[1]["assets"]


def test_a_style_with_a_broken_manifest_is_left_out_and_the_default_is_shown(world):
    home, profile, printer = world
    folder = _style(profile)
    (folder / "template.json").write_text("{not json", encoding="utf-8")
    assert list(_show(home, profile)["styles"]) == ["default"]


def test_a_set_with_a_missing_image_is_made_again(world):
    home, profile, printer = world
    _show(home, profile)
    (home / ".style" / "preview" / "default" / "cv_page_1.png").unlink()
    shown = _show(home, profile)
    assert len(printer.calls) == 4 and (home / ".style" / "preview" / "default" / "cv_page_1.png").is_file() and shown["styles"]["default"]["cv"]


def test_without_a_cv_the_example_one_is_shown(world):
    home, profile, printer = world
    (profile / "cv.md").unlink()
    _show(home, profile)
    assert "Jane Doe" in printer.calls[0]["html"]


def test_a_pdf_that_cannot_be_read_back_leaves_the_set_out(world, monkeypatch):
    import pypdfium2
    home, profile, printer = world

    def broken(*a, **kw):
        raise pypdfium2.PdfiumError("Failed to load document")
    monkeypatch.setattr(style_preview.pdf_render, "render_pdf_pages", broken)
    assert _show(home, profile) == {"styles": {}}


def test_two_shows_at_once_both_get_every_image(world, monkeypatch):
    home, profile, _ = world

    def slow(folder, html, pdf, *, assets=None, **kw):
        time.sleep(0.2)
        shutil.copyfile(PDF, pdf)
    monkeypatch.setattr(html_pdf, "print_html", slow)
    results, errors = {}, []

    def run(i):
        try:
            results[i] = _show(home, profile)
        except Exception as exc:  # the test names what was raised
            errors.append(repr(exc))
    threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
        time.sleep(0.05)
    for t in threads:
        t.join()
    assert errors == [] and len(results) == 2
    for shown in results.values():
        assert shown["styles"]["default"]["cv"] and shown["styles"]["default"]["letter"]
    assert [p.name for p in (home / ".style" / "preview").iterdir()] == ["default"]


def test_like_is_the_candidate_when_one_waits_else_the_style_kept(world):
    home, profile, printer = world
    kept = _style(profile)
    (kept / "cv.template.html").write_text((kept / "cv.template.html").read_text() + "<!-- kept -->", encoding="utf-8")
    _show(home, profile)
    printer.calls.clear()
    candidate = profile / "style.next"
    shutil.copytree(kept, candidate)
    (candidate / "cv.template.html").write_text((REPO_ROOT / "profile.example" / "cv.template.html").read_text() + "<!-- candidate -->",
                                                 encoding="utf-8")
    _show(home, profile)
    assert any("<!-- candidate -->" in c["html"] for c in printer.calls)
    assert not any("<!-- kept -->" in c["html"] for c in printer.calls)


def test_moving_the_candidate_in_prints_nothing_again(world):
    home, profile, printer = world
    candidate = _style(profile)
    candidate.rename(profile / "style.next")
    _show(home, profile)
    printed = len(printer.calls)
    (profile / "style.next").rename(profile / "style")
    _show(home, profile)
    assert len(printer.calls) == printed
