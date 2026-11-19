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


def test_the_style_s_contact_labels_are_written_in_the_contact_spans_of_their_kinds_only():
    body = ('<header class="cv-header"><h1>A</h1><p class="contact"><span class="phone">12</span>'
            '<span class="email"><a href="mailto:a@b.c">a@b.c</a></span><span class="location">X</span></p></header>')
    out = page._with_labels(body, {"phone": "Tel:", "email": "<b>"})
    assert '<span class="phone"><label class="label">Tel:</label> 12</span>' in out
    assert '<span class="email"><label class="label">&lt;b&gt;</label> <a ' in out
    assert '<span class="location">X</span>' in out
    assert page._with_labels(body, {}) == body
