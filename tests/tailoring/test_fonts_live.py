"""The pinned fonts for real (#199): one file fetched from the pinned google/fonts commit matches its sha256, and
every stand-in prints through the real Chromium shell under its own name, embedded and not as nameless Type 3
text. Skipped where the network or the shell is not there."""

from __future__ import annotations

import pypdfium2 as pdfium
import pypdfium2.raw as raw
import pytest

from door.core import chromium, fonts
from door.tailoring.html_pdf import PrintError, print_html
from live_utils import not_reached

pytestmark = pytest.mark.live

# CSS family -> the base names the printed PDF must have for it (regular, then bold)
_STAND_INS = {
    "Carlito": ["Carlito-Regular", "Carlito-Bold"], "Caladea": ["Caladea-Regular", "Caladea-Bold"],
    "Arimo": ["Arimo-Regular", "Arimo-Bold"], "Tinos": ["Tinos-Regular", "Tinos-Bold"],
    "Cousine": ["Cousine-Regular", "Cousine-Bold"], "Lato": ["Lato-Regular", "Lato-Bold"],
    "Young Serif": ["YoungSerif-Regular"],
}


def _entry(family: str, weight: int) -> dict:
    return {"font": f"{family}-x", "family": family, "weight": weight, "italic": False, "serif": False, "fixed": False,
            "embedded": True, "icon": False, "type3": False, "runs": 1, "chars": 10}


def test_a_family_is_fetched_from_the_pin_and_matches_its_checksum(tmp_path):
    plan = fonts.plan([_entry("Young Serif", 400)])
    try:
        [path] = fonts.fetch(plan, tmp_path)
    except fonts.FontsError as exc:
        if "checksum" in str(exc):
            raise
        not_reached("raw.githubusercontent.com", str(exc))
    assert path.name == "YoungSerif-Regular.ttf" and path.stat().st_size == plan[0]["files"][0]["size"]
    assert (tmp_path / "YoungSerif-OFL.txt").is_file()


def test_each_stand_in_prints_under_its_own_name(tmp_path):
    if chromium.find_chromium() is None:
        pytest.skip("no Chromium headless shell installed (./door doctor --fix)")
    plan = fonts.plan([_entry(f, w) for f in _STAND_INS for w in (400, 700)])
    try:
        files = fonts.fetch(plan, tmp_path / "fonts")
    except fonts.FontsError as exc:
        not_reached("raw.githubusercontent.com", str(exc))
    faces = "".join(
        f"@font-face {{ font-family: '{e['family']}'; src: url('/fonts/{f['name']}'); "
        f"font-weight: {f['weight']}; font-style: {'italic' if f['italic'] else 'normal'} }}\n"
        for e in plan for f in e["files"])
    # bold only where the family has a bold file: the browser would fake one, as nameless text
    body = "".join(f"<p style=\"font-family: '{e['family']}'\">{e['family']} regular "
                   f"{'<b>and bold</b>' if len(e['files']) > 1 else ''}</p>" for e in plan)
    html = f"<!doctype html><html><head><meta charset='utf-8'><style>{faces}</style></head><body>{body}</body></html>"
    (tmp_path / "work").mkdir()
    out = tmp_path / "out.pdf"
    try:
        print_html(tmp_path / "work", html, out, assets={"fonts": files})
    except PrintError as exc:
        not_reached("chromium", str(exc))
    doc = pdfium.PdfDocument(str(out))
    try:
        names = {obj.get_font().get_base_name().split("+", 1)[-1]
                 for page in doc for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_TEXT])}
    finally:
        doc.close()
    assert "" not in names, "a font printed as nameless Type 3 text"
    expected = {name for names_ in _STAND_INS.values() for name in names_}
    assert expected <= names, expected - names
