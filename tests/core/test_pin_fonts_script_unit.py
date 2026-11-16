"""scripts/pin_fonts.py (#199): the parts that need no network, on a font the repo ships."""

import importlib.util

from paths import REPO_ROOT

from door.core import fonts, workspace

_spec = importlib.util.spec_from_file_location("pin_fonts", REPO_ROOT / "scripts" / "pin_fonts.py")
pin_fonts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pin_fonts)


def test_a_font_is_measured_in_em_fractions_with_an_advance_per_character():
    m = pin_fonts.measure_font(workspace.PROFILE_EXAMPLE_DIR / "fonts" / "Figtree-Regular.ttf")
    assert 0.45 < m["x_height"] < 0.55 and 0.65 < m["cap_height"] < 0.75 and 0.03 < m["stem"] < 0.15
    assert len(m["advance"]) == len(fonts.ADVANCE_CHARS)
    assert m["advance"][fonts.ADVANCE_CHARS.index(" ")] < m["advance"][fonts.ADVANCE_CHARS.index("m")]


def test_weights_and_italics_are_read_off_the_file_names():
    assert pin_fonts.weight_italic("Lato-BoldItalic.ttf") == (700, True)
    assert pin_fonts.weight_italic("PT_Sans-Web-Regular.ttf") == (400, False)
    assert pin_fonts.weight_italic("Lato-Black.ttf") == (900, False)


def test_every_alias_the_script_writes_is_in_normal_form_and_a_listed_family():
    listed = {name for name, _, _ in pin_fonts.FAMILIES}
    for target, names in pin_fonts.ALIASES.items():
        assert target in listed
        assert all(n == fonts.key(n) for n in names)
