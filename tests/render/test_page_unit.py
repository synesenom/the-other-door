"""`render/page.py`: a body's photo and its print (#355)."""

from door.render import page


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


def test_a_style_goes_right_before_the_head_closes_and_none_changes_nothing():
    template = '<html lang="<<lang>>"><head><style>a{}</style></head><body><<body>></body></html>'
    plain = page._wrap(template, "<p>x</p>", "en")
    assert page._wrap(template, "<p>x</p>", "en", "") == plain
    styled = page._wrap(template, "<p>x</p>", "en", ":root{--rule:#000}")
    assert styled == plain.replace("</head>", "<style>:root{--rule:#000}</style></head>")


def test_print_page_hands_the_style_to_the_page_it_prints(tmp_path, monkeypatch):
    from door.render import html_pdf
    seen = {}
    monkeypatch.setattr(html_pdf, "print_html", lambda folder, html, pdf, **kw: seen.update(html=html))
    template = "<html><head></head><body><<body>></body></html>"
    page.print_page("<p>x</p>", template, "en", tmp_path, "cv", style=":root{--rule:#000}")
    assert "<style>:root{--rule:#000}</style></head>" in seen["html"]
