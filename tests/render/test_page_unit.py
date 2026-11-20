"""`render/page.py`: a body placed in a template's columns (#147), its photo and its print (#355)."""

from door.render import page


def test_a_heading_inside_the_header_stays_in_the_header_and_the_columns_start_after_it():
    """#242: a header with its own <h2> (a template's sample body may put CONTACT there) is not split: splitting at it
    left the columns inside the header, which the template places in its own grid area."""
    from door.core import templates
    body = ('<header class="cv-header"><h1>A B</h1><h2>Contact</h2><p class="contact">x</p></header>'
            '<h2 class="kind-experience">Experience</h2><p>e</p><h2 class="kind-skills">Skills</h2><p>s</p>')
    placed = page.place_columns(body, templates.Columns(side=["skills"]))
    head, rest = placed.split("</header>", 1)
    assert "<h2>Contact</h2>" in head and '<div class="main">' not in head
    assert rest == ('<div class="main"><h2 class="kind-experience">Experience</h2><p>e</p></div>'
                    '<div class="side"><h2 class="kind-skills">Skills</h2><p>s</p></div>')


_SECTIONS = ('<h2 class="kind-summary">Profil</h2><p>p</p><h2 class="kind-experience">Erfahrung</h2><p>e</p>'
             '<h2 class="kind-languages">Sprachen</h2><p>l</p><h2 class="kind-other">Hobbys</h2><p>o</p>')


def test_a_section_goes_to_the_side_by_its_kind_class_whatever_it_says():
    from door.core import templates
    placed = page.place_columns(_SECTIONS, templates.Columns(side=["languages", "interests"]))
    assert placed == ('<div class="main"><h2 class="kind-summary">Profil</h2><p>p</p>'
                      '<h2 class="kind-experience">Erfahrung</h2><p>e</p><h2 class="kind-other">Hobbys</h2><p>o</p></div>'
                      '<div class="side"><h2 class="kind-languages">Sprachen</h2><p>l</p></div>')


def test_a_section_with_no_kind_class_in_a_side_column_template_is_refused_in_words():
    import pytest

    from door.core import templates
    body = '<h2 class="kind-experience">Experience</h2><p>e</p><h2>Skills</h2><p>s</p>'
    with pytest.raises(ValueError, match="prepare it again or revise it"):
        page.place_columns(body, templates.Columns(side=["skills"]))


def test_a_body_is_left_as_it_is_when_the_template_has_no_side_column():
    from door.core import templates
    body = "<h2>Experience</h2><p>e</p><h2>Skills</h2><p>s</p>"
    assert page.place_columns(body, None) == body
    assert page.place_columns(body, templates.Columns()) == body


def _photo(tmp_path):
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (300, 400), "tan").save(buf, "JPEG")
    path = tmp_path / "photo.jpg"
    path.write_bytes(buf.getvalue())
    return path


def test_profile_photo_needs_a_photo_key_a_country_that_allows_one_and_a_usable_file(tmp_path):
    path = _photo(tmp_path)
    assert page.profile_photo({"location": "Denmark"}, {}) is None
    assert page.profile_photo({"photo": str(path), "location": "Denmark"}, {"location": "London, UK"}) is None
    assert page.profile_photo({"photo": str(path), "location": "Denmark"}, {}) == path
    assert page.profile_photo({"photo": str(tmp_path / "missing.jpg"), "location": "Denmark"}, {}) is None


def test_a_template_with_no_body_slot_cannot_hold_a_page():
    import pytest
    with pytest.raises(ValueError, match="<<body>>"):
        page._wrap("<html></html>", "<p>x</p>", "en")


def test_the_photo_token_is_dropped_when_the_template_does_not_style_a_photo(tmp_path):
    body, name = page._with_photo("<<photo>><p>x</p>", "<style>p { color: red }</style>", tmp_path, _photo(tmp_path))
    assert (body, name) == ("<p>x</p>", None)


def test_placed_cv_is_the_body_itself_when_the_manifest_cannot_be_read(monkeypatch):
    from door.core import templates

    def broken(path):
        raise ValueError("bad manifest")
    monkeypatch.setattr(templates, "manifest", broken)
    body = "<h2>Experience</h2><p>e</p><h2>Skills</h2><p>s</p>"
    assert page.placed_cv(body, {}) == body

