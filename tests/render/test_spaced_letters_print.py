"""Letters printed apart (#267), really printed by the pinned Chromium: CSS that spaces text so wide that pdfium reads
it as single letters ("P r o f i l e") is a `spaced` read-back problem, whatever spaced it; text spaced within reason,
initials and one-letter words read clean. Marked `real_chromium` like test_template_print.py."""

import os

import pytest

from door.core.downloads import chromium
from door.render import html_pdf, readability

pytestmark = [
    pytest.mark.real_chromium,
    pytest.mark.skipif(chromium.find_chromium() is None and not os.environ.get("CI"),
                       reason="no Chromium headless shell installed"),
]

BODY = ("<h1>Jane Doe</h1><h2>Profile</h2><p>Engineer with ten years in energy markets.</p>"
        "<h2>Experience</h2><p>Lead analyst at Globex.</p>")


def _found(tmp_path, css, body=BODY):
    pdf = tmp_path / "cv.pdf"
    html_pdf.print_html(tmp_path, f"<!doctype html><meta charset=utf-8><style>{css}</style><body>{body}</body>", pdf)
    return readability.check_pdf(pdf, body, "Jane Doe", cv=True)


@pytest.mark.parametrize("css", [
    # a parent's spacing inherited as a fixed length by smaller text
    "body{font-size:26pt;letter-spacing:0.1em} h1,h2,p{font-size:7pt}",
    "h2{font-size:14pt;letter-spacing:.1em} h2 span{font-size:8pt}",
    # a loosely filled justified line spread per character
    "p{width:300px;font-size:9pt;text-align:justify;text-align-last:justify;text-justify:inter-character}",
], ids=["inherited", "inherited-by-a-span", "justified-per-character"])
def test_text_printed_letter_by_letter_is_spaced(tmp_path, css):
    body = BODY.replace("<h2>Profile</h2>", "<h2><span>Profile</span></h2>")
    assert "spaced" in [p["kind"] for p in _found(tmp_path, css, body)]


def test_spacing_within_reason_initials_and_one_letter_words_read_clean(tmp_path):
    body = (BODY + "<p>J. K. Rowling, A team of 5. Il y a à faire. Ez a s az ő munkája.</p>"
            "<ul><li>a</li><li>b</li><li>c</li></ul>")
    assert _found(tmp_path, "h2{letter-spacing:.08em;text-transform:uppercase} p{text-align:justify}", body) == []
