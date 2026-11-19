"""Spike of #429 (epic #428): how well does a small model read a CV and check a tailored CV's facts?

Measures Haiku, then Sonnet, on made-up data only (never a real CV): a *reader* task (cv.md in, what the CV says out:
section kinds, contacts, skill and language levels, name, email, city, country, working languages, role years, the
parts of each entry heading) and a *facts* task (a source cv.md and a tailored CV body with fabrications planted in
it; the model lists the claims the source does not back). Ground truth is built in: the corpus is generated from
made-up people, so every expected value is a literal of the text. The rules of today (`facts.check`, `cv_body.header`,
`_heading3`) are scored on the same cases as the baseline. A miss becomes a made-up prompt example, never a rule in
Python.

    poetry run python scripts/record_cv_reading.py --write-fixtures
    poetry run python scripts/record_cv_reading.py --task reader|facts --model haiku|sonnet [--runs 3] [--version N]
    poetry run python scripts/record_cv_reading.py --task report --model haiku|sonnet|baseline [--version N]

Result (made-up data, 15 CVs x 3 runs for the reader, 28 bodies x 3 runs for the fact check): Haiku is go on both
tasks with the prompts of round 2 (reader) and round 3 (facts), `CHOSEN_MODEL`; Sonnet is go too, a little less stable on
the facts. `FINAL_VERSION` names the rounds `test_record_cv_reading_unit.py` pins; the earlier rounds' answers stay
recorded beside them (`v1` is the prompt with no example).
`--version` picks a prompt round: `EXAMPLES` holds each made-up example with the round that added it.

Answers are recorded under `tests/tailoring/fixtures/cv_reading/recorded/<model>/<task>/v<version>/<case>.<run>.json`
(raw, so the scoring unit test reads them offline). Calls go through `claude_cli.ask` on the local claude's plan (never
an API key); the usage feature keys are `infer_basics` (the reader) and `revise` (the fact check), the nearest
existing ones: this spike adds none.
"""

from __future__ import annotations

import html
import json
import re

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from door.render import html_doc  # noqa: E402
from door.style import cv_body  # noqa: E402
from door.tailoring import facts  # noqa: E402


