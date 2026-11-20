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


# ---------- a built template (#204): the page a stylist writes around <<body>> ----------

import re  # noqa: E402

from door.core import templates  # noqa: E402
from paths import REPO_ROOT  # noqa: E402

_CV_COMMENT = ("cv-header contact tagline phone email web location linkedin github entry role org dates place sep level "
               "level-1 level-5 " + " ".join(f"kind-{k}" for k in cv_read.KINDS))
_LETTER_COMMENT = "letter-header contact phone email web location linkedin github recipient date closing signoff"
_MANIFEST = templates.Manifest(fonts=["Lato-Regular.ttf", "Lato-Bold.ttf"], icons={"phone": "phone.svg", "email": "mail.svg"})


def page(css="", head="", body="<<body>>", comment=_CV_COMMENT, lang="<<lang>>", cv=True):
    photo = ".photo { width: 2cm; }" if cv else ""
    return (f"<!doctype html>\n<!-- {comment} -->\n<html lang=\"{lang}\">\n<head>\n<meta charset=\"utf-8\">\n<title>CV</title>\n"
            f"{head}<style>\n@font-face {{ font-family: Lato; src: url(/fonts/Lato-Regular.ttf) format(\"truetype\"); }}\n"
            f"html {{ font-synthesis: none; }}\n{photo}\n{css}\n</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n")


def problems(html, kind="cv", manifest=_MANIFEST):
    return html_guard.template_problems(html, manifest, kind)


def test_a_plain_built_template_passes_as_a_cv_and_as_a_letter():
    assert problems(page()) == []
    assert problems(page(comment=_LETTER_COMMENT, cv=False), kind="letter") == []


@pytest.mark.parametrize("name,head", [
    ("<script>", "<script>alert(1)</script>"),
    ("<link>", '<link rel="stylesheet" href="https://evil.example/x.css">'),
    ("<iframe>", '<iframe src="about:blank"></iframe>'),
    ("<object>", '<object data="x"></object>'),
    ("<svg>", "<svg><circle r=1></circle></svg>"),
    ("<img>", '<img alt="x">'),
    ("<base>", '<base href="https://evil.example/">'),
    ("http-equiv", '<meta http-equiv="refresh" content="0;url=https://evil.example">'),
])
def test_a_template_with_a_forbidden_element_is_refused(name, head):
    assert any(name in p for p in problems(page(head=head)))


@pytest.mark.parametrize("attr", ['onload="x()"', 'ONCLICK="x()"', 'src="https://x"', 'href="https://x"', 'srcset="x"',
                                  'background="x.png"'])
def test_a_template_with_a_script_or_loading_attribute_is_refused(attr):
    assert problems(page(body=f"<div {attr}></div>\n<<body>>"))


@pytest.mark.parametrize("css", [
    '@import url("https://evil.example/x.css");', "@IMPORT 'x.css';", "@\\69mport 'x.css';",
    "a { background: url(https://evil.example/x.png); }", "a { background: url(data:image/png;base64,AAAA); }",
    "a { background: u\\72l(/fonts/Lato-Regular.ttf); }", "a { background: url(/fonts/Other.ttf); }",
    "a { background: url(/icons/web.svg); }", "a { background: url(/fonts/../secrets.ttf); }", "a { background: url(//evil.example/x); }",
    "a { background: image-set('x.png' 1x); }", "a { width: expression(alert(1)); }", "a { -moz-binding: url(x); }",
])
def test_css_that_loads_something_else_is_refused(css):
    assert problems(page(css=css))


def test_a_style_attribute_is_read_as_css_too():
    assert problems(page(body='<div style="background: url(https://evil.example/x)"></div>\n<<body>>'))
    assert problems(page(body='<div style="color: red"></div>\n<<body>>')) == []


def test_url_may_name_only_a_font_or_an_icon_the_manifest_lists():
    ok = ('a { background: url("/icons/phone.svg"); } b { background: url( \'/icons/mail.svg\' ); } '
          "@font-face { font-family: B; src: url(/fonts/Lato-Bold.ttf); }")
    assert problems(page(css=ok)) == []
    assert problems(page(css="a { background: url(/icons/phone.svg); }"), manifest=None)


def test_a_css_escape_is_refused_outside_a_string_but_a_content_string_may_have_one():
    assert problems(page(css='.c::after { content: "\\00B7"; }')) == []
    assert problems(page(css=".\\63 lass { color: red; }"))


