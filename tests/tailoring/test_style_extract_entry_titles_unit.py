"""Headings vs entry titles (#320): bold body-size entry titles share the headings' style, in any language."""
import pytest

from door.tailoring import style_extract as se
from tests.pdf_utils import raw_pdf

LANG = {
    "en": (["Experience", "Education", "Skills", "Projects"], ["Senior Developer", "Team Lead", "Student Assistant", "Software Engineer"]),
    "de": (["Berufserfahrung", "Ausbildung", "Kenntnisse", "Projekte"], ["Senior Entwickler", "Teamleiter Technik", "Werkstudent Informatik", "Softwareingenieur"]),
    "es": (["Experiencia profesional", "Formacion academica", "Competencias", "Proyectos"], ["Ingeniero de software", "Jefe de equipo", "Becario de informatica", "Analista de datos"]),
    "it": (["Esperienze lavorative", "Istruzione e formazione", "Competenze", "Progetti"], ["Sviluppatore senior", "Responsabile tecnico", "Stagista informatico", "Analista dati"]),
    "pl": (["Doswiadczenie zawodowe", "Wyksztalcenie", "Umiejetnosci", "Projekty"], ["Starszy programista", "Kierownik zespolu", "Stazysta informatyk", "Analityk danych"]),
}


def _cv(lang, upper=False, dates="below", hsize=10, tsize=10, entries=(2, 2, 1, 2)):
    heads, titles = LANG[lang]
    ops, y = [], 800

    def t(font, size, x, yy, s):
        ops.append(f"BT 0 g /{font} {size} Tf {x} {yy} Td ({s}) Tj ET")

    t("F2", 18, 50, y, "Max Mustermann")
    y -= 26
    t("F1", 10, 50, y, "max@example.com  +49 30 1234567")
    y -= 36
    ti = 0
    for hi, h in enumerate(heads):
        t("F2", hsize, 50, y, h.upper() if upper else h)
        y -= 18
        for _ in range(entries[hi]):
            title = titles[ti % 4] + ", Firma AG"
            ti += 1
            if dates == "column":
                t("F1", 10, 50, y, "2019 - 2022")
                t("F2", tsize, 130, y, title)
            elif dates == "own":
                t("F2", tsize, 50, y, title + " 2019-2022")
            elif dates == "same":
                t("F2", tsize, 50, y, title)
                t("F1", 10, 400, y, "05/2019 - 2022")
            else:
                t("F2", tsize, 50, y, title)
                y -= 13
                t("F5", 10, 50, y, "2019 - 2022")
            y -= 14
            for _ in range(2):
                t("F1", 10, 60, y, "- Entwicklung und Betrieb von Diensten in der Cloud")
                y -= 13
            y -= 6
    return raw_pdf("\n".join(ops))


def _headings(tmp_path, **kw):
    path = tmp_path / "cv.pdf"
    path.write_bytes(_cv(**kw))
    return [h["text"] for h in se.extract(path)["headings"]]


@pytest.mark.parametrize("lang", list(LANG))
@pytest.mark.parametrize("upper", [False, True])
@pytest.mark.parametrize("dates", ["same", "column", "own"])
@pytest.mark.parametrize("tsize", [12, 14])
def test_dated_titles_set_larger_than_the_headings_are_not_the_headings(tmp_path, lang, upper, dates, tsize):
    want = [h.upper() if upper else h for h in LANG[lang][0]]
    assert _headings(tmp_path, lang=lang, upper=upper, dates=dates, hsize=10, tsize=tsize) == want


def test_titles_in_exactly_the_headings_style_come_with_them(tmp_path):
    # the limit: one style, undated headings among dated titles, nothing tells them apart
    assert set(LANG["de"][0]) <= set(_headings(tmp_path, lang="de", dates="same"))


