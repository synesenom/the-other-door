"""cv.md as a body (#204, #431): the deterministic twin of what the tailor writes, with no model, for the stress renders
and the previews of a built template. What the CV means comes from its reading (`core/cv_read`, here the made-up
`tests/cv_read_utils`), never from word lists. The result is in the tailor's closed vocabulary and the columns place it."""

import re
import sys

import pytest

from door.core import templates
from door.render import html_doc, html_guard, page
from door.style import cv_body
from paths import REPO_ROOT, TESTS_DIR

sys.path.insert(0, str(TESTS_DIR))
from cv_read_utils import reading  # noqa: E402

EXAMPLE = (REPO_ROOT / "profile.example" / "cv.md").read_text(encoding="utf-8")


def text_of(fragment: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", fragment)).strip()


def read_of(md: str, **replace) -> dict:
    return reading(md, **replace)


def make(md: str, **replace) -> str:
    return cv_body.body(md, read_of(md, **replace))


def entry(heading, role=None, org=None, dates=None, place=None):
    return {"heading": heading, "role": role, "org": org, "dates": dates, "place": place, "start_year": None, "end_year": None}


def test_the_example_cv_becomes_a_body_the_guard_accepts():
    out = make(EXAMPLE)
    assert html_guard.unsafe(out) == []
    assert html_doc.headings(out) == ["Profile", "Work Experience", "Education", "Skills", "Certifications", "Languages"]


def test_each_h2_carries_the_kind_of_the_reading_section_at_its_place_whatever_it_says():
    md = "## Profil\n\nx\n\n## Erfahrung\n\n### R | O\n\n## Hobbys\n\n- Chess\n"
    sections = [{"heading": "Profil", "kind": "summary"}, {"heading": "Erfahrung", "kind": "experience"},
                {"heading": "Hobbys", "kind": "interests"}]
    out = make(md, sections=sections)
    assert html_doc.kinds(out) == ["summary", "experience", "interests"]
    assert html_doc.headings(out) == ["Profil", "Erfahrung", "Hobbys"]
    assert html_guard.unsafe(out) == []


def test_the_header_has_the_photo_token_name_tagline_and_contact_kinds_in_order():
    out = make(EXAMPLE)
    header = re.search(r'<header class="cv-header">.*?</header>', out, re.S).group(0)
    assert header.startswith('<header class="cv-header"><<photo>><h1>Jane Doe</h1>')
    assert '<p class="tagline">Financial Controller | Group Reporting &amp; Process Improvement</p>' in header
    kinds = re.findall(r'<span class="(\w+)">', header)
    assert kinds == ["phone", "email", "web", "linkedin", "github", "location"]
    assert '<a href="mailto:jane.doe@example.com">jane.doe@example.com</a>' in header
    assert '<a href="https://www.linkedin.com/in/janedoe">www.linkedin.com/in/janedoe</a>' in header
    assert '<a href="https://janedoe.example.com">janedoe.example.com</a>' in header


def test_the_contacts_come_from_the_reading_in_the_templates_order_in_any_language():
    md = "# A\n\nSted: Aarhus | Tlf: +45 1\n\n## Erfaring\n"
    contacts = [{"kind": "location", "label": "Sted", "value": "Aarhus"}, {"kind": "phone", "label": "Tlf", "value": "+45 1"}]
    out = make(md, contacts=contacts, sections=[{"heading": "Erfaring", "kind": "experience"}])
    assert '<span class="phone">+45 1</span><span class="location">Aarhus</span>' in out
    assert cv_body.contact_labels({"contacts": contacts}) == {"location": "Sted:", "phone": "Tlf:"}


def test_only_the_readings_contacts_are_written_even_when_the_header_holds_more():
    md = "# A\n\nx@y.example | Born 1990\n\n## E\n"
    out = make(md, contacts=[], sections=[{"heading": "E", "kind": "other"}])
    assert "contact" not in out and "x@y.example" not in out and "Born" not in out
    contacts = [{"kind": "phone", "label": None, "value": "+45 1"}]
    assert '<p class="contact"><span class="phone">+45 1</span></p>' in make(md, contacts=contacts, sections=[{"heading": "E", "kind": "other"}])


def test_an_indented_section_line_is_no_section_so_the_kinds_keep_their_places():
    md = "## Skills\n\n  ## not a heading\n\n## Languages\n\nx\n"
    out = make(md)
    assert html_doc.kinds(out) == ["skills", "languages"] and "not a heading" in html_doc.text(out)


def test_a_label_that_the_reading_found_is_dropped_with_the_value_kept_once():
    md = "# A\n\n**Téléphone :** +33 1 | **Lieu :** Lyon\n\n## E\n"
    contacts = [{"kind": "phone", "label": "Téléphone", "value": "+33 1"}, {"kind": "location", "label": "Lieu", "value": "Lyon"}]
    out = make(md, contacts=contacts, sections=[{"heading": "E", "kind": "other"}])
    assert '<p class="contact"><span class="phone">+33 1</span><span class="location">Lyon</span></p>' in out


def test_an_entry_heading_is_written_in_the_readings_parts_and_reads_back_as_the_plain_heading():
    md = "## Experience\n\n### Senior Controller | Acme Corp — 2021 - present\n\n- Did a thing.\n"
    out = make(md, entries=[entry("Senior Controller | Acme Corp — 2021 - present", "Senior Controller", "Acme Corp", "2021 - present")])
    assert ('<div class="entry"><h3><span class="role">Senior Controller</span><span class="sep"> | </span>'
            '<span class="org">Acme Corp</span><span class="sep"> - </span><span class="dates">2021 - present</span></h3>') in out
    assert "<ul><li>Did a thing.</li></ul></div>" in out
    assert text_of(re.search(r"<h3>.*?</h3>", out).group(0)) == "Senior Controller | Acme Corp - 2021 - present"


def test_an_entry_may_name_a_place_and_skip_the_dates():
    md = "## Experience\n\n### Dev | Acme — 2020 | Aarhus\n\n### Dev | Acme | Aarhus\n"
    out = make(md, entries=[entry("Dev | Acme — 2020 | Aarhus", "Dev", "Acme", "2020", "Aarhus"),
                            entry("Dev | Acme | Aarhus", "Dev", "Acme", None, "Aarhus")])
    assert '<span class="dates">2020</span><span class="sep"> | </span><span class="place">Aarhus</span>' in out
    assert '<span class="org">Acme</span><span class="sep"> | </span><span class="place">Aarhus</span>' in out


def test_the_org_is_whatever_the_reading_says_not_what_a_dash_splits():
    md = "## Experience\n\n### Dev | Acme - Nordics\n"
    out = make(md, entries=[entry("Dev | Acme - Nordics", "Dev", "Acme - Nordics")])
    assert '<span class="org">Acme - Nordics</span></h3>' in out


def test_a_heading_the_reading_has_no_parts_for_is_a_role_alone():
    out = make("## Education\n\n### Self-taught developer\n")
    assert '<h3><span class="role">Self-taught developer</span></h3>' in out


def test_only_an_item_the_reading_lists_with_a_level_gets_a_level_class_and_keeps_its_word():
    md = ("## Languages\n\n- **Anglais** — courant\n- Danish (B1)\n- **French** — somewhat\n- **Skill** — expert\n"
          "- Plain item\n")
    levels = [{"item": "Anglais", "level": 4}, {"item": "Danish", "level": 2}, {"item": "French", "level": None}]
    out = make(md, levels=levels, sections=[{"heading": "Languages", "kind": "languages"}])
    assert '<li><strong>Anglais</strong> <span class="level level-4">courant</span></li>' in out
    assert '<li><strong>Danish</strong> <span class="level level-2">B1</span></li>' in out
    assert out.count("level-") == 2
    assert "<li><strong>French</strong> — somewhat</li>" in out and "<li>Plain item</li>" in out


def test_a_level_item_wrapped_onto_a_second_line_keeps_its_level():
    md = "## Languages\n\n- **Danish** —\n  conversational\n- English — native\n"
    levels = [{"item": "Danish", "level": 2}, {"item": "English", "level": 5}]
    out = make(md, levels=levels)
    assert '<span class="level level-2">conversational</span>' in out
    assert '<span class="level level-5">native</span>' in out
    assert out.count("<li>") == 2


def test_a_skills_paragraph_and_an_unknown_section_are_kept_as_text():
    out = make("## Skills\n\nPython, SQL\nand more\n\n## Publications\n\n- A study (2021)\n- Notes (2019)\n")
    assert '<h2 class="kind-skills">Skills</h2>\n<p>Python, SQL and more</p>' in out
    assert '<h2 class="kind-other">Publications</h2>\n<ul><li>A study (2021)</li><li>Notes (2019)</li></ul>' in out


def test_markdown_inline_and_unsafe_text_are_made_safe():
    out = make("## Profile\n\nI use **bold**, *italic* and [a site](https://ok.example), R&D <script>x</script>, "
               "[bad](javascript:alert(1)) and [plain](http://insecure.example).\n")
    assert html_guard.unsafe(out) == []
    assert "<strong>bold</strong>" in out and "<em>italic</em>" in out
    assert '<a href="https://ok.example">a site</a>' in out
    assert "R&amp;D &lt;script&gt;x&lt;/script&gt;" in out
    assert "javascript" not in out and "<p>I use" in out and out.count("<a ") == 1
    assert "plain" in out and "http://" not in out


def test_nothing_in_is_nothing_out_and_the_result_is_the_same_each_time():
    assert cv_body.body("", read_of("")) == ""
    assert cv_body.body("   \n\n", read_of("   \n\n")) == ""
    assert make(EXAMPLE) == make(EXAMPLE)


def test_the_columns_place_its_sections_by_their_kind_like_a_tailored_body():
    out = make(EXAMPLE)
    placed = page.place_columns(out, templates.Columns(side=["skills", "languages", "certifications"]))
    main, side = placed.split('<div class="side">')
    assert html_doc.headings(main) == ["Profile", "Work Experience", "Education"]
    assert html_doc.headings(side) == ["Skills", "Certifications", "Languages"]
    assert placed.startswith('<header class="cv-header">')


def test_headings_are_placed_by_kind_in_any_language():
    md = "# A\n\n## Expérience\n\n### R | O — 2020\n\n## Compétences\n\nPython\n"
    out = make(md, sections=[{"heading": "Expérience", "kind": "experience"}, {"heading": "Compétences", "kind": "skills"}])
    placed = page.place_columns(out, templates.Columns(side=["skills"]))
    assert html_doc.headings(placed.split('<div class="side">')[1]) == ["Compétences"]


def test_a_heading_named_as_a_side_heading_goes_to_the_side_whatever_it_says():
    out = ('<header></header><h2 class="kind-summary">Profil</h2><p>a</p><h2 class="kind-other">Savoir-être</h2><p>b</p>'
           '<h2 class="kind-other">LOGICIELS</h2><p>c</p>')
    placed = page.place_columns(out, templates.Columns(side=["skills"], headings=["savoir-être", "Logiciels"]))
    main, side = placed.split('<div class="side">')
    assert html_doc.headings(main) == ["Profil"]
    assert html_doc.headings(side) == ["Savoir-être", "LOGICIELS"]


def test_side_headings_alone_make_a_side_column_and_a_template_with_none_places_nothing():
    out = "<h2>Logiciels</h2><p>c</p>"
    assert page.place_columns(out, None) == out
    assert '<div class="side"><h2>Logiciels</h2>' in page.place_columns(out, templates.Columns(headings=["Logiciels"]))


def test_letter_header_is_the_name_and_contact_of_the_cv_in_the_letter_header_shape():
    md = "# Jane Doe\n\n> Analyst\n\n**Email:** jane@example.com | **Phone:** +45 1234 5678\n\n## Experience\n\n- x\n"
    header, name = cv_body.letter_header(md, read_of(md))
    assert name == "Jane Doe"
    assert header.startswith('<header class="letter-header"><h1>Jane Doe</h1>')
    assert '<span class="email"><a href="mailto:jane@example.com">' in header and "Analyst" not in header
    assert "Experience" not in header


def test_letter_header_of_a_cv_with_no_name_is_empty():
    md = "## Experience\n\n- x\n"
    assert cv_body.letter_header(md, read_of(md)) == ("", "")


def test_a_section_marker_is_no_heading_text():
    md = "## Toolbox <!-- kind: skills -->\n\n- **Danish** — native\n"
    out = make(md, levels=[{"item": "Danish", "level": 5}])
    assert '<h2 class="kind-other">Toolbox</h2>' in out
    assert "kind:" not in out and "level-5" in out


def test_a_cv_with_no_labels_has_none():
    assert cv_body.contact_labels({"contacts": [{"kind": "email", "label": None, "value": "a@b.c"}]}) == {}


def test_the_body_reads_no_word_list():
    source = (REPO_ROOT / "src" / "door" / "style" / "cv_body.py").read_text(encoding="utf-8")
    assert not re.search(r"^(?:from door import i18n|from door\.core import .*cv_sections)", source, re.M)
