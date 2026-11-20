"""`render/cv_body.py`: a `cv.md` as a body in the tailor's vocabulary, no model (#431, #465)."""

from cv_read_utils import plain
from door.render import cv_body, html_guard

CV = """# Jane Doe
> Finance lead

**Email:** jane@example.com | **Web:** https://jane.example

## Experience

### Head of Finance, Globex 2020 - 2023
- Cut <close> time by 30%
- See [report](https://example.com/r) and [bad](javascript:alert(1))

## Skills

IFRS, SQL
"""


def _body():
    return cv_body.body(CV, plain(CV))


def test_the_cv_is_a_body_in_the_building_blocks():
    out = _body()
    assert out.startswith('<header class="cv-header"><<photo>><h1>Jane Doe</h1>\n<p class="tagline">Finance lead</p>')
    assert '<span class="email"><a href="mailto:jane@example.com">' in out
    assert '<h2 class="kind-experience">Experience</h2>' in out and '<h2 class="kind-skills">Skills</h2>' in out
    assert '<div class="entry"><h3>' in out and "<ul><li>Cut &lt;close&gt; time by 30%</li>" in out


def test_only_https_mailto_and_fragment_links_are_kept():
    out = _body()
    assert '<a href="https://example.com/r">report</a>' in out and "javascript" not in out.replace("bad", "")


def test_the_body_passes_the_guard():
    assert not html_guard.unsafe(_body().replace("<<photo>>", ""))