def test_headings_only_group_is_kept(tmp_path):
    # no entry carries a year: nothing is an entry title, the bold group stays headings
    heads = ["Berufserfahrung", "Ausbildung", "Kenntnisse", "Interessen"]
    ops, y = ["BT 0 g /F2 18 Tf 50 810 Td (Max Mustermann) Tj ET"], 770
    for h in heads:
        ops.append(f"BT 0 g /F2 10 Tf 50 {y} Td ({h}) Tj ET")
        ops.append(f"BT 0 g /F1 10 Tf 50 {y - 14} Td (Ein Satz Text ohne Jahreszahl hier.) Tj ET")
        y -= 60
    path = tmp_path / "cv.pdf"
    path.write_bytes(raw_pdf("\n".join(ops)))
    assert [h["text"] for h in se.extract(path)["headings"]] == heads


def _plain(layout, gap, heads=("Berufserfahrung", "Ausbildung", "Kenntnisse", "Ehrenamt"), hfont="F2", line=None):
    """Bold headings, each with two blocks below it in the body font; `layout` says how a block starts."""
    ops, y = ["BT 0 g /F2 18 Tf 50 810 Td (Max Mustermann) Tj ET"], 770
    for i, h in enumerate(heads):
        ops.append(f"BT 0 g /{hfont} 11 Tf 50 {y} Td ({h}) Tj ET")
        if i < 3:  # an undated group of fewer lines than the headings: what the fallback takes if they count as dated
            ops.append(f"BT 0 g /F3 10 Tf 300 {y + 8} Td (Schwerpunkt Cloud) Tj ET")
        y -= gap
        for _ in range(2):
            if layout == "date_first":
                ops.append(f"BT 0 g /F1 10 Tf 50 {y} Td ({line or '2019 - 2022  Senior Entwickler bei Firma AG'}) Tj ET")
            elif layout == "date_above":
                ops.append(f"BT 0 g /F5 10 Tf 50 {y} Td ({line or '03/2019 - heute'}) Tj ET")
                y -= 13
                ops.append(f"BT 0 g /F2 10 Tf 50 {y} Td (Senior Entwickler, Firma AG) Tj ET")
            else:  # prose
                ops.append(f"BT 0 g /F1 10 Tf 50 {y} Td ({line}) Tj ET")
            y -= 14
            ops.append(f"BT 0 g /F1 10 Tf 60 {y} Td (- Entwicklung und Betrieb von Diensten in der Cloud) Tj ET")
            y -= 19
    return raw_pdf("\n".join(ops))


def _got(tmp_path, pdf):
    path = tmp_path / "x.pdf"
    path.write_bytes(pdf)
    return [h["text"] for h in se.extract(path)["headings"]]


@pytest.mark.parametrize("gap", [10, 12, 14, 18, 22])
@pytest.mark.parametrize("line", ["2019 - 2022  Senior Entwickler bei Firma AG", "03/2019 - heute  Senior Entwickler", "seit 2019 Senior Entwickler"])
def test_a_heading_over_a_line_with_a_year_stays_a_heading(tmp_path, gap, line):
    assert _got(tmp_path, _plain("date_first", gap, line=line)) == ["Berufserfahrung", "Ausbildung", "Kenntnisse", "Ehrenamt"]


@pytest.mark.parametrize("gap", [10, 14, 22])
@pytest.mark.parametrize("line", ["Seit 2015 in der Softwareentwicklung taetig.", "Microsoft Office 2019, Python"])
def test_prose_with_a_year_under_a_heading_changes_nothing(tmp_path, gap, line):
    assert _got(tmp_path, _plain("prose", gap, line=line)) == ["Berufserfahrung", "Ausbildung", "Kenntnisse", "Ehrenamt"]


@pytest.mark.parametrize("gap", [10, 14, 22])
def test_a_date_line_above_a_bold_title_keeps_the_headings(tmp_path, gap):
    got = _got(tmp_path, _plain("date_above", gap, line="2019 - 2022"))
    assert all(h in got for h in ["Berufserfahrung", "Ausbildung", "Kenntnisse", "Ehrenamt"])


HEADS = ["Berufserfahrung", "Ausbildung", "Kenntnisse", "Ehrenamt"]


