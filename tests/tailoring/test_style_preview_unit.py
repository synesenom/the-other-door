"""The previews of the CV style (#207): the user's cv.md and a sample letter printed in the rebuilt template and in the
default one, kept in HOME/.style/preview/<default|like>/ and made again only when what they are made from changed. The
print is stood in by a one page PDF; the real one is in test_style_preview.py."""

import io
import json
import shutil

import pytest
from PIL import Image

from door.core import workspace
from door.tailoring import html_pdf, style_preview
from paths import REPO_ROOT, TESTS_DIR

PDF = TESTS_DIR / "tailoring" / "fixtures" / "styles" / "html-plain-single.pdf"
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


def test_the_sample_letter_of_the_build_keeps_a_fictional_header():
    letter = style_preview.sample_letter()
    assert "Jane Doe" in letter and "<<date>>" not in letter


def test_the_sample_letter_escapes_the_name():
    assert "<b>" not in style_preview.sample_letter("# A <b>x</b>\n\n## S\n")


def test_without_a_style_only_the_default_is_shown_and_it_is_written_whole(world):
    home, profile, printer = world
    shown = _show(home, profile)
    assert list(shown["styles"]) == ["default"]
    default = shown["styles"]["default"]
    folder = home / ".style" / "preview" / "default"
    assert default["cv"] == [str(folder / "cv_page_1.png")] and default["letter"] == [str(folder / "letter_page_1.png")]
    assert sorted(p.name for p in folder.iterdir()) == ["cv.pdf", "cv_page_1.png", "letter.pdf", "letter_page_1.png", "meta.json"]
    Image.open(default["cv"][0]).verify()
    assert [c["pdf"] for c in printer.calls] == ["cv.pdf", "letter.pdf"]
    assert "Ada Lovelace" in printer.calls[0]["html"] and "Ada Lovelace" in printer.calls[1]["html"]
    assert list((home / ".style" / "preview").iterdir()) == [folder]  # no staging left


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