def _n(value) -> str:
    """A text for comparison: case, spacing and the kind of dash do not matter."""
    text = re.sub(r"[‐-―−]", "-", str(value or ""))
    text = re.sub(r"\s*-\s*", "-", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


# --- scoring the reader -----------------------------------------------------------------------------------------

READER_FIELDS = ("sections", "contacts", "levels", "name", "email", "city", "country", "languages", "years",
                 "heading_role", "heading_org", "heading_dates", "heading_place")
_WORKING = {"native", "fluent", "working"}


def _empty() -> dict:
    return {f: {"hit": 0, "total": 0} for f in READER_FIELDS}


def _count(score: dict, field: str, ok: bool) -> None:
    score[field]["total"] += 1
    score[field]["hit"] += bool(ok)


def score_reader(expected: dict, answer: dict) -> dict:
    """Per field, how many of the expected values the model's `answer` read right: `{field: {hit, total}}`. An answer
    that is an error misses everything."""
    answer = {} if not isinstance(answer, dict) or "error" in answer else answer
    score = _empty()
    for field in ("name", "email", "city", "country"):
        _count(score, field, answer.get(field) is not None and
               (str(answer[field]).strip() == str(expected[field]) if field in ("name", "email")
                else _n(answer[field]) == _n(expected[field])))
    kinds = {_n(s.get("heading")): s.get("kind") for s in answer.get("sections") or [] if isinstance(s, dict)}
    for heading, kind in expected["sections"].items():
        _count(score, "sections", kinds.get(_n(heading)) == kind)
    contacts = [c for c in answer.get("contacts") or [] if isinstance(c, dict)]
    for c in expected["contacts"]:
        _count(score, "contacts", any(
            a.get("kind") == c["kind"] and _n(a.get("label")) == _n(c["label"]) and _n(a.get("value")) == _n(c["value"])
            for a in contacts))
    levels = {_n(i.get("item")): i.get("level") for i in answer.get("levels") or [] if isinstance(i, dict)}
    for item, level in expected["levels"].items():
        _count(score, "levels", levels.get(_n(item)) == level)
    working = {l.get("language") for l in answer.get("languages") or []
               if isinstance(l, dict) and str(l.get("level")).lower() in _WORKING}
    _count(score, "languages", working == set(expected["working_languages"]))
    entries = {_n(e.get("heading")): e for e in answer.get("entries") or [] if isinstance(e, dict)}
    for want in expected["entries"]:
        got = entries.get(_n(want["heading"]), {})
        _count(score, "years", got.get("start_year") == want["start_year"])
        _count(score, "years", got.get("end_year") == want["end_year"])
        for part in ("role", "org", "dates", "place"):
            _count(score, f"heading_{part}", _n(got.get(part)) == _n(want[part]))
    return score


# --- scoring the facts check ------------------------------------------------------------------------------------

KINDS = ("number", "year", "employer", "skill", "certification", "degree")


def _val(value) -> str:
    """A claimed value for comparison: ``1,8 M kr`` and ``1.8M kr`` are one."""
    return re.sub(r"\s+", "", _n(value)).replace(",", ".")


def is_verbatim(quote: str, body_html: str) -> bool:
    """The quote is a stretch of the body's text (spacing squashed, as `facts` squashes it)."""
    quote = facts._squash(quote or "")
    return bool(quote) and quote in facts._squash(html_doc.text(body_html))


def _findings(answer) -> list[dict]:
    return [f for f in answer if isinstance(f, dict)] if isinstance(answer, list) else []


def _matches(plant: dict, found: dict) -> bool:
    if found.get("kind") != plant["kind"]:
        return False
    context = _val(found.get("context"))
    return (_val(found.get("value")) == _val(plant["planted_value"]) or _val(plant["planted_value"]) in context
            or _val(plant["quote"]) in context)


def score_facts(plants: list[dict], findings, body_html: str) -> dict:
    """One body's reading: `per_kind` {kind: {planted, found}} for the kinds planted, `false_flags` (findings that
    match no plant), `verbatim` (findings whose context is in the body, of all findings). An error answer finds nothing."""
    found = _findings(findings)
    per_kind: dict = {}
    for plant in plants:
        cell = per_kind.setdefault(plant["kind"], {"planted": 0, "found": 0})
        cell["planted"] += 1
        cell["found"] += any(_matches(plant, f) for f in found)
    false = sum(not any(_matches(p, f) for p in plants) for f in found)
    return {"per_kind": per_kind, "false_flags": false,
            "verbatim": (sum(is_verbatim(f.get("context"), body_html) for f in found), len(found))}


def stability(runs: dict) -> float:
    """The share of bodies whose set of (kind, value) flags is the same in every run (`runs`: case to each run's findings)."""
    same = [len({frozenset((f.get("kind"), _val(f.get("value"))) for f in _findings(r)) for r in rs}) == 1
            for rs in runs.values()]
    return sum(same) / len(same) if same else 0.0


# --- the go thresholds of #429 ----------------------------------------------------------------------------------

FACTS_GO = {"recall": 0.90, "false_clean_max": 1, "verbatim": 0.98, "stable": 0.95}
FACTS_NO_GO = {"recall": 0.80, "false_clean_max": 2}
READER_GO = {"sections": 0.98, "contacts": 0.98, "name": 1.0, "email": 1.0, "years": 0.95}
READER_NO_GO = 0.80


def facts_verdict(report: dict) -> str:
    """`go`, `no-go` or `close` for a facts report: `per_kind` recall, `false_clean_max` (most false flags on a clean
    body), `verbatim` and `stable` shares."""
    recalls = list(report["per_kind"].values())
    if min(recalls) < FACTS_NO_GO["recall"] or report["false_clean_max"] > FACTS_NO_GO["false_clean_max"]:
        return "no-go"
    ok = (min(recalls) >= FACTS_GO["recall"] and report["false_clean_max"] <= FACTS_GO["false_clean_max"]
          and report["verbatim"] >= FACTS_GO["verbatim"] and report["stable"] >= FACTS_GO["stable"])
    return "go" if ok else "close"


def reader_verdict(report: dict) -> str:
    """`go`, `no-go` or `close` for a reader report (a share per gated field)."""
    if any(report[f] < READER_NO_GO for f in READER_GO):
        return "no-go"
    return "go" if all(report[f] >= t for f, t in READER_GO.items()) else "close"


# --- the made-up people -----------------------------------------------------------------------------------------
# Everything below is invented: names, employers, schools, figures. Each language has its own pools, so a CV reads as
# one written there (headings, contact labels, level words, month names). The pools of what a plant invents are apart
# from the ones a CV is made of, so a planted employer, skill, degree or certification is never in the source.

LANG_PATTERN = ("da", "fr", "en", "da", "fr", "hu", "da", "fr", "sv", "en")
ENGLISH_NAME = {"en": "English", "da": "Danish", "fr": "French", "hu": "Hungarian", "sv": "Swedish", "de": "German"}
LEVEL_NUMBER = {"native": 5, "fluent": 4, "working": 3, "conversational": 2, "basic": 1}
CEFR = {"fluent": "C1", "working": "B2", "conversational": "B1", "basic": "A2"}
_TOOLS = ["Python", "SQL", "Docker", "Git", "Excel", "Power BI", "Figma", "TypeScript"]
_ORGS = ["Northwind Labs", "Bluebird Systems", "Kestrel Analytics", "Fjord Software", "Linden Works", "Harbor Digital",
         "Quill & Co", "Maple Robotics", "Tidewater Data", "Ember Studio"]
_CERTS = ["Scrum Master (PSM I)", "ITIL 4 Foundation", "Prince2 Foundation", "Google Data Analytics"]
_FAKE_ORGS = ["Globex Nordic", "Initech Europe", "Umbrella Logistics", "Stark Analytics", "Hooli Cloud", "Vandelay Industries"]
_FAKE_SKILLS = ["Kubernetes", "Terraform", "Apache Spark", "Rust", "Snowflake", "Airflow"]
_FAKE_CERTS = ["AWS Certified Solutions Architect", "PMP", "CISSP", "Certified Kubernetes Administrator"]
_MONTHS = {
    "en": "January February March April May June July August September October November December",
    "da": "januar februar marts april maj juni juli august september oktober november december",
    "fr": "janvier février mars avril mai juin juillet août septembre octobre novembre décembre",
    "hu": "január február március április május június július augusztus szeptember október november december",
    "sv": "januari februari mars april maj juni juli augusti september oktober november december",
}

# Bullets: (text, a figure in it, the same figure told another way, a different figure told in that other way).
_BULLETS = {
    "en": [
        ("Built and maintained services used by about 40 000 people a month.", "40 000", "40k", "60k"),
        ("Cut the nightly pipeline from 3 hours to 25 minutes by rewriting its slowest stage.", "25 minutes", "25 min", "12 min"),
        ("Grew annual revenue of the unit from 1 200 000 EUR to 1 850 000 EUR in three years.", "1 850 000 EUR", "1,85 M EUR", "2,4 M EUR"),
        ("Reduced customer churn from 12,5 % to 9 %.", "9 %", "9 percent", "5 percent"),
        ("Led a team of 14 people through a migration with no downtime.", "14 people", "fourteen people", "30 people"),
        ("Introduced code review and automated checks across 6 repositories.", "6 repositories", "six repositories", "11 repos"),
    ],
    "da": [
        ("Udviklede og drev tjenester, der bruges af omkring 40 000 mennesker om måneden.", "40 000", "40k", "60k"),
        ("Skar den natlige kørsel ned fra 3 timer til 25 minutter ved at skrive den langsomste del om.", "25 minutter", "25 min.", "12 min."),
        ("Voksede enhedens årlige omsætning fra 1 200 000 kr. til 1 850 000 kr. på tre år.", "1 850 000 kr.", "1,85 mio. kr.", "2,4 mio. kr."),
        ("Nedbragte kundefrafaldet fra 12,5 % til 9 %.", "9 %", "9 procent", "5 procent"),
        ("Ledede et team på 14 medarbejdere gennem en migrering uden nedetid.", "14 medarbejdere", "fjorten medarbejdere", "30 medarbejdere"),
        ("Indførte kodegennemgang og automatiske kontroller i 6 repositories.", "6 repositories", "seks repositories", "11 repositories"),
    ],
    "fr": [
        ("Développé et exploité des services utilisés par environ 40 000 personnes par mois.", "40 000", "40k", "60 k"),
        ("Ramené le traitement nocturne de 3 heures à 25 minutes en réécrivant son étape la plus lente.", "25 minutes", "25 min", "12 min"),
        ("Fait passer le chiffre d'affaires annuel de l'unité de 1 200 000 € à 1 850 000 € en trois ans.", "1 850 000 €", "1,85 M€", "2,4 M€"),
        ("Réduit le taux d'attrition de 12,5 % à 9 %.", "9 %", "9 pour cent", "5 pour cent"),
        ("Encadré une équipe de 14 personnes lors d'une migration sans interruption.", "14 personnes", "quatorze personnes", "30 collaborateurs"),
        ("Mis en place la revue de code et des contrôles automatiques sur 6 dépôts.", "6 dépôts", "six dépôts", "11 dépôts"),
    ],
    "hu": [
        ("Több mint 40 000 ember által havonta használt szolgáltatásokat fejlesztettem és üzemeltettem.", "40 000", "40e", "60e"),
        ("Az éjszakai feldolgozást 3 óráról 25 percre rövidítettem a leglassabb lépés átírásával.", "25 percre", "huszonöt percre", "12 percre"),
        ("Az egység éves árbevételét három év alatt 1 200 000 euróról 1 850 000 euróra növeltem.", "1 850 000 euróra", "1,85 millió euróra", "2,4 millió euróra"),
        ("Az ügyfélelvándorlást 12,5 %-ról 9 %-ra csökkentettem.", "9 %-ra", "9 százalékra", "5 százalékra"),
        ("14 fős csapatot vezettem állásidő nélküli migráción keresztül.", "14 fős", "tizennégy fős", "30 fős"),
        ("Kódátvizsgálást és automatikus ellenőrzéseket vezettem be 6 tárolóban.", "6 tárolóban", "hat tárolóban", "11 tárolóban"),
    ],
    "sv": [
        ("Byggde och drev tjänster som används av cirka 40 000 personer i månaden.", "40 000", "40k", "60k"),
        ("Kortade den nattliga körningen från 3 timmar till 25 minuter genom att skriva om det långsammaste steget.", "25 minuter", "25 min", "12 min"),
        ("Ökade enhetens årliga omsättning från 1 200 000 kr till 1 850 000 kr på tre år.", "1 850 000 kr", "1,85 Mkr", "2,4 Mkr"),
        ("Minskade kundbortfallet från 12,5 % till 9 %.", "9 %", "9 procent", "5 procent"),
        ("Ledde ett team på 14 personer genom en migrering utan driftstopp.", "14 personer", "fjorton personer", "30 personer"),
        ("Införde kodgranskning och automatiska kontroller i 6 repon.", "6 repon", "sex repon", "11 repon"),
    ],
}

_PACK = {
    "en": dict(
        country="gb", phone="+44", cities=["Manchester", "Bristol", "Leeds"], school="Example University",
        first=["Emma", "Oliver", "Hannah", "Jack", "Grace", "Thomas", "Ruby"], last=["Clarke", "Hughes", "Bennett", "Shaw", "Palmer", "Wood", "Marsh"],
        roles=["Data Analyst", "Senior Data Analyst", "Analytics Lead"], present="present",
        summary="{title} who likes clear plans, steady progress and plain language.",
        headings=dict(summary="Profile", experience="Work Experience", education="Education", skills="Skills", certifications="Certifications",
                      languages="Languages", interests="Interests", other="Volunteering"),
        alt=dict(experience="Career History", skills="Key Skills"),
        labels=dict(phone="Phone", email="Email", web="Web", location="Location"),
        levels=dict(native="native", fluent="fluent", working="working proficiency", conversational="conversational", basic="basic"),
        skill_word="advanced", soft=["stakeholder management", "planning", "reporting"],
        degrees=["MSc in Computer Science", "BSc in Mathematics"], fake_degrees=["MBA in Strategic Management", "PhD in Economics"],
        interests="Running, gardening and board games.", extra="Mentor to new colleagues and volunteer at a local code club.",
        langs=dict(en="English", da="Danish", fr="French", hu="Hungarian", sv="Swedish", de="German"), third="de",
    ),
    "da": dict(
        country="dk", phone="+45", cities=["Aarhus", "Odense", "Aalborg"], school="Eksempel Universitet",
        first=["Mette", "Lars", "Sofie", "Jens", "Ida", "Anders", "Freja"], last=["Holm", "Berg", "Lund", "Dahl", "Mørk", "Skov", "Vinther"],
        roles=["Dataanalytiker", "Senioranalytiker", "Leder af analyse"], present="nu",
        summary="{title}, der kan lide klare planer, jævn fremdrift og et enkelt sprog.",
        headings=dict(summary="Profil", experience="Erhvervserfaring", education="Uddannelse", skills="Kompetencer", certifications="Certificeringer",
                      languages="Sprog", interests="Interesser", other="Frivilligt arbejde"),
        alt=dict(experience="Karriere", skills="Nøglekompetencer"),
        labels=dict(phone="Tlf", email="E-mail", web="Hjemmeside", location="By"),
        levels=dict(native="modersmål", fluent="flydende", working="arbejdssprog", conversational="samtaleniveau", basic="grundlæggende"),
        skill_word="avanceret", soft=["interessenthåndtering", "planlægning", "rapportering"],
        degrees=["Cand.scient. i datalogi", "Bachelor i matematik"], fake_degrees=["MBA i strategisk ledelse", "Ph.d. i økonomi"],
        interests="Løb, havearbejde og brætspil.", extra="Mentor for nye kolleger og frivillig i en lokal kodeklub.",
        langs=dict(en="Engelsk", da="Dansk", fr="Fransk", hu="Ungarsk", sv="Svensk", de="Tysk"), third="de",
    ),
    "fr": dict(
        country="fr", phone="+33", cities=["Lyon", "Lille", "Nantes"], school="Université d'Exemple",
        first=["Camille", "Julien", "Léa", "Mathieu", "Chloé", "Hugo", "Manon"], last=["Martin", "Roche", "Bernard", "Moreau", "Fabre", "Lambert", "Girard"],
        roles=["Analyste de données", "Analyste senior", "Responsable analytique"], present="présent",
        summary="{title} qui aime les plans clairs, les progrès réguliers et un langage simple.",
        headings=dict(summary="Profil", experience="Expérience professionnelle", education="Formation", skills="Compétences", certifications="Certifications",
                      languages="Langues", interests="Centres d'intérêt", other="Bénévolat"),
        alt=dict(experience="Parcours", skills="Savoir-faire"),
        labels=dict(phone="Tél", email="Courriel", web="Site", location="Lieu"),
        levels=dict(native="langue maternelle", fluent="courant", working="opérationnel", conversational="conversationnel", basic="notions"),
        skill_word="avancé", soft=["gestion des parties prenantes", "planification", "reporting"],
        degrees=["Master en informatique", "Licence de mathématiques"], fake_degrees=["MBA en management stratégique", "Doctorat en économie"],
        interests="Course à pied, jardinage et jeux de société.", extra="Mentor des nouveaux collègues et bénévole dans un club de code local.",
        langs=dict(en="Anglais", da="Danois", fr="Français", hu="Hongrois", sv="Suédois", de="Allemand"), third="de",
    ),
    "hu": dict(
        country="hu", phone="+36", cities=["Debrecen", "Szeged", "Pécs"], school="Példa Egyetem",
        first=["Eszter", "Gábor", "Anna", "Balázs", "Réka", "Márton", "Dóra"], last=["Kovács", "Szabó", "Varga", "Molnár", "Fekete", "Tóth", "Balogh"],
        roles=["Adatelemző", "Vezető adatelemző", "Elemzési vezető"], present="jelenleg",
        summary="{title}, aki szereti az egyértelmű terveket, az egyenletes haladást és az egyszerű nyelvet.",
        headings=dict(summary="Profil", experience="Szakmai tapasztalat", education="Tanulmányok", skills="Készségek", certifications="Tanúsítványok",
                      languages="Nyelvek", interests="Érdeklődési kör", other="Önkéntes munka"),
        alt=dict(experience="Pályafutás", skills="Szakértelem"),
        labels=dict(phone="Telefon", email="E-mail", web="Weboldal", location="Város"),
        levels=dict(native="anyanyelv", fluent="folyékony", working="munkanyelv", conversational="társalgási", basic="alapszint"),
        skill_word="haladó", soft=["érdekelt felek kezelése", "tervezés", "riportolás"],
        degrees=["Informatikus MSc", "Matematika BSc"], fake_degrees=["MBA stratégiai menedzsment", "Közgazdaságtan PhD"],
        interests="Futás, kertészkedés és társasjátékok.", extra="Mentor új kollégáknak és önkéntes egy helyi programozókörben.",
        langs=dict(en="Angol", da="Dán", fr="Francia", hu="Magyar", sv="Svéd", de="Német"), third="de",
    ),
    "sv": dict(
        country="se", phone="+46", cities=["Göteborg", "Malmö", "Uppsala"], school="Exempel Universitet",
        first=["Elin", "Johan", "Maja", "Erik", "Sara", "Oskar", "Linnea"], last=["Lindqvist", "Ekström", "Holmgren", "Sandberg", "Wikström", "Nyberg", "Åberg"],
        roles=["Dataanalytiker", "Senioranalytiker", "Analyschef"], present="nuvarande",
        summary="{title} som gillar tydliga planer, stadiga framsteg och enkelt språk.",
        headings=dict(summary="Profil", experience="Arbetslivserfarenhet", education="Utbildning", skills="Kompetenser", certifications="Certifieringar",
                      languages="Språk", interests="Intressen", other="Volontärarbete"),
        alt=dict(experience="Karriär", skills="Nyckelkompetenser"),
        labels=dict(phone="Tel", email="E-post", web="Webbplats", location="Ort"),
        levels=dict(native="modersmål", fluent="flytande", working="arbetsspråk", conversational="samtalsnivå", basic="grundläggande"),
        skill_word="avancerad", soft=["intressenthantering", "planering", "rapportering"],
        degrees=["Civilingenjör i datateknik", "Kandidat i matematik"], fake_degrees=["MBA i strategisk ledning", "Doktor i nationalekonomi"],
        interests="Löpning, trädgårdsarbete och sällskapsspel.", extra="Mentor åt nya kollegor och volontär i en lokal kodklubb.",
        langs=dict(en="Engelska", da="Danska", fr="Franska", hu="Ungerska", sv="Svenska", de="Tyska"), third="de",
    ),
}


def _ascii(text: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


def make_person(n: int) -> dict:
    """The made-up person number *n*: language, name, jobs, schooling, skills, languages; every choice a function of *n*."""
    lang = LANG_PATTERN[n % 10]
    pack = _PACK[lang]
    first, last = pack["first"][n % 7], pack["last"][(n * 3 + 1) % 7]
    base = 2008 + n % 4
    spans = [(base + 9, None), (base + 5, base + 9), (base + 2, base + 5)]
    jobs = [{"role": pack["roles"][2 - i], "org": _ORGS[(n + i * 3) % 10], "place": pack["cities"][(n + i) % 3], "start": a, "end": b,
             "bullets": [_BULLETS[lang][(n + i + j) % 6] for j in range(3)]} for i, (a, b) in enumerate(spans)]
    edu = [{"degree": pack["degrees"][1], "school": pack["school"], "place": pack["cities"][n % 3], "start": base - 3, "end": base},
           {"degree": pack["degrees"][0], "school": pack["school"], "place": pack["cities"][n % 3], "start": base, "end": base + 2}]
    own = (lang, "native")
    spoken = [own, ("en" if lang != "en" else "fr", "fluent" if n % 2 else "working"), (pack["third"], "basic" if n % 3 else "conversational")]
    return {
        "n": n, "lang": lang, "name": f"{first} {last}", "title": pack["roles"][2], "city": pack["cities"][n % 3], "country": pack["country"],
        "phone": f"{pack['phone']} 00 00 00 00",  # the number the privacy guard knows as made up
        "email": f"{_ascii(first)}.{_ascii(last)}@example.com", "slug": f"{_ascii(first)}.{_ascii(last)}",
        "style": n % 3, "contact_style": (n // 3) % 3, "level_style": n % 2, "variant": (n // 2) % 2,
        "skill_levels": n % 3 == 1, "extra": n % 2 == 0, "linkedin": n % 4 == 0,
        "jobs": jobs, "education": edu,
        "skills": [_TOOLS[(n + i) % 8] for i in range(5)] + [pack["soft"][n % 3]],
        "certs": [(_CERTS[(n + i) % 4], 2016 + (n + i) % 8) for i in range(2)],
        "languages": spoken, "months": [(n + i * 5) % 12 for i in range(6)],
    }


PEOPLE = [make_person(n) for n in range(28)]


# --- the CV as markdown, with what it says built in --------------------------------------------------------------

def _dates(person: dict, start, end, i: int) -> str:
    pack = _PACK[person["lang"]]
    if person["style"] != 2:
        return f"{start} - {end or pack['present']}"
    months = _MONTHS[person["lang"]].split()
    m1 = months[person["months"][i % 6]]
    tail = pack["present"] if end is None else f"{months[person['months'][(i + 1) % 6]]} {end}"
    return f"{m1} {start} \u2013 {tail}"


def _entry(person: dict, role: str, org: str, place: str, start, end, i: int) -> tuple[str, dict]:
    dates = _dates(person, start, end, i)
    style = person["style"]
    if style == 0:
        heading, place = f"{role}, {org} ({dates})", None
    elif style == 1:
        heading = f"{role} | {org} \u2014 {dates} | {place}"
    else:
        heading = f"{org}, {place} \u2013 {role} ({dates})"
    return heading, {"heading": heading, "role": role, "org": org, "dates": dates, "place": place, "start_year": start, "end_year": end}


def _contact_block(person: dict, labels: dict) -> tuple[str, list[dict]]:
    items = [("phone", person["phone"]), ("email", person["email"]), ("web", f"example.com/{person['slug']}"), ("location", person["city"])]
    if person["linkedin"]:
        items.insert(3, ("linkedin", f"https://www.linkedin.com/in/{person['slug']}"))
    style = person["contact_style"]
    tag = {k: labels.get(k) or ("LinkedIn" if k == "linkedin" else None) for k, _ in items}
    contacts = [{"kind": k, "label": None if style == 2 else tag[k], "value": v} for k, v in items]
    if style == 0:
        return " | ".join(f"**{tag[k]}:** {v}" for k, v in items), contacts
    if style == 1:
        return "\n".join(f"{tag[k]}: {v}" for k, v in items) + "\n", contacts
    return " | ".join(v for _, v in items), contacts


def render_cv_md(person: dict) -> tuple[str, dict]:
    """The person's cv.md and `expected` (what a reader should find in it): every expected value is a literal of the text."""
    pack, lang = _PACK[person["lang"]], person["lang"]
    heads = {**pack["headings"], **(pack["alt"] if person["variant"] else {})}
    sections: dict[str, str] = {}
    entries: list[dict] = []
    levels: dict = {}
    out = [f"# {person['name']}", "", f"> {person['title']}", ""]
    block, contacts = _contact_block(person, pack["labels"])
    out += [block, ""]

    def section(kind: str) -> None:
        sections[heads[kind]] = kind
        out.extend([f"## {heads[kind]}", ""])

    section("summary")
    out += [pack["summary"].format(title=person["title"]), ""]
    section("experience")
    for i, job in enumerate(person["jobs"]):
        heading, entry = _entry(person, job["role"], job["org"], job["place"], job["start"], job["end"], i)
        entries.append(entry)
        out += [f"### {heading}", "", *[f"- {b[0]}" for b in job["bullets"]], ""]
    section("education")
    for i, ed in enumerate(person["education"]):
        heading, entry = _entry(person, ed["degree"], ed["school"], ed["place"], ed["start"], ed["end"], i + 3)
        entries.append(entry)
        out += [f"### {heading}", ""]
    section("skills")
    if person["skill_levels"]:
        out += [f"- {s} \u2014 {pack['skill_word']}" for s in person["skills"]] + [""]
        levels.update({s: None for s in person["skills"]})
    else:
        out += [", ".join(person["skills"]), ""]
    section("certifications")
    out += [f"- **{name}** \u2014 {year}" for name, year in person["certs"]] + [""]
    section("languages")
    working = []
    for code, level in person["languages"]:
        name, cefr = pack["langs"][code], person["level_style"] == 1 and level != "native"
        word = CEFR[level] if cefr else pack["levels"][level]
        out.append(f"- **{name}** ({word})" if cefr else (f"- **{name}** \u2014 {word}" if person["n"] % 3 else f"- {name}: {word}"))
        levels[name] = LEVEL_NUMBER[level]
        if LEVEL_NUMBER[level] >= 3:
            working.append(ENGLISH_NAME[code])
    out.append("")
    section("interests")
    out += [pack["interests"], ""]
    if person["extra"]:
        section("other")
        out += [pack["extra"], ""]
    md = "\n".join(out)
    expected = {"name": person["name"], "email": person["email"], "city": person["city"], "country": pack["country"],
                "working_languages": sorted(working), "sections": sections, "contacts": contacts, "levels": levels, "entries": entries}
    return md, expected


def render_body(person: dict, *, reformat: bool = False) -> str:
    """The CV as a tailored body in the tailor's vocabulary (`cv_body.body`: no model). `reformat` tells two figures of
    the first job another way (the same value: `40 000` as `40k`), which the CV backs."""
    body = cv_body.body(render_cv_md(person)[0], person["lang"])
    if reformat:
        for _, anchor, same, _ in person["jobs"][0]["bullets"][:2]:
            body = body.replace(html.escape(anchor, quote=False), html.escape(same, quote=False), 1)
    return body


# --- planting fabrications --------------------------------------------------------------------------------------

def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def _insert_in_section(body: str, heading: str, snippet_ul: str, snippet_p: str) -> str:
    """Add to the end of the list or paragraph that follows `heading` (its `<h2>`)."""
    start = body.find(f"<h2>{_esc(heading)}</h2>")
    if start < 0:
        raise ValueError(f"no section {heading!r} to plant in")
    ul, p = body.find("</ul>", start), body.find("</p>", start)
    nxt = body.find("<h2>", start + 1)
    nxt = len(body) if nxt < 0 else nxt
    if 0 <= ul < nxt and (p < 0 or ul < p):
        return body[:ul] + snippet_ul + body[ul:]
    if 0 <= p < nxt:
        return body[:p] + snippet_p + body[p:]
    raise ValueError(f"no list or paragraph in {heading!r}")


def _swap(body: str, old: str, new: str) -> str:
    if old not in body:
        raise ValueError(f"nothing to plant at: {old!r}")
    return body.replace(old, new, 1)


def plant(body: str, kind: str, person: dict, pick: int) -> tuple[str, dict]:
    """`body` with one fabrication of `kind` planted by an anchored replacement, and what was planted:
    `{kind, planted_value, quote}` (`quote` is a stretch of the new body's text). Raises ValueError with no anchor."""
    pack, source = _PACK[person["lang"]], render_cv_md(person)[0]
    heads = {**pack["headings"], **(pack["alt"] if person["variant"] else {})}
    if kind == "number":
        _, anchor, _, fake = person["jobs"][pick % 3]["bullets"][pick % 3]
        return _swap(body, _esc(anchor), _esc(fake)), {"kind": kind, "planted_value": fake, "quote": fake}
    if kind == "year":
        job = person["jobs"][2]
        old = _dates(person, job["start"], job["end"], 2)
        fake_year = next(y for y in (job["start"] - 2, job["start"] - 1, job["start"] - 3, job["start"] + 3) if str(y) not in source)
        new = old.replace(str(job["start"]), str(fake_year), 1)
        return _swap(body, _esc(old), _esc(new)), {"kind": kind, "planted_value": str(fake_year), "quote": new}
    if kind == "employer":
        fake = _FAKE_ORGS[pick % len(_FAKE_ORGS)]
        return _swap(body, _esc(person["jobs"][2]["org"]), _esc(fake)), {"kind": kind, "planted_value": fake, "quote": fake}
    if kind == "degree":
        fake = pack["fake_degrees"][pick % 2]
        return _swap(body, _esc(person["education"][1]["degree"]), _esc(fake)), {"kind": kind, "planted_value": fake, "quote": fake}
    if kind == "skill":
        fake = _FAKE_SKILLS[pick % len(_FAKE_SKILLS)]
        return (_insert_in_section(body, heads["skills"], f"<li>{fake}</li>", f", {fake}"),
                {"kind": kind, "planted_value": fake, "quote": fake})
    if kind == "certification":
        fake = _FAKE_CERTS[pick % len(_FAKE_CERTS)]
        return (_insert_in_section(body, heads["certifications"], f"<li><strong>{fake}</strong></li>", f" {fake}"),
                {"kind": kind, "planted_value": fake, "quote": fake})
    raise ValueError(f"unknown kind {kind!r}")


# --- the two corpora ---------------------------------------------------------------------------------------------

def build_reader_corpus() -> dict:
    """The CVs the reader reads: `{name: {lang, md, expected}}` for the first 15 people (every language, every heading
    and contact style, levels in words and in CEFR, a level word outside the table, headings no word list knows)."""
    corpus = {}
    for person in PEOPLE[:15]:
        md, expected = render_cv_md(person)
        corpus[f"p{person['n']:02d}-{person['lang']}"] = {"lang": person["lang"], "md": md, "expected": expected}
    return corpus


def build_body_corpus() -> dict:
    """The tailored bodies the fact check reads: `{name: {lang, person, md, body, plants}}`; the first 20 people's with
    one to three fabrications each (every kind planted), then 8 clean twins with a figure told another way."""
    corpus, cursor = {}, 0
    for n, person in enumerate(PEOPLE[:28]):
        body, plants = render_body(person, reformat=n >= 20), []
        if n < 20:
            for c in range(1 + n % 3):
                body, info = plant(body, KINDS[(cursor + c) % len(KINDS)], person, n + c)
                plants.append(info)
            cursor += 1 + n % 3
        corpus[f"b{n:02d}-{person['lang']}"] = {"lang": person["lang"], "person": n, "md": render_cv_md(person)[0], "body": body, "plants": plants}
    return corpus


# --- the fixtures on disk ---------------------------------------------------------------------------------------

CASES = REPO / "tests" / "tailoring" / "fixtures" / "cv_reading"


def _dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def write_fixtures() -> None:
    """Write the corpora to `tests/tailoring/fixtures/cv_reading/{readers,bodies}/<case>/`; a test checks the files
    are what the builders make, so run this after changing them and read the diff."""
    import shutil
    for folder in ("readers", "bodies"):
        shutil.rmtree(CASES / folder, ignore_errors=True)
    for name, case in build_reader_corpus().items():
        (CASES / "readers" / name).mkdir(parents=True, exist_ok=True)
        (CASES / "readers" / name / "cv.md").write_text(case["md"], encoding="utf-8")
        _dump(CASES / "readers" / name / "expected.json", case["expected"])
    for name, case in build_body_corpus().items():
        (CASES / "bodies" / name).mkdir(parents=True, exist_ok=True)
        (CASES / "bodies" / name / "cv.md").write_text(case["md"], encoding="utf-8")
        (CASES / "bodies" / name / "cv.html").write_text(case["body"], encoding="utf-8")
        _dump(CASES / "bodies" / name / "expected.json", {"lang": case["lang"], "plants": case["plants"]})


# --- today's rules, as the baseline ------------------------------------------------------------------------------

_SECTION_KINDS = ("skills", "education", "certifications", "languages", "interests")


def baseline_reader(md: str, lang: str) -> dict:
    """What the rules of today read from `md`, as an answer of the model's shape: the header parse and
    `_infer_basics_core` (with its model call refused), the section word lists, the level table, `_heading3`'s split."""
    import tempfile
    from unittest import mock

    from door import i18n
    from door.commands import cv as cv_cmd
    from door.core import claude_cli, cv_sections

    with tempfile.TemporaryDirectory() as tmp, mock.patch.object(claude_cli, "ask", side_effect=claude_cli.ClaudeError("off")):
        basics = cv_cmd._infer_basics_core(md, profile_dir=Path(tmp))
    head, labels = cv_body.header(md), cv_body.contact_labels(md)
    country = i18n.country_for_location(basics["location"] or "")
    body = cv_body.body(md, lang)
    levels = [{"item": m[1], "level": int(m[2])} for m in re.finditer(r"<li>(?:<strong>)?(.+?)(?:</strong>)?\s*[\u2014:(][^<]*<span class=\"level level-(\d)", body)]
    sections = [{"heading": cv_sections.heading(s[0])[0], "kind": cv_sections.kind(s, _SECTION_KINDS, (lang, "en")) or "other"}
                for s in cv_sections.split(md) if s and s[0].startswith("##")]
    entries = []
    for line in md.splitlines():
        if line.startswith("### "):
            parts = {m[1]: html.unescape(m[2]) for m in re.finditer(r'<span class="(role|org|dates|place)">(.*?)</span>', cv_body._heading3(line[4:].strip()))}
            entries.append({"heading": line[4:].strip(), **{k: parts.get(k) for k in ("role", "org", "dates", "place")}, "start_year": None, "end_year": None})
    return {
        "name": basics["name"], "email": basics["email"], "city": basics["location"], "country": country.code if country else None,
        "languages": [{"language": l, "level": "fluent"} for l in basics["languages"]],
        "sections": sections, "levels": levels, "entries": entries,
        "contacts": [{"kind": k, "label": labels.get(k, "").rstrip(":") or None, "value": v} for k, vs in head["details"].items() for v in vs],
    }


def baseline_facts(md: str, body: str) -> list[dict]:
    """What `facts.extract_claims` and `unsupported` flag in `body` against `md`, today, as findings."""
    return facts.unsupported(facts.extract_claims(body, "cv"), [md], current_year=2026)


# --- recorded answers and the report -----------------------------------------------------------------------------

RECORDED = CASES / "recorded"


def load_recorded(model: str, task: str, version: int, root: Path = RECORDED) -> dict:
    """`{case: [answer per run]}` from `<root>/<model>/<task>/v<version>/<case>.<run>.json`; a run that failed is `{"error"}`."""
    folder = Path(root) / model / task / f"v{version}"
    runs: dict[str, dict[int, object]] = {}
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        case, run = path.stem.rsplit(".", 1)
        data = json.loads(path.read_text(encoding="utf-8"))
        runs.setdefault(case, {})[int(run)] = data["answer"] if "answer" in data else {"error": data.get("error", "unknown")}
    return {case: [by_run[r] for r in sorted(by_run)] for case, by_run in runs.items()}


def summarize(task: str, answers: dict, corpus: dict) -> dict:
    """The numbers of one model on one task from `answers` (`{case: [answer per run]}`), with the verdict."""
    runs = max((len(a) for a in answers.values()), default=0)
    if task == "reader":
        total = {f: [0, 0] for f in READER_FIELDS}
        for case, runs_ in answers.items():
            for answer in runs_:
                for field, cell in score_reader(corpus[case]["expected"], answer).items():
                    total[field][0] += cell["hit"]
                    total[field][1] += cell["total"]
        fields = {f: (h / t if t else 0.0) for f, (h, t) in total.items()}
        return {"cases": len(answers), "runs": runs, "fields": fields, "verdict": reader_verdict(fields)}
    kinds = {k: [0, 0] for k in KINDS}
    verbatim, false_clean, false_planted, bodies = [0, 0], [], [], 0
    for case, runs_ in answers.items():
        for answer in runs_:
            score = score_facts(corpus[case]["plants"], answer, corpus[case]["body"])
            for kind, cell in score["per_kind"].items():
                kinds[kind][0] += cell["found"]
                kinds[kind][1] += cell["planted"]
            verbatim[0] += score["verbatim"][0]
            verbatim[1] += score["verbatim"][1]
            (false_planted if corpus[case]["plants"] else false_clean).append(score["false_flags"])
            bodies += 1
    report = {
        "cases": len(answers), "runs": runs, "per_kind": {k: h / t for k, (h, t) in kinds.items() if t},
        "false_clean_max": max(false_clean, default=0), "false_clean_mean": sum(false_clean) / max(len(false_clean), 1),
        "false_planted_mean": sum(false_planted) / max(len(false_planted), 1),
        "verbatim": verbatim[0] / verbatim[1] if verbatim[1] else 1.0,
        "stable": stability({c: a for c, a in answers.items()}) if runs > 1 else None,
    }
    report["verdict"] = facts_verdict({**report, "stable": 1.0 if report["stable"] is None else report["stable"]})
    return report


def to_markdown(task: str, report: dict) -> str:
    """The report as a markdown table."""
    pct = lambda x: "n/a" if x is None else f"{100 * x:.0f}%"  # noqa: E731
    head = f"{report['cases']} cases x {report['runs']} runs, verdict: **{report['verdict']}**\n\n"
    if task == "reader":
        return head + "| field | right |\n|---|---|\n" + "".join(f"| {f} | {pct(v)} |\n" for f, v in report["fields"].items())
    rows = "".join(f"| {k} | {pct(v)} |\n" for k, v in report["per_kind"].items())
    return (head + "| kind | recall |\n|---|---|\n" + rows +
            f"\nfalse flags: clean bodies max {report['false_clean_max']}, mean {report['false_clean_mean']:.2f}; planted bodies mean "
            f"{report['false_planted_mean']:.2f}. verbatim: {pct(report['verbatim'])}. stable: {pct(report['stable'])}.\n")


# --- the prompts ------------------------------------------------------------------------------------------------
# Spike-local: if the model is chosen, they move to the CV reader (`core/cv_read.py`) and to the facts check. A miss
# becomes an example here, made up from a person other than the case that missed (never a Python rule); `EXAMPLES`
# holds each with the round that added it, so an older round can be measured again as it was.

_READER_PROMPT = (
    "You read a job seeker's CV (markdown, in any language) and report what it says as JSON. Copy text exactly as "
    "written; never guess: null when the CV does not say.\n"
    "- `name`, `email`: as written. `city`: where they live (the contact details), else the city of their current job. "
    "`country`: the ISO 3166-1 alpha-2 code, lower case, of that city's country.\n"
    "- `languages`: every spoken language the CV names, `language` its English name and `level` one of native, fluent "
    "(professional, business, C1), working (B2), conversational (B1) or basic (A1, A2). C2 is native.\n"
    "- `sections`: every `##` heading, `heading` exactly as written, `kind` one of summary (the profile or the "
    "introduction), experience (the jobs), education, skills, certifications, languages, interests or other. The kind "
    "is by what the section holds, whatever the heading says or the language is.\n"
    "- `contacts`: each contact detail of the header: `kind` (phone, email, web, linkedin, github, location), `label` "
    "the word written before it (`Tlf`, without the colon) or null when it has none, `value` as written.\n"
    "- `levels`: every item of a skills or languages list that states a level, `item` as written and `level` 1 to 5 "
    "(5 native or C2, 4 fluent or C1, 3 working or B2, 2 conversational or B1, 1 basic, A1 or A2); null when the "
    "stated word is not one of these (a skill that is `advanced` has no level).\n"
    "- `entries`: every `###` heading, `heading` exactly as written after the `###`, and its parts: `role` (a job "
    "title or a degree), `org` (the employer or the school), `dates` as written, `place` (null when the heading has "
    "none), `start_year` and `end_year` (integers; `end_year` null when the end is the present).\n"
    "Answer with the JSON only."
)

_FACTS_PROMPT = (
    "You check a tailored CV against the candidate's own CV. You get the SOURCE (markdown) and the TAILORED CV (HTML). "
    "The tailored CV may drop, reorder, shorten and reword; it must not add a fact the source does not back. List every "
    "claim in the tailored CV that the source does not support:\n"
    "- `number`: a figure, amount, percentage or count whose VALUE differs from the source's; a figure told another way "
    "with the same value (`1 200 000 EUR` and `1,2 M EUR`, `40 000` and `40k`, `9 %` and `9 percent`, a number written "
    "in words) is supported.\n"
    "- `year`: a year, or a year of a date range, that differs from the source's.\n"
    "- `employer`: an employer the source does not name. `skill`: a tool, technology or method the source does not "
    "name. `certification`, `degree`: one the source does not name.\n"
    "Ignore the header and contact details. `value`: the claimed value. `context`: a stretch of the tailored CV's text, "
    "copied exactly as it reads (at most 15 words) that holds it. List nothing the source supports: an empty list is a "
    "clean CV. Answer with the JSON only."
)

EXAMPLES: dict[str, list[tuple[int, str]]] = {
    "reader": [
        # Round 2 (after Haiku's first reading: a level's word kept in the item, `##` kept in a heading, `working` read as fluent)
        (2, "`- **Italian** \u2014 fluent` gives item `Italian` with level 4, and `- Spanish (B2)` gives item `Spanish` with level 3: "
            "the item is the name alone, never with its level word."),
        (2, "A language at the level of a working language (`Arbeitssprache`, `lingua di lavoro`, `working proficiency`) is level 3, not 4: "
            "4 is for fluent, professional or C1."),
        (2, "`## Key Skills` gives the heading `Key Skills`: the `#` marks are not part of it."),
    ],
    "facts": [
        # Round 2 (after Haiku's first check: the HTML tags quoted, the same plant valued three ways)
        (2, "`context` is plain text with no HTML tag in it: for `<li><strong>Rust</strong></li>` it is `Rust`, for a heading "
            "`<span class=\"role\">Analyst</span> | <span class=\"org\">Zenith Corp</span>` it is `Analyst | Zenith Corp`."),
        (2, "`value` is the claimed item alone, as the CV writes it: a figure with its unit (`3 k`, `7 percent`), the name of an "
            "employer, skill, certification or degree. For a changed date range `2004 - 2008` the kind is `year` and the value the one "
            "year that differs (`2004`), not the range."),
        # Round 3 (after Sonnet's check: the tags of a one-element quote still copied)
        (3, "Never copy markup into `context`: `<strong>Rust</strong>` is wrong and `Rust` is right; `<span class=\"dates\">2004 - 2008</span>` "
            "is wrong and `Zenith Corp - 2004 - 2008` is right. Copy only words and figures, as the text of the page reads them."),
    ],
}


def prompt(task: str, version: int) -> str:
    """The system prompt of `task` as of round `version`: the base text and the examples added up to that round."""
    base = _READER_PROMPT if task == "reader" else _FACTS_PROMPT
    examples = [text for since, text in EXAMPLES[task] if since <= version]
    return base + ("\nExamples (made up):\n" + "\n".join(f"- {e}" for e in examples) if examples else "")


_STR_OR_NULL = {"type": ["string", "null"]}
_INT_OR_NULL = {"type": ["integer", "null"]}
READER_SCHEMA = {
    "type": "object",
    "properties": {
        "name": _STR_OR_NULL, "email": _STR_OR_NULL, "city": _STR_OR_NULL, "country": _STR_OR_NULL,
        "languages": {"type": "array", "items": {"type": "object", "properties": {"language": {"type": "string"}, "level": {"type": "string"}},
                                                 "required": ["language", "level"]}},
        "sections": {"type": "array", "items": {"type": "object", "properties": {"heading": {"type": "string"}, "kind": {"type": "string"}},
                                                "required": ["heading", "kind"]}},
        "contacts": {"type": "array", "items": {"type": "object", "properties": {"kind": {"type": "string"}, "label": _STR_OR_NULL, "value": {"type": "string"}},
                                                "required": ["kind", "label", "value"]}},
        "levels": {"type": "array", "items": {"type": "object", "properties": {"item": {"type": "string"}, "level": _INT_OR_NULL},
                                              "required": ["item", "level"]}},
        "entries": {"type": "array", "items": {"type": "object", "properties": {
            "heading": {"type": "string"}, "role": _STR_OR_NULL, "org": _STR_OR_NULL, "dates": _STR_OR_NULL, "place": _STR_OR_NULL,
            "start_year": _INT_OR_NULL, "end_year": _INT_OR_NULL}, "required": ["heading", "role", "org", "dates", "place", "start_year", "end_year"]}},
    },
    "required": ["name", "email", "city", "country", "languages", "sections", "contacts", "levels", "entries"],
}
FACTS_SCHEMA = {
    "type": "object",
    "properties": {"findings": {"type": "array", "items": {"type": "object", "properties": {
        "kind": {"type": "string", "enum": list(KINDS)}, "value": {"type": "string"}, "context": {"type": "string"}},
        "required": ["kind", "value", "context"]}}},
    "required": ["findings"],
}

MODELS = ("haiku", "sonnet")
CHOSEN_MODEL = "haiku"  # go on both tasks (see the module's docstring), and the cheaper of two that are within noise of each other
FINAL_VERSION = {"reader": 2, "facts": 3}  # the prompt round of the answers the report of #429 is made from


def ask_case(task: str, model: str, case: dict, version: int):
    """One call to the model for `case`: the reader's answer (a dict) or the facts check's findings (a list).
    Plan quota through `claude_cli.ask`; the feature keys are the nearest existing ones (see the module's docstring)."""
    from door.core import claude_cli

    if task == "reader":
        return claude_cli.ask(prompt("reader", version), f"CV:\n<<<\n{case['md']}\n>>>\n", model=model, feature="infer_basics",
                              schema=READER_SCHEMA, effort="low", timeout_s=240)
    text = f"SOURCE:\n<<<\n{case['md']}\n>>>\n\nTAILORED CV:\n<<<\n{case['body']}\n>>>\n"
    answer = claude_cli.ask(prompt("facts", version), text, model=model, feature="revise", schema=FACTS_SCHEMA, effort="low", timeout_s=240)
    return [{**f, "file": "cv"} for f in answer.get("findings") or [] if isinstance(f, dict)]


def run(task: str, model: str, corpus: dict, *, runs: int, version: int, root: Path = RECORDED, workers: int = 4) -> None:
    """Ask for every (case, run) with no recorded answer (a recorded error is asked again) and record it as raw JSON."""
    from concurrent.futures import ThreadPoolExecutor

    folder = Path(root) / model / task / f"v{version}"
    folder.mkdir(parents=True, exist_ok=True)

    def one(job):
        name, run_no = job
        path = folder / f"{name}.{run_no}.json"
        try:
            record = {"answer": ask_case(task, model, {"name": name, **corpus[name]}, version)}
            if isinstance(record["answer"], dict) and "error" in record["answer"]:
                record = record["answer"]
        except Exception as exc:  # noqa: BLE001 - a failed call is a miss to count, not a stop
            record = {"error": str(exc)[:300]}
        path.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        return name, run_no, "error" in record

    def done(path: Path) -> bool:
        return path.is_file() and "error" not in json.loads(path.read_text(encoding="utf-8"))

    jobs = [(n, r) for n in sorted(corpus) for r in range(runs) if not done(folder / f"{n}.{r}.json")]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for name, run_no, failed in pool.map(one, jobs):
            print(f"{model} {task} v{version} {name}.{run_no}: {'ERROR' if failed else 'recorded'}", file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write-fixtures", action="store_true")
    ap.add_argument("--task", choices=("reader", "facts", "report-reader", "report-facts"))
    ap.add_argument("--model", choices=(*MODELS, "baseline"), default="haiku")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--version", type=int, default=1, help="the prompt round (EXAMPLES say what each added)")
    args = ap.parse_args(argv)
    if args.write_fixtures:
        write_fixtures()
        return
    task = (args.task or "").removeprefix("report-")
    corpus = build_reader_corpus() if task == "reader" else build_body_corpus()
    if args.task in ("reader", "facts"):
        run(task, args.model, corpus, runs=args.runs, version=args.version)
        return
    if args.model == "baseline":
        answers = {n: [baseline_reader(c["md"], c["lang"]) if task == "reader" else baseline_facts(c["md"], c["body"])] for n, c in corpus.items()}
    else:
        answers = load_recorded(args.model, task, args.version)
    print(to_markdown(task, summarize(task, answers, corpus)))


if __name__ == "__main__":
    main()
