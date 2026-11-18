"""`render/page.py`: a body placed in a template's columns (#147), its photo and its print (#355)."""

from door.render import page


def test_a_heading_inside_the_header_stays_in_the_header_and_the_columns_start_after_it():
    """#242: a header with its own <h2> (a built style's sample body put CONTACT there) is not split: splitting at it
    left the columns inside the header, which the template places in its own grid area."""
    from door.core import templates
    body = ('<header class="cv-header"><h1>A B</h1><h2>Contact</h2><p class="contact">x</p></header>'
            "<h2>Experience</h2><p>e</p><h2>Skills</h2><p>s</p>")
    placed = page.place_columns(body, templates.Columns(side=["skills"]))
    head, rest = placed.split("</header>", 1)
    assert "<h2>Contact</h2>" in head and '<div class="main">' not in head
    assert rest == '<div class="main"><h2>Experience</h2><p>e</p></div><div class="side"><h2>Skills</h2><p>s</p></div>'


def _photo(tmp_path):
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (300, 400), "tan").save(buf, "JPEG")
    path = tmp_path / "photo.jpg"
    path.write_bytes(buf.getvalue())
    return path


def test_profile_photo_needs_a_photo_key_a_country_that_allows_one_and_a_usable_file(tmp_path):
    from door import i18n
    path = _photo(tmp_path)
    assert page.profile_photo({}, i18n.CvConventions(photo="optional")) is None
    assert page.profile_photo({"photo": str(path)}, i18n.CvConventions(photo="no")) is None
    assert page.profile_photo({"photo": str(path)}, i18n.CvConventions(photo="optional")) == path
    assert page.profile_photo({"photo": str(tmp_path / "missing.jpg")}, i18n.CvConventions(photo="optional")) is None


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
