"""The shipped fonts are TrueType: Chromium writes a CFF (.otf) font into a PDF as nameless Type 3 text."""

from door.core import workspace

_FONTS = workspace.PROFILE_EXAMPLE_DIR / "fonts"
_FILES = [
    "Figtree-Regular.ttf", "Figtree-Italic.ttf", "Figtree-SemiBold.ttf", "Figtree-SemiBoldItalic.ttf",
    "YoungSerif-Regular.ttf",
]


def test_the_five_fonts_are_truetype():
    for name in _FILES:
        data = (_FONTS / name).read_bytes()
        assert data[:4] == b"\x00\x01\x00\x00", name
        assert b"glyf" in data[:2048] and b"CFF " not in data[:2048], name


def test_each_family_keeps_its_licence_and_no_otf_is_left():
    assert (_FONTS / "Figtree-OFL.txt").is_file() and (_FONTS / "YoungSerif-OFL.txt").is_file()
    assert not list(_FONTS.glob("*.otf"))
