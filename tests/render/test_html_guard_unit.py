"""A prepared cv.html / cover_letter.html is a body fragment in a closed vocabulary (#146): it never loads another
file, reaches the network or runs anything. It is model output, steered by a job ad or an instruction from a phone,
and a real browser prints it. The guard is an allow-list; compile refuses to build a body that it names anything in."""

import pytest

from door.core import cv_read
from door.render import html_guard

CV = """<!-- Keywords: IFRS, budgeting -->
<!-- Tailoring: led with the close -->
<<photo>>
<header class="cv-header"><h1>Ada Lovelace</h1>
<p class="contact"><span>+45 1</span><span><a href="mailto:ada@example.com">ada@example.com</a></span>
<span><a href="https://ada.dev">ada.dev</a></span></p></header>
<h2>Experience</h2>
<div class="entry"><h3>Controller | Acme &mdash; 2021 - present</h3>
<ul><li>Cut the close by <strong>40%</strong> &amp; saved <em>time</em><br>twice.</li></ul></div>
<p><a href="#top">top</a></p>
"""
LETTER = """<header class="letter-header"><h1>Ada</h1><p class="contact"><span>x</span></p></header>
<div class="recipient"><p>Hiring team</p><p>Acme</p></div><p class="date"><<date>></p>
<p>Dear team,</p><p>I would like the <<title>> role at <<company>>.</p>
<div class="closing"><p class="signoff">Kind regards,</p><p>Ada</p></div>"""


KINDS = ("phone", "email", "web", "location", "linkedin", "github")


def test_a_header_with_a_tagline_and_a_kind_on_each_contact_span_passes():
    spans = "".join(f'<span class="{k}">x</span>' for k in KINDS)
    body = f'<header class="cv-header"><h1>Ada</h1><p class="tagline">Controller | Reporting</p><p class="contact">{spans}</p></header>'
    assert html_guard.unsafe(body) == []


def test_an_unknown_kind_class_is_refused():
    assert html_guard.unsafe('<p class="contact"><span class="fax">x</span></p>') != []


@pytest.mark.parametrize("kind", cv_read.KINDS)
def test_each_section_kind_is_a_class_of_an_h2(kind):
    assert html_guard.unsafe(f'<h2 class="kind-{kind}">Anything</h2>') == []


@pytest.mark.parametrize("snippet", [
    '<div class="kind-skills">x</div>', '<span class="kind-skills">x</span>', '<p class="kind-skills">x</p>',
    '<h3 class="kind-skills">x</h3>', '<h2 class="kind-bogus">x</h2>', '<h2 class="kind-skills main">x</h2>',
])
def test_a_kind_class_is_only_for_an_h2_and_only_a_known_kind(snippet):
    assert html_guard.unsafe(snippet) != []


def test_an_ordinary_cv_and_letter_pass():
    assert html_guard.unsafe(CV) == []
    assert html_guard.unsafe(LETTER) == []


@pytest.mark.parametrize("snippet", [
    "<script>alert(1)</script>", "<SCRIPT>alert(1)</SCRIPT>", "scr<script>ipt", "<p onclick=\"x()\">a</p>",
    "<p ONCLICK='x()'>a</p>", "<p style=\"background:url(file:///etc/passwd)\">a</p>",
    "<style>@import 'http://evil/x.css';</style>", "<img src=\"file:///etc/passwd\">",
    "<svg><use xlink:href=\"file:///etc/passwd\"></use></svg>", "<iframe src=\"file:///etc/passwd\"></iframe>",
    "<object data=\"x\"></object>", "<embed src=\"x\">", "<link rel=\"stylesheet\" href=\"http://evil/x.css\">",
    "<meta http-equiv=\"refresh\" content=\"0;url=http://evil\">", "<base href=\"http://evil/\">",
    "<form action=\"http://evil\"><input name=a></form>", "<button>x</button>", "<video src=\"x\"></video>",
    "<a href=\"javascript:alert(1)\">x</a>", "<a href=\"&#106;avascript:alert(1)\">x</a>",
    "<a href=\"JaVa&#x73;cript:alert(1)\">x</a>", "<a href=\" \tjavascript:alert(1)\">x</a>",
    "<a href=\"data:text/html,x\">x</a>", "<a href=\"file:///etc/passwd\">x</a>", "<a href=\"../secret.pdf\">x</a>",
    "<a href=\"photo.jpg\">x</a>", "<a href=\"http://insecure.example\">x</a>", "<a href=\"//evil.example/x\">x</a>",
    "<a href=\"https://x/<b\">x</a>", "<a href=\"https://x\" target=\"_blank\">x</a>", "<p src=\"x\">a</p>",
    "<marquee>x</marquee>", "<p class=\"evil\">x</p>", "<p class=\"entry evil\">x</p>", "<p class=\"photo\">x</p>",
    "<!-- anything else -->", "<!-- Keywords: a --!><script>x</script> -->", "<!DOCTYPE html>", "<![CDATA[x]]>",
    "<?xml version=\"1.0\"?>", "<!-- Keywords: never closed", "<a href>x</a>", "<math><mi>x</mi></math>",
])
def test_anything_outside_the_vocabulary_is_named(snippet):
    assert html_guard.unsafe(CV + snippet), snippet


def test_allowed_links_pass():
    for href in ("mailto:ada@example.com", "https://ada.dev/a?b=c#d", "#experience", "HTTPS://ada.dev"):
        assert html_guard.unsafe(f'<p><a href="{href}">x</a></p>') == [], href


def test_a_refusal_is_named_once():
    found = html_guard.unsafe("<script>a</script><script>b</script><p onclick='x'>c</p><p onclick='y'>d</p>")
    assert len(found) == len(set(found)) and "<script>" in found
    assert any("onclick" in name for name in found)


def test_an_unclosed_or_stray_tag_is_not_a_way_in():
    assert html_guard.unsafe("<p>text <scr")
    assert html_guard.unsafe("a < b and c > d") == []


ENTRY = ('<div class="entry"><h3><span class="role">Controller</span><span class="sep"> | </span><span class="org">Acme</span>'
         '<span class="sep"> - </span><span class="dates">2021 - present</span><span class="sep"> | </span>'
         '<span class="place">Aarhus</span></h3></div>')


def test_an_entry_heading_with_role_org_dates_place_and_separators_passes():
    assert html_guard.unsafe(ENTRY) == []


def test_a_skill_level_class_one_to_five_passes():
    body = "".join(f'<ul><li><strong>Danish</strong> <span class="level level-{n}">level</span></li></ul>' for n in range(1, 6))
    assert html_guard.unsafe(body) == []


@pytest.mark.parametrize("cls", ["level level-6", "level-0", "main", "side", "level level-10"])
def test_a_level_beyond_five_or_a_column_class_is_refused(cls):
    assert html_guard.unsafe(f'<div class="{cls}">x</div>') != []
