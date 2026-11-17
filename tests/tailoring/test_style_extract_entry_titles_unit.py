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
@pytest.mark.parametrize("dates", ["same", "column"])
def test_headings_not_entry_titles(tmp_path, lang, upper, dates):
    want = [h.upper() if upper else h for h in LANG[lang][0]]
    got = _headings(tmp_path, lang=lang, upper=upper, dates=dates)
    assert [g for g in got if g in want] == want
    assert not [g for g in got if g not in want]


def test_titles_larger_than_headings_are_not_returned(tmp_path):
    got = _headings(tmp_path, lang="de", hsize=10, tsize=12, dates="same")
    assert not any("Firma AG" in g for g in got)


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
    for h in heads:
        ops.append(f"BT 0 g /{hfont} 10 Tf 50 {y} Td ({h}) Tj ET")
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


def test_a_known_heading_over_a_dated_line_stays(tmp_path):
    # English names are known; the bold titles dated on their own line are the entry titles
    heads = ["Experience", "Education", "Skills", "Projects"]
    ops, y = ["BT 0 g /F2 18 Tf 50 810 Td (Max Mustermann) Tj ET"], 770
    for h in heads:
        ops.append(f"BT 0 g /F2 10 Tf 50 {y} Td ({h}) Tj ET")
        y -= 14
        for title in ("Developer 2019 - 2022", "Team Lead 2022 - 2024"):
            ops.append(f"BT 0 g /F2 10 Tf 50 {y} Td ({title}) Tj ET")
            ops.append(f"BT 0 g /F1 10 Tf 60 {y - 14} Td (- Development and operation of cloud services for customers) Tj ET")
            y -= 34
        y -= 6
    assert _got(tmp_path, raw_pdf("\n".join(ops))) == heads