@pytest.mark.parametrize("html", [
    page().replace("<<body>>", ""), page(body="<<body>>\n<<body>>"), page(lang="en"), page(lang="<<lang>><<lang>>"),
])
def test_exactly_one_body_and_one_lang_token(html):
    assert any("<<body>>" in p or "<<lang>>" in p for p in problems(html))


@pytest.mark.parametrize("html", [
    page(css="a::after { content: '<<body>>'; }").replace("<<body>>\n</body>", "x\n</body>"),
    page(body='<div title="<<body>>"></div>', css="").replace("<title>CV</title>", "<title><<body>></title>"),
])
def test_the_body_token_must_be_a_text_node_of_the_page(html):
    assert any("<<body>>" in p for p in problems(html))


def test_another_token_is_refused_because_the_body_owns_them():
    assert any("<<photo>>" in p for p in problems(page(body="<<photo>>\n<<body>>")))


def test_a_cv_template_needs_a_photo_rule_a_letter_does_not():
    no_photo = page(cv=False)
    assert any(".photo" in p for p in problems(no_photo))
    assert problems(no_photo.replace(_CV_COMMENT, _LETTER_COMMENT), kind="letter") == []


def test_font_synthesis_none_is_required():
    assert any("font-synthesis" in p for p in problems(page().replace("font-synthesis: none", "font-synthesis: weight")))


def test_the_header_comment_must_list_the_vocabulary_classes():
    assert any("comment" in p for p in problems(page(comment="my template")))
    found = [p for p in problems(page(comment=_CV_COMMENT.replace(" tagline", "").replace(" sep", "")))
             if "comment" in p]
    assert found and "tagline" in found[0] and "sep" in found[0]
    assert any("comment" in p for p in problems(page(comment=_LETTER_COMMENT), kind="cv"))
    assert any("comment" in p for p in problems("<!doctype html><html lang=\"<<lang>>\"><body><<body>></body></html>"))


def test_a_cv_template_header_comment_must_list_the_kind_classes_a_letter_one_need_not():
    found = [p for p in problems(page(comment=_CV_COMMENT.replace("kind-skills", ""))) if "comment" in p]
    assert found and "kind-skills" in found[0]
    assert problems(page(comment=_LETTER_COMMENT), kind="letter") == []


def test_a_word_of_a_class_is_not_the_class():
    assert any("sep" in p for p in problems(page(comment=_CV_COMMENT.replace(" sep", " separator"))))


def test_visible_text_outside_the_tokens_is_refused():
    assert any("Hello" in p for p in problems(page(body="<p>Hello</p>\n<<body>>")))
    assert any("Hello" in p for p in problems(page(body="Hello <<body>>")))
    assert problems(page(body="<header><div></div></header>\n<<body>>")) == []


def test_markup_a_browser_could_read_differently_is_refused():
    assert problems(page(head="<scr<script>ipt>x</script>"))
    assert problems(page(head="<!-- never closed"))
    assert problems(page(head="<?php x ?>"))


def test_the_shipped_templates_pass_with_the_fonts_they_serve():
    fonts = sorted(p.name for p in (REPO_ROOT / "profile.example" / "fonts").glob("*.ttf"))
    manifest = templates.Manifest(fonts=fonts)
    cv = (REPO_ROOT / "profile.example" / "cv.template.html").read_text(encoding="utf-8")
    letter = (REPO_ROOT / "profile.example" / "cover-letter.template.html").read_text(encoding="utf-8")
    assert html_guard.template_problems(cv, manifest, "cv") == []
    assert html_guard.template_problems(letter, manifest, "letter") == []
    assert html_guard.template_problems(letter, manifest, "cv")  # no .photo, and its comment is the letter's


def test_the_icons_a_fixture_template_draws_are_the_ones_its_manifest_lists():
    folder = REPO_ROOT / "tests" / "render" / "fixtures" / "icon_template"
    text = (folder / "cv.template.html").read_text(encoding="utf-8")
    assert not [p for p in html_guard.template_problems(text, templates.manifest(folder / "cv.template.html"), "cv") if "url(" in p]
    assert [p for p in html_guard.template_problems(text, None, "cv") if "url(" in p]


def test_every_problem_is_a_short_line_named_once():
    found = problems(page(head="<script></script><script></script>"))
    assert len(found) == len(set(found)) and all(isinstance(p, str) and len(p) < 200 for p in found)
    assert not [p for p in found if re.search(r"\n", p)]


# ---------- review fixes: baked-in text, unclosed url(, raw-text elements, messages ----------

