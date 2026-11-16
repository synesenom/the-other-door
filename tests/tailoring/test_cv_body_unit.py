"""cv.md as a body (#204): the deterministic twin of what the tailor writes, with no model, for the stress renders and
the previews of a built template. The result is in the tailor's closed vocabulary and the columns place it."""

import re

import pytest

from door import i18n
from door.commands import compile as compile_cmd
from door.core import templates
from door.tailoring import cv_body, html_doc, html_guard
from paths import REPO_ROOT

EXAMPLE = (REPO_ROOT / "profile.example" / "cv.md").read_text(encoding="utf-8")


def text_of(fragment: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", fragment)).strip()


def test_the_example_cv_becomes_a_body_the_guard_accepts():
    out = cv_body.body(EXAMPLE, "en")
    assert html_guard.unsafe(out) == []
    assert html_doc.headings(out) == ["Profile", "Work Experience", "Education", "Skills", "Certifications", "Languages"]


def test_the_header_has_the_photo_token_name_tagline_and_contact_kinds_in_order():
    out = cv_body.body(EXAMPLE, "en")
    header = re.search(r'<header class="cv-header">.*?</header>', out, re.S).group(0)
    assert header.startswith('<header class="cv-header"><<photo>><h1>Jane Doe</h1>')
    assert '<p class="tagline">Financial Controller | Group Reporting &amp; Process Improvement</p>' in header
    kinds = re.findall(r'<span class="(\w+)">', header)
    assert kinds == ["phone", "email", "web", "linkedin", "github", "location"]
    assert '<a href="mailto:jane.doe@example.com">jane.doe@example.com</a>' in header
    assert '<a href="https://www.linkedin.com/in/janedoe">www.linkedin.com/in/janedoe</a>' in header
    assert '<a href="https://janedoe.example.com">janedoe.example.com</a>' in header


def test_an_entry_heading_is_written_in_parts_and_reads_back_as_the_plain_heading():
    out = cv_body.body("## Experience\n\n### Senior Controller | Acme Corp — 2021 - present\n\n- Did a thing.\n", "en")
    assert ('<div class="entry"><h3><span class="role">Senior Controller</span><span class="sep"> | </span>'
            '<span class="org">Acme Corp</span><span class="sep"> - </span><span class="dates">2021 - present</span></h3>') in out
    assert "<ul><li>Did a thing.</li></ul></div>" in out
    assert text_of(re.search(r"<h3>.*?</h3>", out).group(0)) == "Senior Controller | Acme Corp - 2021 - present"


def test_an_entry_may_name_a_place():
    out = cv_body.body("## Experience\n\n### Dev | Acme — 2020 | Aarhus\n", "en")
    assert '<span class="dates">2020</span><span class="sep"> | </span><span class="place">Aarhus</span>' in out


def test_a_heading_with_no_pipe_is_a_role_and_a_hyphen_splits_dates_only_before_a_number():
    plain = cv_body.body("## Education\n\n### Self-taught developer\n", "en")
    assert '<h3><span class="role">Self-taught developer</span></h3>' in plain
    hyphen = cv_body.body("## Experience\n\n### Dev | Acme - Nordics\n\n### Dev | Acme - 2019\n", "en")
    assert '<span class="org">Acme - Nordics</span></h3>' in hyphen
    assert '<span class="org">Acme</span><span class="sep"> - </span><span class="dates">2019</span>' in hyphen


def test_a_level_word_becomes_a_level_class_and_stays_in_the_text():
    out = cv_body.body(EXAMPLE, "en")
    assert '<li><strong>English</strong> <span class="level level-4">fluent</span></li>' in out
    assert '<li><strong>Danish</strong> <span class="level level-2">conversational</span></li>' in out


@pytest.mark.parametrize("word,number", [("native", 5), ("C2", 5), ("Professional", 4), ("C1", 4), ("working", 3), ("B2", 3),
                                         ("B1", 2), ("basic", 1), ("A2", 1)])
def test_the_levels_follow_the_tailors_table(word, number):
    out = cv_body.body(f"## Languages\n\n- **French** — {word}\n", "en")
    assert f'<span class="level level-{number}">{word}</span>' in out


def test_a_word_that_is_not_a_level_and_an_item_outside_skills_and_languages_get_no_level_class():
    assert "level" not in cv_body.body("## Languages\n\n- **French** — somewhat\n", "en")
    assert "level" not in cv_body.body("## Certifications\n\n- **CMA** — fluent\n", "en")


def test_levels_are_read_in_the_headings_of_the_ads_language():
    assert 'level-5' in cv_body.body("## Langues\n\n- **Anglais** — native\n", "fr")


def test_a_skills_paragraph_and_an_unknown_section_are_kept_as_text():
    out = cv_body.body("## Skills\n\nPython, SQL\nand more\n\n## Publications\n\n- A study (2021)\n- Notes (2019)\n", "en")
    assert "<h2>Skills</h2>\n<p>Python, SQL and more</p>" in out
    assert "<h2>Publications</h2>\n<ul><li>A study (2021)</li><li>Notes (2019)</li></ul>" in out


def test_markdown_inline_and_unsafe_text_are_made_safe():
    out = cv_body.body("## Profile\n\nI use **bold**, *italic* and [a site](https://ok.example), R&D <script>x</script>, "
                       "[bad](javascript:alert(1)) and [plain](http://insecure.example).\n", "en")
    assert html_guard.unsafe(out) == []
    assert "<strong>bold</strong>" in out and "<em>italic</em>" in out
    assert '<a href="https://ok.example">a site</a>' in out
    assert "R&amp;D &lt;script&gt;x&lt;/script&gt;" in out
    assert "javascript" not in out and "<p>I use" in out and out.count("<a ") == 1
    assert "plain" in out and "http://" not in out


def test_a_contact_detail_with_no_label_is_an_email_or_a_plain_span():
    out = cv_body.body("# A\n\nx@y.example | Born 1990\n", "en")
    assert '<span class="email"><a href="mailto:x@y.example">x@y.example</a></span><span>Born 1990</span>' in out


def test_contact_labels_in_french():
    out = cv_body.body("# A\n\n**Téléphone :** +33 1 | **Lieu :** Lyon\n", "fr")
    assert '<span class="phone">+33 1</span><span class="location">Lyon</span>' in out


def test_nothing_in_is_nothing_out_and_the_result_is_the_same_each_time():
    assert cv_body.body("", "en") == ""
    assert cv_body.body("   \n\n", "en") == ""
    assert cv_body.body(EXAMPLE, "en") == cv_body.body(EXAMPLE, "en")


def test_the_columns_place_its_sections_like_a_tailored_body():
    out = cv_body.body(EXAMPLE, "en")
    placed = compile_cmd._place_columns(out, templates.Columns(side=["skills", "languages", "certifications"]))
    main, side = placed.split('<div class="side">')
    assert html_doc.headings(main) == ["Profile", "Work Experience", "Education"]
    assert html_doc.headings(side) == ["Skills", "Certifications", "Languages"]
    assert placed.startswith('<header class="cv-header">')


def test_headings_are_placed_in_any_supported_language():
    out = cv_body.body("# A\n\n## Expérience\n\n### R | O — 2020\n\n## Compétences\n\nPython\n", "fr")
    placed = compile_cmd._place_columns(out, templates.Columns(side=["skills"]))
    assert html_doc.headings(placed.split('<div class="side">')[1]) == ["Compétences"]


def test_every_section_kind_the_i18n_reads_is_the_one_the_columns_use():
    assert i18n.cv_section_kind("Languages", ("languages",), ("en",)) == "languages"


# ---------- review fixes ----------

def entry_parts(heading):
    out = cv_body.body(f"## Experience\n\n### {heading}\n", "en")
    return {c: text_of(m) for c, m in re.findall(r'<span class="(role|org|dates|place)">(.*?)</span>', out)}


@pytest.mark.parametrize("heading,expected", [
    ("Controller | Big Bank — 2018 - 2021", {"role": "Controller", "org": "Big Bank", "dates": "2018 - 2021"}),
    ("Analyst | Acme — Jan 2018 – Mar 2021", {"role": "Analyst", "org": "Acme", "dates": "Jan 2018 – Mar 2021"}),
    ("Analyst | Acme — 2018 - 2021 | Aarhus", {"role": "Analyst", "org": "Acme", "dates": "2018 - 2021", "place": "Aarhus"}),
    ("Analyst | Acme - 2018 - 2021", {"role": "Analyst", "org": "Acme", "dates": "2018 - 2021"}),
])
def test_the_dates_split_off_at_the_first_dash_not_the_last(heading, expected):
    assert entry_parts(heading) == expected


def test_the_example_cvs_entry_with_a_range_keeps_its_org_whole():
    heading = next(ln[4:] for ln in EXAMPLE.splitlines() if ln.startswith("### ") and "Big Bank" in ln)
    assert entry_parts(heading)["org"].startswith("Big Bank") and "20" not in entry_parts(heading)["org"]


def test_a_level_item_wrapped_onto_a_second_line_keeps_its_level():
    out = cv_body.body("## Languages\n\n- **Danish** —\n  conversational\n- English — native\n", "en")
    assert '<span class="level level-2">conversational</span>' in out
    assert '<span class="level level-5">native</span>' in out
    assert out.count("<li>") == 2


def test_contact_labels_of_every_supported_language_name_their_kind():
    for label, kind in [("Hjemmeside", "web"), ("Weboldal", "web"), ("Helyszín", "location"), ("Telefon", "phone"),
                        ("E-post", "email"), ("Webbplats", "web"), ("Ort", "location"), ("Courriel", "email")]:
        assert i18n.contact_kind(label) == kind


def test_letter_header_is_the_name_and_contact_of_the_cv_in_the_letter_header_shape():
    md = "# Jane Doe\n\n> Analyst\n\n**Email:** jane@example.com | **Phone:** +45 1234 5678\n\n## Experience\n\n- x\n"
    header, name = cv_body.letter_header(md)
    assert name == "Jane Doe"
    assert header.startswith('<header class="letter-header"><h1>Jane Doe</h1>')
    assert '<span class="email"><a href="mailto:jane@example.com">' in header and "Analyst" not in header
    assert "Experience" not in header


def test_letter_header_of_a_cv_with_no_name_is_empty():
    assert cv_body.letter_header("## Experience\n\n- x\n") == ("", "")
