"""The example templates, really compiled (#357, #623): the example CV and letter each fit one page, read back with
nothing an ATS would miss, and are set in the templates' own fonts (Figtree, headings in Young Serif) from
profile.example/fonts/. Skipped where no Tectonic or xelatex is installed."""

import json
import shutil

import pytest

from door.commands import compile as compile_cmd
from door.core import workspace
from door.core.installers import find_tectonic
from door.tailoring import readability
from paths import REPO_ROOT, TESTS_DIR
from pdf_utils import font_names, image_count, page_count

pytestmark = pytest.mark.skipif(not (find_tectonic() or shutil.which("xelatex")), reason="no LaTeX compiler installed")

FIXTURES = TESTS_DIR / "tailoring" / "fixtures"


def _document(template: str, fixture: str) -> str:
    """The template up to its own `\\begin{document}` (its comments name it too), then the fixture's body."""
    head = (REPO_ROOT / "profile.example" / template).read_text(encoding="utf-8").rsplit("\\begin{document}", 1)[0]
    body = (FIXTURES / fixture).read_text(encoding="utf-8").split("\\begin{document}", 1)[1]
    return head + "\\begin{document}" + body.replace("<<photo>>", "")


@pytest.fixture(scope="module")
def compiled(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("templates")
    out = tmp / "output" / "example"
    out.mkdir(parents=True)
    (out / "posting.json").write_text(json.dumps({"title": "Head of Finance", "company": "Globex Energy", "location": "Aarhus"}))
    (out / "cv.tex").write_text(_document("cv.template.tex", "example_cv.tex"), encoding="utf-8")
    (out / "cover_letter.tex").write_text(_document("cover-letter.template.tex", "example_cover_letter.tex"), encoding="utf-8")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(workspace, "PROFILE_DIR", tmp / "no-profile")
        result = compile_cmd._compile_core("example", jobs_dir=tmp)
    return out, {r["file"]: r for r in result["results"]}


@pytest.mark.parametrize("name", ["cv", "cover_letter"])
def test_the_example_compiles_to_one_page_in_the_templates_fonts(compiled, name):
    out, results = compiled
    assert results[f"{name}.tex"]["status"] == "compiled", results[f"{name}.tex"].get("stderr")
    assert page_count(out / f"{name}.pdf") == 1
    fonts = font_names(out / f"{name}.pdf")
    assert any(f.startswith("Figtree") for f in fonts) and any(f.startswith("YoungSerif") for f in fonts), fonts


def test_the_example_cv_reads_back_with_every_heading_on_its_own_line_and_in_order(compiled):
    out, results = compiled
    tex = (out / "cv.tex").read_text(encoding="utf-8")
    assert readability.check_pdf(out / "cv.pdf", tex, "Jane Doe") == []
    assert results["cv.tex"]["readable"] == []


def test_a_cv_with_a_photo_shows_it_beside_the_header_and_still_reads_back(tmp_path, monkeypatch):
    import io

    from PIL import Image

    profile = tmp_path / "profile"
    profile.mkdir()
    buf = io.BytesIO()
    Image.new("RGB", (350, 450), "tan").save(buf, "JPEG")
    (profile / "photo.jpg").write_bytes(buf.getvalue())
    (profile / "config.json").write_text(json.dumps({"location": "Copenhagen", "photo": str(profile / "photo.jpg")}))
    monkeypatch.setattr(workspace, "PROFILE_DIR", profile)
    out = tmp_path / "output" / "photo"
    out.mkdir(parents=True)
    (out / "posting.json").write_text(json.dumps({"title": "Head of Finance", "company": "Globex Energy", "location": "Copenhagen"}))
    head, begin, body = _document("cv.template.tex", "example_cv.tex").rpartition("\\begin{document}")
    tex = head + begin + "\n<<photo>>" + body
    (out / "cv.tex").write_text(tex, encoding="utf-8")
    result = compile_cmd._compile_core("photo", jobs_dir=tmp_path)["results"][0]
    assert result["status"] == "compiled" and result["photo"] == "photo.jpg", result.get("stderr")
    assert result["readable"] == []
    assert page_count(out / "cv.pdf") == 1
    assert image_count(out / "cv.pdf") == 1
