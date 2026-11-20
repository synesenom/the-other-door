"""One reading of a cv.html / cover_letter.html body for readability, facts, revise and the show tool (#146)."""

from door.render import html_doc

BODY = """<!-- Keywords: IFRS, budgeting & forecasting -->
<!-- Tailoring: led with the close -->
<<photo>>
<header class="cv-header"><h1>Ada Lovelace</h1><p class="contact"><span>+45 1</span><span>Copenhagen</span></p></header>
<h2>Work <em>experience</em></h2>
<div class="entry"><h3>Controller | Acme &mdash; 2021</h3><ul><li>Cut the close by <strong>40%</strong> &amp; more.</li>
<li>Second<br>line&nbsp;here</li></ul></div>
<h2>R&amp;D</h2><p>Text</p>
"""


def test_headings_are_the_h2_texts_in_order():
    assert html_doc.headings(BODY) == ["Work experience", "R&D"]


def test_a_note_is_the_text_after_its_label_or_none():
    assert html_doc.note(BODY, "Keywords") == "IFRS, budgeting & forecasting"
    assert html_doc.note(BODY, "Tailoring") == "led with the close"
    assert html_doc.note("<p>x</p>", "Keywords") is None
    assert html_doc.keywords(BODY) == ["IFRS", "budgeting & forecasting"]
    assert html_doc.keywords("<p>x</p>") == []


def test_text_drops_tags_and_comments_and_decodes_entities():
    text = html_doc.text(BODY)
    assert "Keywords" not in text and "<" not in text and "photo" not in text
    assert "Cut the close by 40% & more." in text
    assert "Controller | Acme — 2021" in text
    assert "Second\nline here" in text


def test_each_block_is_a_line_of_its_own():
    lines = html_doc.text("<h2>A</h2><p>b</p><div><p>c</p><p>d</p></div><ul><li>e</li><li>f</li></ul>").splitlines()
    assert [line for line in lines if line] == ["A", "b", "c", "d", "e", "f"]


def test_word_count_counts_the_words_of_the_text_only():
    assert html_doc.word_count("<!-- Keywords: a b c --><p>Dear <strong>team</strong>, I'd like 2 roles.</p>") == 6


CLAIMS = """<header class="cv-header"><h1>Jane 5500</h1><p class="contact"><span>+45 12 34 56 78</span></p></header>
<h2>Experience</h2><div class="entry"><h3>Dev | Acme A/S &mdash; 2019</h3><ul><li>Cut churn by 40%.</li></ul></div>
<h2>Skills</h2><p>Python, SQL</p>
<div class="recipient"><p>Hiring 9000</p></div><p class="date">16 November 2026</p>
<div class="closing"><p class="signoff">Regards</p><p>Jane</p></div>"""


def test_h3_texts_are_the_entry_headings():
    assert html_doc.h3s(CLAIMS) == ["Dev | Acme A/S \u2014 2019"]


# --- the tagline and the contact kinds (#189) ---------------------------------------------------------------------

KINDED = """<header class="cv-header"><h1>Ada Lovelace</h1><p class="tagline">Analyst | Engines</p>
<p class="contact"><span class="phone">+45 1</span><span class="linkedin"><a href="https://www.linkedin.com/in/ada">LinkedIn</a></span>
<span class="location">Copenhagen</span></p></header>
<h2>Work experience</h2><p>Ran the engine room.</p>"""


def test_the_tagline_and_the_kinded_details_read_in_order():
    text = html_doc.text(KINDED)
    assert text.index("Ada Lovelace") < text.index("Analyst | Engines") < text.index("+45 1") < text.index("LinkedIn")
    assert html_doc.headings(KINDED) == ["Work experience"]


SPANS = ('<h3><span class="role">Role</span><span class="sep"> | </span><span class="org">Company</span>'
         '<span class="sep"> - </span><span class="dates">2021 - present</span><span class="sep"> | </span>'
         '<span class="place">City</span></h3>')


def test_a_span_structured_entry_heading_reads_as_the_plain_one():
    assert html_doc.h3s(SPANS) == ["Role | Company - 2021 - present | City"]
    assert html_doc.h3s(SPANS) == html_doc.h3s("<h3>Role | Company - 2021 - present | City</h3>")


def test_a_level_item_keeps_its_word_in_the_text():
    body = '<h2>Languages</h2><ul><li><strong>Danish</strong> <span class="level level-5">native</span></li></ul>'
    assert "Danish native" in html_doc.text(body)



def test_kinds_reads_the_kind_class_of_each_h2_or_none():
    body = '<h2 class="kind-skills">Skills</h2><p>s</p><h2>Other</h2><h2 class="kind-other x">Hobbys</h2>'
    assert html_doc.kinds(body) == ["skills", None, "other"]
