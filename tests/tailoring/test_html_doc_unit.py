"""One reading of a cv.html / cover_letter.html body for readability, facts, revise and the show tool (#146)."""

from door.tailoring import html_doc

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
