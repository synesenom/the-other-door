"""The test world's stylist stand-in (app/test/world/stylist.py, #205): what it answers a stylist call must be what the
builder accepts (the blocks it reads, a template and a letter that pass the guard)."""

import subprocess
import sys

from door.core import templates
from door.tailoring import html_guard, style_build
from paths import REPO_ROOT

STAND_IN = REPO_ROOT / "app" / "test" / "world" / "stylist.py"
CSS = '@font-face { font-family: "Lato"; font-weight: 400; font-style: normal; src: url(/fonts/Lato-Regular.ttf) format("truetype"); }'


def _answer(folder):
    done = subprocess.run([sys.executable, str(STAND_IN), str(folder)], capture_output=True, text=True,
                          env={"PYTHONPATH": str(REPO_ROOT / "src"), "PATH": ""})
    assert done.returncode == 0, done.stderr
    return style_build.blocks(done.stdout)


def _manifest():
    return templates.Manifest(fonts=["Lato-Regular.ttf"])


def test_a_cv_call_gets_a_template_and_a_sample_body_the_builder_accepts(tmp_path):
    (tmp_path / "fonts.css").write_text(CSS)
    got = _answer(tmp_path)
    assert set(got) == {"template", "body"}
    assert html_guard.template_problems(got["template"], _manifest()) == []
    assert html_guard.unsafe(got["body"]) == []


def test_a_letter_call_gets_a_letter_template_the_builder_accepts(tmp_path):
    (tmp_path / "fonts.css").write_text(CSS)
    (tmp_path / "default.cover-letter.template.html").write_text("x")
    got = _answer(tmp_path)
    assert set(got) == {"letter"}
    assert html_guard.template_problems(got["letter"], _manifest(), "letter") == []
