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
@pytest.mark.parametrize("dates", ["below", "same", "column"])
def test_headings_not_entry_titles(tmp_path, lang, upper, dates):
    want = [h.upper() if upper else h for h in LANG[lang][0]]
    got = _headings(tmp_path, lang=lang, upper=upper, dates=dates)
    # the last section's entries have no year nearby only in the limit case; here every entry is dated
    assert [g for g in got if g in want] == want
    assert not [g for g in got if g not in want]


def test_titles_larger_than_headings_are_not_returned(tmp_path):
    got = _headings(tmp_path, lang="de", hsize=10, tsize=12)
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
