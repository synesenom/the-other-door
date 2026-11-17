"""#310: the extracted style does not depend on the process's hash seed."""
import json
import os
import subprocess
import sys

from door.style import style_extract

from tests.paths import REPO_ROOT, TESTS_DIR

PDF = TESTS_DIR / "style" / "fixtures" / "styles" / "html-canva-icons.pdf"


def _heading(color, rule, band="main"):
    return {"size": 11.0, "color": color, "weight": 600, "family": "F", "case": "upper", "italic": False, "rule": rule,
            "band": band}


def test_heading_style_tie_goes_to_the_first_style_met():
    rule = {"color": "#fff", "width": 0.8, "gap": 2.8, "span": "column"}
    a = [_heading("#e8625a", None)] * 3 + [_heading("#ffffff", rule)] * 3
    assert style_extract.heading_style(a)["color"] == "#e8625a"
    assert style_extract.heading_style(a)["rule"] is None
    assert style_extract.heading_style(a[::-1])["color"] == "#ffffff"


def test_a_tie_goes_to_the_main_column_headings_over_a_side_band_s():
    # white headings ruled on a coloured side band tie with the main column's: the page's heading look is the main one
    rule = {"color": "#fff", "width": 0.8, "gap": 2.8, "span": "column"}
    side_first = [_heading("#ffffff", rule, "side")] * 3 + [_heading("#e8625a", None)] * 3
    assert style_extract.heading_style(side_first)["color"] == "#e8625a"
    assert style_extract.heading_style(side_first)["rule"] is None


def test_the_text_colour_tie_goes_to_the_colour_met_first_under_every_seed():
    code = ("from door.style import style_extract as s;"
            "print(s.colors([{'color': '#222222', 'text': 'ab'}, {'color': '#e8625a', 'text': 'cd'}], [])['text'])")
    outs = set()
    for seed in ("0", "1", "2", "3", "4", "5"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(REPO_ROOT / "src")}
        outs.add(subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                                check=True).stdout.strip())
    assert outs == {"#222222"}


def test_extract_is_the_same_under_every_hash_seed():
    code = ("import json,sys;from door.style import style_extract as s;"
            "print(json.dumps(s.extract(sys.argv[1]),sort_keys=True,default=str))")
    outs = set()
    for seed in ("0", "1", "2", "3"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(REPO_ROOT / "src")}
        outs.add(subprocess.run([sys.executable, "-c", code, str(PDF)], env=env, capture_output=True, text=True,
                                check=True).stdout)
    assert len(outs) == 1
