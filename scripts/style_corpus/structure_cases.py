"""Made-up CVs whose structure a rule gets wrong (#343, epic #342), written by hand as PDFs: entry titles set in the
headings' own style, headings in capitals in the body font, headings with a year, a CV of three columns, a designed
CV with a "Page N of M" footer. `CASES` is name to ``(pdf bytes, headings, columns)``; `scripts/make_style_corpus.py`
writes each into `tests/tailoring/fixtures/styles/`, where `structure/<name>.json` is the model's recorded answer
for it. Everything is made up: fake names, `example.com` addresses."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.pdf_utils import raw_pdf  # noqa: E402

LANG = {
    "en": (["Experience", "Education", "Skills", "Projects"], ["Senior Developer", "Team Lead", "Student Assistant", "Software Engineer"]),
    "de": (["Berufserfahrung", "Ausbildung", "Kenntnisse", "Projekte"], ["Senior Entwickler", "Teamleiter Technik", "Werkstudent Informatik", "Softwareingenieur"]),
    "es": (["Experiencia profesional", "Formacion academica", "Competencias", "Proyectos"], ["Ingeniero de software", "Jefe de equipo", "Becario de informatica", "Analista de datos"]),
    "it": (["Esperienze lavorative", "Istruzione e formazione", "Competenze", "Progetti"], ["Sviluppatore senior", "Responsabile tecnico", "Stagista informatico", "Analista dati"]),
    "pl": (["Doswiadczenie zawodowe", "Wyksztalcenie", "Umiejetnosci", "Projekty"], ["Starszy programista", "Kierownik zespolu", "Stazysta informatyk", "Analityk danych"]),
}


def cv(lang, upper=False, dates="below", hsize=10, tsize=10, entries=(2, 2, 1, 2)):
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


def t(ops, f, s, x, y, txt, col="0 g"):
    ops.append(f"BT {col} /{f} {s} Tf {x} {y} Td ({txt}) Tj ET")

BODY = "- Entwicklung und Betrieb von Diensten in der Cloud"

def yearhead(heads, hsize=10):
    ops = []; t(ops, "F2", 18, 50, 810, "Max Mustermann"); t(ops, "F1", 10, 50, 792, "max@example.com  +49 30 1234567"); y = 760
    for h in heads:
        t(ops, "F2", hsize, 50, y, h); yy = y - 14
        for _ in range(3):
            t(ops, "F1", 10, 60, yy, BODY); yy -= 13
        y -= 70
    return raw_pdf("\n".join(ops))

def twocol(side_text):
    ops = []; t(ops, "F2", 18, 50, 810, "Max Mustermann"); y = 770
    for i, h in enumerate(["Berufserfahrung", "Ausbildung", "Kenntnisse", "Ehrenamt"]):
        t(ops, "F2", 10, 50, y, h); t(ops, "F1", 9, 400, y, side_text.format(i=i)); yy = y - 14
        for _ in range(3):
            t(ops, "F1", 10, 60, yy, BODY); yy -= 13
        y -= 80
    return raw_pdf("\n".join(ops))

def threecol():
    ops = []; t(ops, "F2", 20, 30, 810, "Anna Schmidt"); t(ops, "F1", 10, 30, 792, "anna@example.com | +49 151 2345678")
    cols = [(30, ["Kontakt", "Sprachen"], ["Berlin", "anna@example.com", "+49 151 2345678", "Deutsch", "Englisch"]),
            (215, ["Berufserfahrung", "Projekte"], ["Leiterin Daten, Nordbank 2019-2024", "Analystin, Firma AG 2015-2019", "Aufbau der Datenplattform", "Berichte fuer den Vorstand"]),
            (400, ["Ausbildung", "Kenntnisse"], ["MSc Statistik 2013-2015", "BSc Mathematik 2010-2013", "Python, SQL, R", "Tableau"])]
    for x, heads, lines in cols:
        y = 760
        for h in heads:
            t(ops, "F2", 11, x, y, h, "0.1 0.3 0.6 rg"); y -= 16
            for ln in lines:
                t(ops, "F1", 9, x, y, ln); y -= 12
            y -= 20
    return raw_pdf("\n".join(ops))

DE = LANG["de"][0]
CASES = {
    "de-titles-same-style": (cv("de", dates="same"), DE, 1),
    "de-titles-same-style-date-below": (cv("de", dates="below"), DE, 1),
    "es-titles-same-style": (cv("es", dates="same"), LANG["es"][0], 1),
    "en-titles-same-style": (cv("en", dates="same"), LANG["en"][0], 1),
    "de-titles-larger": (cv("de", dates="same", tsize=12), DE, 1),
    "de-titles-larger-own-year": (cv("de", dates="own", tsize=12), DE, 1),
    "de-heads-some-years": (yearhead(["Berufserfahrung seit 2015", "Ausbildung", "Kenntnisse", "Projekte 2020"]),
                            ["Berufserfahrung seit 2015", "Ausbildung", "Kenntnisse", "Projekte 2020"], 1),
    "de-heads-all-years": (yearhead(["Berufserfahrung 2015-2024", "Ausbildung 2010-2015", "Projekte 2020", "Ehrenamt seit 2018"]),
                           ["Berufserfahrung 2015-2024", "Ausbildung 2010-2015", "Projekte 2020", "Ehrenamt seit 2018"], 1),
    "de-side-year-on-heading-row": (twocol("Zertifikat AWS 201{i}"), ["Berufserfahrung", "Ausbildung", "Kenntnisse", "Ehrenamt"], None),
    "de-three-columns": (threecol(), ["Kontakt", "Sprachen", "Berufserfahrung", "Projekte", "Ausbildung", "Kenntnisse"], 3),
}


def caps_body_headings():
    ops = []; t(ops, "F2", 18, 50, 810, "Max Mustermann"); t(ops, "F1", 10, 50, 792, "max@example.com  +49 30 1234567"); y = 755
    for h, n in [("BERUFSERFAHRUNG", 3), ("AUSBILDUNG", 2), ("EHRENAMT", 1), ("KENNTNISSE", 0)]:
        t(ops, "F1", 10, 50, y, h); y -= 18
        for i in range(n):
            t(ops, "F2", 10, 50, y, f"Entwickler, Firma {i} GmbH"); t(ops, "F1", 10, 450, y, f"201{i} - 202{i}"); y -= 13
            for _ in range(2):
                t(ops, "F1", 10, 60, y, BODY); y -= 13
            y -= 6
        if n == 0:
            t(ops, "F1", 10, 50, y, "Python, Go, Kubernetes, Terraform, PostgreSQL"); y -= 13
        y -= 14
    return raw_pdf("\n".join(ops))


def long_two_pages():
    heads = ["Berufserfahrung", "Projekte", "Ausbildung", "Weiterbildung", "Ehrenamt", "Kenntnisse"]
    pages, ops, y = [], [], 800
    t(ops, "F2", 18, 50, y, "Max Mustermann"); y -= 40
    k = 0
    for h in heads:
        if y < 200:
            pages.append("\n".join(ops)); ops, y = [], 800
        t(ops, "F2", 10, 50, y, h); y -= 18
        for i in range(4):
            if y < 80:
                pages.append("\n".join(ops)); ops, y = [], 800
            k += 1
            t(ops, "F2", 10, 50, y, f"Senior Entwickler, Firma {k} AG"); t(ops, "F1", 10, 450, y, f"0{i+1}/201{i} - 202{i}"); y -= 13
            for _ in range(3):
                t(ops, "F1", 10, 60, y, BODY); y -= 13
            y -= 6
        y -= 10
    pages.append("\n".join(ops))
    return raw_pdf(pages), heads


def designed_with_page_footer():
    pages = []
    for p in (1, 2):
        ops = []
        if p == 1:
            t(ops, "F2", 22, 50, 800, "Jane Doe", "0.6 0.1 0.1 rg"); t(ops, "F1", 10, 50, 780, "jane@example.com  +45 1234 5678")
        y = 740 if p == 1 else 800
        for h in (["Experience", "Education"] if p == 1 else ["Languages", "Certifications"]):
            t(ops, "F2", 13, 50, y, h.upper(), "0.6 0.1 0.1 rg"); y -= 18
            for i in range(3):
                t(ops, "F2", 10, 50, y, f"Data Engineer, Acme {i}"); t(ops, "F5", 10, 450, y, f"201{i} - 202{i}"); y -= 13
                for _ in range(3):
                    t(ops, "F1", 10, 60, y, "Built pipelines and dashboards for the finance team"); y -= 13
                y -= 6
            y -= 12
        t(ops, "F1", 8, 270, 30, f"Page {p} of 2")
        pages.append("\n".join(ops))
    return raw_pdf(pages)


_long, _lh = long_two_pages()
CASES.update({
    "de-caps-headings-in-body-font": (caps_body_headings(), ["BERUFSERFAHRUNG", "AUSBILDUNG", "EHRENAMT", "KENNTNISSE"], 1),
    "de-long-two-pages-same-style": (_long, _lh, 1),
    "en-designed-with-page-footer": (designed_with_page_footer(), ["EXPERIENCE", "EDUCATION", "LANGUAGES", "CERTIFICATIONS"], 1),
})