def _heads(tmp_path, heads, side=None, color="0 g", size=11, rightdate=None, label=False):  # headings 11pt: larger than the 10pt label
    ops, y = ["BT 0 g /F2 18 Tf 50 810 Td (Max Mustermann) Tj ET"], 770
    for i, h in enumerate(heads):
        ops.append(f"BT {color} /F2 {size} Tf 50 {y} Td ({h}) Tj ET")
        if i < 3 and label:  # an undated group of fewer lines than the headings
            ops.append(f"BT 0 g /F3 10 Tf 160 {y + 8} Td (Schwerpunkt Cloud) Tj ET")
        if side:  # a side column: its first line is on the heading's baseline, then more lines under it
            ops.append(f"BT 0 g /F1 9 Tf 420 {y} Td ({side.format(i=i)}) Tj ET")
            for k in range(1, 5):
                ops.append(f"BT 0 g /F1 9 Tf 420 {y - 12 * k} Td (Zertifikat und Kurs) Tj ET")
        if rightdate:
            ops.append(f"BT 0 g /F1 10 Tf 450 {y} Td ({rightdate}) Tj ET")
        for k in range(3):
            ops.append(f"BT 0 g /F1 10 Tf 60 {y - 14 - 13 * k} Td (- Entwicklung und Betrieb von Diensten) Tj ET")
        y -= 80
    return _got(tmp_path, raw_pdf("\n".join(ops)))


def test_a_year_in_a_side_column_on_a_heading_baseline_keeps_the_heading(tmp_path):
    assert _heads(tmp_path, HEADS, side="Zertifikat AWS 201{i}", label=True) == HEADS


def test_headings_some_with_a_year_are_all_kept(tmp_path):
    heads = ["Berufserfahrung seit 2015", "Ausbildung", "Kenntnisse", "Projekte 2020"]
    assert _heads(tmp_path, heads) == heads


def test_all_dated_headings_in_a_coloured_larger_style_are_kept(tmp_path):
    heads = ["Berufserfahrung 2015-2024", "Ausbildung 2010-2015", "Projekte 2020", "Ehrenamt seit 2018"]
    assert _heads(tmp_path, heads, color="0.1 0.3 0.7 rg", size=13) == heads


def test_a_right_aligned_date_on_every_heading_row_keeps_them_when_coloured_and_larger(tmp_path):
    assert _heads(tmp_path, HEADS, color="0.1 0.3 0.7 rg", size=13, rightdate="2015 - 2024") == HEADS


@pytest.mark.parametrize("rightdate", [None, "2015 - 2024"])
def test_all_dated_headings_with_no_other_group_are_still_the_headings(tmp_path, rightdate):
    heads = ["Berufserfahrung 2015-2024", "Ausbildung 2010-2015", "Projekte 2020", "Ehrenamt seit 2018"]
    assert _heads(tmp_path, heads if rightdate is None else HEADS, rightdate=rightdate) == (heads if rightdate is None else HEADS)


def test_a_larger_all_dated_group_does_not_lose_to_a_group_of_more_lines(tmp_path):
    # 4 bold headings, each with a small year note at the right of its row (so all dated), and one Times line per
    # section: the largest group stays the headings unless an undated group has fewer lines
    ops, y = ["BT 0 g /F2 18 Tf 50 810 Td (Max Mustermann) Tj ET"], 770
    for i, h in enumerate(HEADS):
        ops.append(f"BT 0 g /F2 11 Tf 50 {y} Td ({h}) Tj ET")
        ops.append(f"BT 0 g /F1 8 Tf 480 {y} Td (seit 201{i}) Tj ET")
        for k in range(3):
            font, text = ("F3", "Schwerpunkt Cloud") if k == 0 else ("F1", "- Entwicklung und Betrieb von Diensten in der Cloud")
            ops.append(f"BT 0 g /{font} 10 Tf 60 {y - 16 - 13 * k} Td ({text}) Tj ET")
        y -= 70
    assert _got(tmp_path, raw_pdf("\n".join(ops))) == HEADS