@pytest.mark.parametrize("css", [
    '.x::after { content: "Jane Doe"; }', '.x::after { content: "\\4A ane"; }', '.x::after { content: "\\004A\\0061ne"; }',
    '@page { @top-center { content: "Jane"; } }', ".x::before { content: attr(data-x); }", '.x::before { content: "2019"; }',
    ".x::before { content: 'a'; }", '.x::before { content : counter(n) "Jane"; }',
    # an icon font's glyph or a stray mark printed where a dropped icon was (#248)
    '.web::before { content: "!"; }', '.web::before { content: "\\f0c1"; }', '.x::before { content: ""; }',
    '.x::before { content: "?"; }',
])
def test_text_baked_in_by_css_is_refused(css):
    assert problems(page(css=css))


@pytest.mark.parametrize("css", [
    '.x::before { content: "\\00B7"; }', '.x::before { content: "•"; }', '.x::before { content: ""; }',
    ".x::before { content: none; }", ".x::before { content: counter(item) \". \"; }", '.x::before { content: open-quote; }',
    '.x::before { content: "\\2014"; }', '@page { @bottom-center { content: counter(page) " / " counter(pages); } }',
])
def test_symbols_counters_and_quotes_in_css_content_pass(css):
    assert problems(page(css=css)) == []


def test_an_unclosed_url_is_refused():
    assert problems(page(css="a { background: url(https://evil.example/x.png; }"))
    assert problems(page(css='a { background: url("/fonts/Lato-Regular.ttf"; }'))


@pytest.mark.parametrize("tag", ["xmp", "template", "plaintext", "noembed", "noframes", "textarea"])
def test_raw_text_elements_around_the_body_token_are_refused(tag):
    assert any(f"<{tag}>" in p for p in problems(page(body=f"<{tag}><<body>></{tag}>")))


def test_an_attribute_or_meta_outside_the_allow_list_is_refused():
    assert problems(page(body='<div id="x"></div>\n<<body>>'))
    assert problems(page(head='<meta property="og:title" content="x">'))
    assert problems(page(head='<meta name="viewport" content="width=device-width">')) == []


@pytest.mark.parametrize("css,named", [
    ("a { background: image('x.png'); }", "image()"), ("a { background: image-set('x.png' 1x); }", "image-set()"),
])
def test_a_function_is_named_with_its_parentheses(css, named):
    assert named in problems(page(css=css))


# On the pinned Chromium, pdfium reads a word printed with letter-spacing above 0.1em as pieces ("Skil l s", "P r o f
# i l e") and two words printed tighter than -0.02em as one ("WORKEXPERIENCE", "ProfessionalProfile"): measured on
# Figtree, Young Serif, Lato, Arimo, Tinos, Carlito, Caladea and Cousine at 10 and 16 pt, the first split came at
# 0.11em, the first join at -0.03em (Young Serif; -0.04 to -0.06em for the others), whatever the size (#254).
@pytest.mark.parametrize("css", ["h2 { letter-spacing: 0.2em; }", "h2 { letter-spacing: .11em !important; }",
                                 "h2 { letter-spacing: 2pt; }", "h2 { letter-spacing: 1px; }", "h2 { letter-spacing: -0.5pt; }",
                                 "h2 { letter-spacing: -0.03em; }", "h2 { letter-spacing: -.06em; }",
                                 "h2 { letter-spacing: calc(0.05em + 1pt); }", "h2 { LETTER-SPACING: 0.3EM }"])
def test_letter_spacing_outside_the_range_pdfium_reads_back_or_not_in_em_is_refused(css):
    assert any("letter-spacing" in p and "-0.02em to 0.1em" in p for p in problems(page(css=css)))


@pytest.mark.parametrize("css", ["h2 { letter-spacing: 0.1em; }", "h2 { letter-spacing: .05em; }", "h2 { letter-spacing: 0; }",
                                 "h2 { letter-spacing: normal; }", "h2 { letter-spacing: -0.02em; }", "h2 { letter-spacing: 0pt; }"])
def test_letter_spacing_from_minus_two_hundredths_to_a_tenth_of_an_em_passes(css):
    assert problems(page(css=css)) == []


def test_inter_character_justification_is_refused():
    # a loose justified line is widened between its letters: pdfium reads them apart as for a wide letter-spacing
    assert any("text-justify" in p for p in problems(page(css="p { text-align: justify; text-justify: inter-character; }")))
    assert problems(page(css="p { text-align: justify; text-justify: inter-word; }")) == []


def test_letter_spacing_in_a_style_attribute_is_read_too():
    assert any("letter-spacing" in p for p in problems(page(body='<div style="letter-spacing: 0.3em"></div>\n<<body>>')))
