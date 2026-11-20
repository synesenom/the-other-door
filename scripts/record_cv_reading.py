"""Spike of #429 (epic #428): how well does a small model read a CV and check a tailored CV's facts?

Measures Haiku and Sonnet on made-up data only (never a real CV): a *reader* task (cv.md in, what the CV says out:
section kinds, contacts, skills, skill and language levels, name, email, city, country, working languages, role years,
the parts of each entry heading; every value but the country and the levels' numbers a stretch of the CV) and a *facts*
task (the source cv.md, a story bank, a posting, a tailored CV body and a cover letter body with fabrications planted in
them; the model lists the claims the sources do not back). Ground truth is built in: the corpus is generated from made-up
people, so every expected value is a literal of the text, and nothing of it is stored but the models' answers.

The facts corpus is meant to be hard: a body in another language than its source (headings, degrees, months and level
words translated, names, employers and figures kept), a tailor's rewording (new summary, merged and dropped bullets and
entries, reordered sections, a skill named by a synonym the CV backs), numeric and day-month dates, claims backed only
by a story bank, a letter echoing the posting, and fabrications in a letter. The facts prompt, schema and the check that a
finding's context is text of its document are `door.tailoring.facts`'s (#433): what is recorded here is what the app asks.
A miss becomes a made-up example in the prompt, never a rule in Python.

    poetry run python scripts/record_cv_reading.py --task reader|facts --model haiku|sonnet [--runs 3] [--held-out]
    poetry run python scripts/record_cv_reading.py --task reader|facts --model haiku|sonnet --report

`--held-out` builds a second corpus from other pools (names, employers, schools, places, degrees, skills, certifications, figures, story
bank and posting) that the prompts were never tuned on; its records are under `held-out/`.

A record is `tests/tailoring/fixtures/cv_reading/<model>/<task>/<case>.<run>.json`: the raw answer and a key of the
prompt and input it answered (a record of other text is not read, and a test fails for one). A failed call is recorded
as an error and counts as a miss; run again and only the errors are asked again (a plan's limit is waited out that way).
Calls go through `claude_cli.ask` on the local claude's plan (never an API key); the usage feature keys are
`cv_read` (the reader) and `facts` (the fact check).
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import unicodedata
from contextlib import contextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import cv_body  # noqa: E402
from door.core import claude_cli, cv_read  # noqa: E402
from door.render import html_doc  # noqa: E402
from door.tailoring import facts  # noqa: E402


def _n(value) -> str:
    """A text for comparison: case, spacing and the kind of dash do not matter."""
    text = re.sub(r"[‐-―−]", "-", str(value or ""))
    text = re.sub(r"\s*-\s*", "-", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


# --- scoring the reader -----------------------------------------------------------------------------------------

READER_FIELDS = ("sections", "contacts", "skills", "levels", "name", "email", "city", "country", "languages", "years",
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
    skills = {_n(s) for s in answer.get("skills") or []}
    for skill in expected["skills"]:
        _count(score, "skills", _n(skill) in skills)
    levels = {_n(i.get("item")): i.get("level") for i in answer.get("levels") or [] if isinstance(i, dict)}
    for item, level in expected["levels"].items():
        _count(score, "levels", levels.get(_n(item)) == level)
    working = {_n(l.get("language")) for l in answer.get("languages") or []
               if isinstance(l, dict) and str(l.get("level")).lower() in _WORKING}
    _count(score, "languages", working == {_n(x) for x in expected["working_languages"]})
    entries = {_n(e.get("heading")): e for e in answer.get("entries") or [] if isinstance(e, dict)}
    for want in expected["entries"]:
        got = entries.get(_n(want["heading"]), {})
        _count(score, "years", got.get("start_year") == want["start_year"])
        _count(score, "years", got.get("end_year") == want["end_year"])
        for part in ("role", "org", "dates", "place"):
            _count(score, f"heading_{part}", _n(got.get(part)) == _n(want[part]))
    return score


def stretches(md: str, answer) -> tuple[int, int]:
    """How many of the text values of a reader's `answer` (all but `country`, which is a code, and the levels' numbers)
    are a stretch of the CV `md`, of all it returned: what #430 needs to check an answer against the CV."""
    if not isinstance(answer, dict) or "error" in answer:
        return 0, 0
    text, values = _n(md), []
    values += [answer.get(k) for k in ("name", "email", "city")]
    values += [l.get("language") for l in answer.get("languages") or [] if isinstance(l, dict)]
    values += [s.get("heading") for s in answer.get("sections") or [] if isinstance(s, dict)]
    values += [c.get(k) for c in answer.get("contacts") or [] if isinstance(c, dict) for k in ("label", "value")]
    values += list(answer.get("skills") or [])
    values += [i.get("item") for i in answer.get("levels") or [] if isinstance(i, dict)]
    values += [e.get(k) for e in answer.get("entries") or [] if isinstance(e, dict) for k in ("heading", "role", "org", "dates", "place")]
    values = [v for v in values if v]
    return sum(_n(v) in text for v in values), len(values)


# --- scoring the facts check ------------------------------------------------------------------------------------

KINDS = facts.KINDS


def _val(value) -> str:
    """A claimed value for comparison: ``1,8 M kr`` and ``1.8M kr`` are one."""
    return re.sub(r"\s+", "", _n(value)).replace(",", ".")


is_verbatim = facts.is_verbatim


def _findings(answer) -> list[dict]:
    return [f for f in answer if isinstance(f, dict)] if isinstance(answer, list) else []


def _matches(plant: dict, found: dict) -> bool:
    if found.get("kind") != plant["kind"] or found.get("file", "cv") != plant.get("file", "cv"):
        return False
    context = _val(found.get("context"))
    return (_val(found.get("value")) == _val(plant["planted_value"]) or _val(plant["planted_value"]) in context
            or _val(plant["quote"]) in context)


def score_facts(plants: list[dict], findings, *bodies: str) -> dict:
    """One case's reading: `per_kind` {kind: {planted, found}} for the kinds planted, `false_flags` (findings that
    match no plant), `verbatim` (findings whose context is in a body, of all findings). An error answer finds nothing."""
    found = _findings(findings)
    per_kind: dict = {}
    for plant in plants:
        cell = per_kind.setdefault(plant["kind"], {"planted": 0, "found": 0})
        cell["planted"] += 1
        cell["found"] += any(_matches(plant, f) for f in found)
    false = sum(not any(_matches(p, f) for p in plants) for f in found)
    return {"per_kind": per_kind, "false_flags": false,
            "verbatim": (sum(is_verbatim(f.get("context"), *bodies) for f in found), len(found))}


def stability(answers: dict) -> float:
    """The share of cases whose set of (kind, value) flags is the same in every run (`answers`: case to each run's findings)."""
    same = [len({frozenset((f.get("kind"), _val(f.get("value"))) for f in _findings(r)) for r in runs}) == 1
            for runs in answers.values()]
    return sum(same) / len(same) if same else 0.0


# --- the go thresholds of #429 ----------------------------------------------------------------------------------

FACTS_GO = {"recall": 0.90, "false_clean_max": 1, "verbatim": 0.98, "stable": 0.95}
FACTS_NO_GO = {"recall": 0.80, "false_clean_max": 2}
READER_GO = {"sections": 0.98, "contacts": 0.98, "name": 1.0, "email": 1.0, "years": 0.95}
READER_NO_GO = 0.80


def facts_verdict(report: dict) -> str:
    """`go`, `no-go` or `close` for a facts report: `per_kind` recall, `false_clean_max` (most false flags on a clean
    body), `verbatim` and `stable` shares."""
    recalls = list(report["per_kind"].values()) or [0.0]  # nothing recorded is no reading
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
        ("Voksede enhedens årlige omsætning fra 1 200 000 EUR til 1 850 000 EUR på tre år.", "1 850 000 EUR", "1,85 mio. EUR", "2,4 mio. EUR"),
        ("Nedbragte kundefrafaldet fra 12,5 % til 9 %.", "9 %", "9 procent", "5 procent"),
        ("Ledede et team på 14 medarbejdere gennem en migrering uden nedetid.", "14 medarbejdere", "fjorten medarbejdere", "30 medarbejdere"),
        ("Indførte kodegennemgang og automatiske kontroller i 6 repositories.", "6 repositories", "seks repositories", "11 repositories"),
    ],
    "fr": [
        ("Développé et exploité des services utilisés par environ 40 000 personnes par mois.", "40 000", "40k", "60 k"),
        ("Ramené le traitement nocturne de 3 heures à 25 minutes en réécrivant son étape la plus lente.", "25 minutes", "25 min", "12 min"),
        ("Fait passer le chiffre d'affaires annuel de l'unité de 1 200 000 EUR à 1 850 000 EUR en trois ans.", "1 850 000 EUR", "1,85 M EUR", "2,4 M EUR"),
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
        ("Ökade enhetens årliga omsättning från 1 200 000 EUR till 1 850 000 EUR på tre år.", "1 850 000 EUR", "1,85 MEUR", "2,4 MEUR"),
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


# What only the tailored documents need, per language: a rewritten summary, the posting a letter echoes, the letter's
# words, and the one claim a story bank backs (the figure `4 000` and the tool `dbt` are in no CV).
_EXTRA = {
    "en": dict(summary2="I turn messy data into plans a team can act on, and I keep the reporting calm and readable.",
               recipient="Hiring team", greeting="Dear hiring team,", closing="Kind regards,",
               posting="Data Analyst at Orchid Energy. We are a company active in 120 countries and need an analyst who knows Looker.",
               echo="Your posting asks for Looker and for someone ready to support a company active in 120 countries.",
               letter_skill="I also work with {x}.",
               story_bullet="Automated invoice matching in dbt, clearing a backlog of 4 000 invoices a month."),
    "da": dict(summary2="Jeg gør rodede data til planer, et team kan handle på, og holder rapporteringen rolig og læsbar.",
               recipient="Rekrutteringsteamet", greeting="Kære rekrutteringsteam,", closing="Med venlig hilsen",
               posting="Dataanalytiker hos Orchid Energy. Vi er en virksomhed i 120 lande og søger en analytiker, der kender Looker.",
               echo="Jeres opslag beder om Looker og en, der vil støtte en virksomhed i 120 lande.",
               letter_skill="Jeg arbejder også med {x}.",
               story_bullet="Automatiserede fakturaafstemning i dbt og fik ryddet en bunke på 4 000 fakturaer om måneden."),
    "fr": dict(summary2="Je transforme des données brouillonnes en plans exploitables par une équipe et je garde le reporting clair et lisible.",
               recipient="Équipe de recrutement", greeting="Madame, Monsieur,", closing="Cordialement,",
               posting="Analyste de données chez Orchid Energy. Nous sommes présents dans 120 pays et cherchons un analyste qui connaît Looker.",
               echo="Votre annonce demande Looker et quelqu'un prêt à soutenir une entreprise présente dans 120 pays.",
               letter_skill="Je travaille aussi avec {x}.",
               story_bullet="Automatisé le rapprochement des factures dans dbt, résorbant un arriéré de 4 000 factures par mois."),
    "hu": dict(summary2="A rendetlen adatból olyan terveket készítek, amelyekre egy csapat építeni tud, és a riportolást áttekinthetően tartom.",
               recipient="Toborzó csapat", greeting="Tisztelt Toborzó Csapat!", closing="Üdvözlettel,",
               posting="Adatelemző az Orchid Energy-nél. 120 országban vagyunk jelen, és olyan elemzőt keresünk, aki ismeri a Looker-t.",
               echo="Hirdetésük szerint Looker-ismeret kell egy 120 országban jelen lévő cég támogatásához.",
               letter_skill="Emellett {x}-t is használok.",
               story_bullet="Automatizáltam a számlaegyeztetést dbt-ben, havi 4 000 számla elmaradását pótolva."),
    "sv": dict(summary2="Jag gör rörig data till planer som ett team kan agera på och håller rapporteringen lugn och läsbar.",
               recipient="Rekryteringsteamet", greeting="Hej rekryteringsteam,", closing="Vänliga hälsningar,",
               posting="Dataanalytiker hos Orchid Energy. Vi finns i 120 länder och söker en analytiker som kan Looker.",
               echo="Er annons efterfrågar Looker och någon som vill stödja ett företag i 120 länder.",
               letter_skill="Jag arbetar också med {x}.",
               story_bullet="Automatiserade fakturaavstämning i dbt och arbetade av en kö på 4 000 fakturor i månaden."),
}
STORY_BANK = (
    "## Invoice matching\n\n**Context:** The finance team matched supplier invoices by hand every month.\n\n"
    "**Action:** I built an automated matching job in dbt and wrote the checks for it.\n\n"
    "**Result:** It cleared a backlog of 4 000 invoices a month.\n\n"
    "**Learning:** Small checks written early save the most time.\n"
)
_SYNONYM = {"Excel": "Microsoft Excel", "Power BI": "PowerBI"}  # a skill the CV backs, named another way
DFMT = ("year", "mm/yyyy", "month", "d.m.yyyy", "yyyy-mm", "day")
# The language a body is written in when it is not its source's: one table to Danish or French, one to the others.
_CROSS_A = {"en": "da", "da": "fr", "fr": "da", "hu": "fr", "sv": "da"}
_CROSS_B = {"en": "fr", "da": "en", "fr": "en", "hu": "da", "sv": "fr"}


def _ascii(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


def make_person(n: int) -> dict:
    """The made-up person number *n*: language, name, jobs, schooling, skills, languages, how dates are written; every
    choice a function of *n*. Texts are not stored but looked up in a language's pack when rendered, so one person can
    be written in any language (names, employers, schools, places and figures stay)."""
    lang = LANG_PATTERN[n % 10]
    pack = _PACK[lang]
    first, last = pack["first"][n % 7], pack["last"][(n * 3 + 1) % 7]
    base = 2008 + n % 4
    spans = [(base + 9, None), (base + 5, base + 9), (base + 2, base + 5)]
    jobs = [{"role_i": 2 - i, "org": _ORGS[(n + i * 3) % 10], "place": pack["cities"][(n + i) % 3], "start": a, "end": b,
             "bullets": [(n + i + j) % 6 for j in range(3)]} for i, (a, b) in enumerate(spans)]
    edu = [{"degree_i": 1, "school": pack["school"], "place": pack["cities"][n % 3], "start": base - 3, "end": base},
           {"degree_i": 0, "school": pack["school"], "place": pack["cities"][n % 3], "start": base, "end": base + 2}]
    spoken = [(lang, "native"), ("en" if lang != "en" else "fr", "fluent" if n % 2 else "working"),
              (pack["third"], "basic" if n % 3 else "conversational")]
    return {
        "n": n, "lang": lang, "name": f"{first} {last}", "city": pack["cities"][n % 3], "country": pack["country"],
        "phone": f"{pack['phone']} 00 00 00 00",  # the number the privacy guard knows as made up
        "email": f"{_ascii(first)}.{_ascii(last)}@example.com", "slug": f"{_ascii(first)}.{_ascii(last)}",
        "style": n % 3, "dfmt": DFMT[(n + n // 3) % 6], "contact_style": (n // 3) % 3, "level_style": n % 2, "variant": (n // 2) % 2,
        "skill_levels": n % 3 == 1, "extra": n % 2 == 0, "linkedin": n % 4 == 0, "story": n % 2 == 0, "letter": n % 4 == 0,
        "jobs": jobs, "education": edu, "tools": [_TOOLS[(n + i) % 8] for i in range(5)], "soft_i": n % 3,
        "certs": [(_CERTS[(n + i) % 4], 2016 + (n + i) % 8) for i in range(2)],
        "languages": spoken, "months": [(n + i * 5) % 12 for i in range(6)],
    }


PEOPLE = [make_person(n) for n in range(28)]


def _held_out_pools() -> dict:
    """The pools of the held-out corpus (#429): other names, employers, schools, places, degrees, skills, certifications,
    figures (and currency), story bank and posting, in three languages. The languages' own words (headings, labels, month
    names, level words) are the same: a language has one set."""
    over = {
        "en": dict(first=["Isabel", "Callum", "Priya", "Marcus", "Freya", "Nathan", "Olive"], last=["Whitfield", "Okafor", "Lindgren", "Barrow", "Hartley", "Quinn", "Ashby"],
                   cities=["Norwich", "Leicester", "Exeter"], school="Sample College", roles=["Operations Analyst", "Senior Operations Analyst", "Head of Operations"],
                   summary="{title} who prefers checklists, clear owners and quiet mornings.", soft=["negotiation", "coaching", "budgeting"],
                   degrees=["MA in Business Administration", "BA in Economics"], fake_degrees=["MSc in Data Science", "LLB in Law"],
                   interests="Cycling, baking and choir singing.", extra="Chair of a local tenants' association and volunteer driver.",
                   alt=dict(experience="Employment", skills="Competencies")),
        "da": dict(first=["Karen", "Mikkel", "Signe", "Rasmus", "Astrid", "Emil", "Nanna"], last=["Bruun", "Kjeldsen", "Thomsen", "Winther", "Frost", "Lykke", "Nygaard"],
                   cities=["Esbjerg", "Roskilde", "Kolding"], school="Pr\u00f8ve H\u00f8jskole", roles=["Driftsanalytiker", "Seniordriftsanalytiker", "Driftschef"],
                   summary="{title}, der foretr\u00e6kker tjeklister, tydelige ansvarlige og rolige morgener.", soft=["forhandling", "coaching", "budgettering"],
                   degrees=["Cand.merc. i erhvervs\u00f8konomi", "Bachelor i \u00f8konomi"], fake_degrees=["Kandidat i dataanalyse", "Cand.jur."],
                   interests="Cykling, bagning og korsang.", extra="Formand for en lokal lejerforening og frivillig chauff\u00f8r.",
                   alt=dict(experience="Ans\u00e6ttelser", skills="F\u00e6rdigheder")),
        "fr": dict(first=["\u00c9lodie", "Baptiste", "In\u00e8s", "Th\u00e9o", "Margaux", "Romain", "Zo\u00e9"], last=["Perrin", "Colin", "Benoit", "Lacroix", "Marchand", "Dupuis", "Renard"],
                   cities=["Rennes", "Dijon", "Tours"], school="\u00c9cole d'Essai", roles=["Analyste des op\u00e9rations", "Analyste senior des op\u00e9rations", "Directeur des op\u00e9rations"],
                   summary="{title} qui pr\u00e9f\u00e8re les listes de contr\u00f4le, des responsables clairs et des matin\u00e9es calmes.", soft=["n\u00e9gociation", "coaching", "budget"],
                   degrees=["Master en gestion", "Licence en \u00e9conomie"], fake_degrees=["Master en science des donn\u00e9es", "Licence de droit"],
                   interests="Cyclisme, p\u00e2tisserie et chorale.", extra="Pr\u00e9sidente d'une association locale de locataires et conductrice b\u00e9n\u00e9vole.",
                   alt=dict(experience="Emplois", skills="Aptitudes")),
    }
    bullets = {
        "en": [("Managed a portfolio of 85 client accounts worth 3,2 M CHF in yearly billings.", "85 client accounts", "eighty-five client accounts", "120 client accounts"),
               ("Shortened the monthly close from 9 days to 4 days with a new checklist.", "4 days", "four days", "2 days"),
               ("Raised customer satisfaction from 71 % to 88 % over two years.", "88 %", "88 percent", "94 percent"),
               ("Trained a group of 23 new hires in the first quarter.", "23 new hires", "twenty-three new hires", "40 new hires"),
               ("Cut warehouse costs by 340 000 CHF a year by renegotiating three contracts.", "340 000 CHF", "340k CHF", "520k CHF"),
               ("Ran weekly reviews with 17 regional managers.", "17 regional managers", "seventeen regional managers", "26 regional managers")],
        "da": [("Styrede en portef\u00f8lje p\u00e5 85 kundekonti med en \u00e5rlig fakturering p\u00e5 3,2 mio. CHF.", "85 kundekonti", "femogfirs kundekonti", "120 kundekonti"),
               ("Forkortede m\u00e5nedsafslutningen fra 9 dage til 4 dage med en ny tjekliste.", "4 dage", "fire dage", "2 dage"),
               ("H\u00e6vede kundetilfredsheden fra 71 % til 88 % over to \u00e5r.", "88 %", "88 procent", "94 procent"),
               ("Opl\u00e6rte en gruppe p\u00e5 23 nye medarbejdere i f\u00f8rste kvartal.", "23 nye medarbejdere", "treogtyve nye medarbejdere", "40 nye medarbejdere"),
               ("Sparede 340 000 CHF om \u00e5ret p\u00e5 lageret ved at genforhandle tre kontrakter.", "340 000 CHF", "340k CHF", "520k CHF"),
               ("Holdt ugentlige gennemgange med 17 regionale ledere.", "17 regionale ledere", "sytten regionale ledere", "26 regionale ledere")],
        "fr": [("G\u00e9r\u00e9 un portefeuille de 85 comptes clients pour 3,2 M CHF de facturation annuelle.", "85 comptes clients", "quatre-vingt-cinq comptes clients", "120 comptes clients"),
               ("Raccourci la cl\u00f4ture mensuelle de 9 jours \u00e0 4 jours gr\u00e2ce \u00e0 une nouvelle liste de contr\u00f4le.", "4 jours", "quatre jours", "2 jours"),
               ("Fait passer la satisfaction client de 71 % \u00e0 88 % en deux ans.", "88 %", "88 pour cent", "94 pour cent"),
               ("Form\u00e9 un groupe de 23 nouvelles recrues au premier trimestre.", "23 nouvelles recrues", "vingt-trois nouvelles recrues", "40 nouvelles recrues"),
               ("\u00c9conomis\u00e9 340 000 CHF par an sur l'entrep\u00f4t en ren\u00e9gociant trois contrats.", "340 000 CHF", "340k CHF", "520k CHF"),
               ("Anim\u00e9 des revues hebdomadaires avec 17 responsables r\u00e9gionaux.", "17 responsables r\u00e9gionaux", "dix-sept responsables r\u00e9gionaux", "26 responsables r\u00e9gionaux")],
    }
    extra = {
        "en": dict(summary2="I make operations predictable: clear owners, written checklists and no surprises on Monday.", company="Marlow Freight",
                   posting="Operations Analyst at Marlow Freight. We run 45 sites and need an analyst who knows Metabase.",
                   echo="Your posting asks for Metabase and for someone ready to support 45 sites.",
                   story_bullet="Automated order routing in n8n, handling 1 800 orders a week without manual sorting."),
        "da": dict(summary2="Jeg g\u00f8r drift forudsigelig: tydelige ansvarlige, skrevne tjeklister og ingen overraskelser mandag.", company="Marlow Freight",
                   posting="Driftsanalytiker hos Marlow Freight. Vi driver 45 lokationer og s\u00f8ger en analytiker, der kender Metabase.",
                   echo="Jeres opslag beder om Metabase og en, der vil st\u00f8tte 45 lokationer.",
                   story_bullet="Automatiserede ordrerouting i n8n og h\u00e5ndterede 1 800 ordrer om ugen uden manuel sortering."),
        "fr": dict(summary2="Je rends les op\u00e9rations pr\u00e9visibles : des responsables clairs, des listes \u00e9crites et aucune surprise le lundi.", company="Marlow Freight",
                   posting="Analyste des op\u00e9rations chez Marlow Freight. Nous g\u00e9rons 45 sites et cherchons un analyste qui conna\u00eet Metabase.",
                   echo="Votre annonce demande Metabase et quelqu'un pr\u00eat \u00e0 soutenir 45 sites.",
                   story_bullet="Automatis\u00e9 le routage des commandes dans n8n, soit 1 800 commandes par semaine sans tri manuel."),
    }
    return {
        "LANG_PATTERN": ("da", "fr", "en", "fr", "da", "en", "fr", "da", "en", "fr"),
        "_CROSS_A": {"en": "da", "da": "fr", "fr": "da"}, "_CROSS_B": {"en": "fr", "da": "en", "fr": "en"},
        "_PACK": {l: {**_PACK[l], **{k: v for k, v in o.items() if k != "alt"}, "alt": {**_PACK[l]["alt"], **o["alt"]}} for l, o in over.items()},
        "_BULLETS": bullets, "_EXTRA": {l: {**_EXTRA[l], **o} for l, o in extra.items()},
        "STORY_BANK": ("## Order routing\n\n**Context:** Orders from the web shop were sorted by hand every morning.\n\n"
                       "**Action:** I built a routing flow in n8n and wrote the tests for it.\n\n"
                       "**Result:** It handled 1 800 orders a week without manual sorting.\n\n**Learning:** Test the awkward orders first.\n"),
        "_ORGS": ["Cedar Freight", "Alpine Textiles", "Granite Logistics", "Saffron Foods", "Birch Packaging", "Copper Mills", "Willow Print", "Anchor Marine", "Summit Tools", "Heron Supply"],
        "_TOOLS": ["SAP", "Tableau", "Jira", "Visio", "SharePoint", "Alteryx", "Trello", "Notion"],
        "_CERTS": ["Six Sigma Green Belt", "CIPD Level 5", "Lean Practitioner", "PRINCE2 Agile"],
        "_FAKE_ORGS": ["Dunmore Holdings", "Veridian Group", "Redwood Capital", "Pinnacle Retail", "Solace Pharma", "Zephyr Air"],
        "_FAKE_SKILLS": ["Power Automate", "Qlik", "Hadoop", "Scala", "Databricks", "Zapier"],
        "_FAKE_CERTS": ["CFA Level 1", "CPA", "Certified Scrum Professional", "Azure Fundamentals"],
    }


@contextmanager
def held_out():
    """Within it the corpus builders build the held-out corpus (#429), made from other pools than the one the prompts
    were tuned on: nothing is shared but a language's own words."""
    pools = _held_out_pools()
    saved = {k: globals()[k] for k in (*pools, "PEOPLE")}
    globals().update(pools)
    globals()["PEOPLE"] = [make_person(n) for n in range(28)]
    try:
        yield
    finally:
        globals().update(saved)


def body_lang(person: dict) -> str:
    """The language the person's tailored documents are written in: another than their CV's for two in three."""
    lang = person["lang"]
    return (_CROSS_A, _CROSS_B, {lang: lang})[person["n"] % 3][lang]


# --- the CV as markdown, with what it says built in --------------------------------------------------------------

def _when(person: dict, year: int, k: int, lang: str) -> str:
    """A date of `year` as the person writes dates, in `lang` (`k` picks its month and day)."""
    f, m, d = person["dfmt"], person["months"][k % 6], (person["n"] + k * 7) % 27 + 1
    name = _MONTHS[lang].split()[m]
    if f == "year":
        return str(year)
    if f == "month":
        return f"{name} {year}"
    if f == "mm/yyyy":
        return f"{m + 1:02d}/{year}"
    if f == "d.m.yyyy":
        return f"{d}.{m + 1}.{year}"
    if f == "yyyy-mm":
        return f"{year}-{m + 1:02d}"
    if lang == "en":
        return f"{d}{'th' if 10 <= d % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(d % 10, 'th')} {name} {year}"
    return {"hu": f"{year}. {name} {d}.", "da": f"{d}. {name} {year}"}.get(lang, f"{d} {name} {year}")


def _dates(person: dict, start: int, end, i: int, lang: str) -> str:
    tail = _PACK[lang]["present"] if end is None else _when(person, end, 2 * i + 1, lang)
    return f"{_when(person, start, 2 * i, lang)} {'-' if person['dfmt'] == 'year' else chr(0x2013)} {tail}"


def _entry(person: dict, role: str, org: str, place: str, start, end, i: int, lang: str) -> tuple[str, dict]:
    dates = _dates(person, start, end, i, lang)
    style = person["style"]
    if style == 0:
        heading, place = f"{role}, {org} ({dates})", None
    elif style == 1:
        heading = f"{role} | {org} — {dates} | {place}"
    else:
        heading = f"{org}, {place} – {role} ({dates})"
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


def _heads(person: dict, lang: str) -> dict:
    pack = _PACK[lang]
    return {**pack["headings"], **(pack["alt"] if person["variant"] else {})}


def render_cv_md(person: dict, lang: str | None = None, *, tailor: bool = False) -> tuple[str, dict]:
    """The person's cv.md in `lang` (their own by default) and `expected` (what a reader should find in it): every
    expected value is a literal of the text. `tailor` writes what a tailor makes of it: a new summary, the first two
    bullets of the latest job merged with its start date after them, the oldest job, degree and second certification and
    the interests dropped, skills before experience, a skill named by a synonym, and the story bank's claim added."""
    lang = lang or person["lang"]
    pack, heads = _PACK[lang], _heads(person, lang)
    skills = [*person["tools"], pack["soft"][person["soft_i"]]]
    sections: dict[str, str] = {}
    entries: list[dict] = []
    levels: dict = {}
    part: dict[str, list[str]] = {}
    part["summary"] = [_EXTRA[lang]["summary2"] if tailor else pack["summary"].format(title=pack["roles"][2]), ""]
    lines = part["experience"] = []
    for i, job in enumerate(person["jobs"]):
        if tailor and i == 2:
            continue
        heading, entry = _entry(person, pack["roles"][job["role_i"]], job["org"], job["place"], job["start"], job["end"], i, lang)
        entries.append(entry)
        texts = [_BULLETS[lang][ix][0] for ix in job["bullets"]]
        if tailor and i == 0:
            merged = texts[0].rstrip(".") + "; " + texts[1][0].lower() + texts[1][1:]
            texts = [f"{merged.rstrip('.')} ({_when(person, job['start'], 0, lang)}).", texts[2]]
            texts += [_EXTRA[lang]["story_bullet"]] if person["story"] else []
        lines += [f"### {heading}", "", *[f"- {t}" for t in texts], ""]
    lines = part["education"] = []
    for i, ed in enumerate(person["education"]):
        if tailor and i == 0:
            continue
        heading, entry = _entry(person, pack["degrees"][ed["degree_i"]], ed["school"], ed["place"], ed["start"], ed["end"], i + 3, lang)
        entries.append(entry)
        lines += [f"### {heading}", ""]
    if person["skill_levels"]:
        part["skills"] = [f"- {_SYNONYM.get(s, s) if tailor else s} — {pack['skill_word']}" for s in skills] + [""]
        levels.update({s: None for s in skills})
    else:
        part["skills"] = [", ".join(_SYNONYM.get(s, s) if tailor else s for s in skills), ""]
    part["certifications"] = [f"- **{name}** — {year}" for name, year in person["certs"][:1 if tailor else 2]] + [""]
    lines = part["languages"] = []
    working = []
    for code, level in person["languages"]:
        name, cefr = pack["langs"][code], person["level_style"] == 1 and level != "native"
        word = CEFR[level] if cefr else pack["levels"][level]
        lines.append(f"- **{name}** ({word})" if cefr else (f"- **{name}** — {word}" if person["n"] % 3 else f"- {name}: {word}"))
        levels[name] = LEVEL_NUMBER[level]
        if LEVEL_NUMBER[level] >= 3:
            working.append(name)
    lines.append("")
    part["interests"] = [pack["interests"], ""]
    part["other"] = [pack["extra"], ""]
    order = ["summary", "skills", "experience", "education", "certifications", "languages"] if tailor else \
        ["summary", "experience", "education", "skills", "certifications", "languages", "interests", *(["other"] if person["extra"] else [])]
    block, contacts = _contact_block(person, pack["labels"])
    out = [f"# {person['name']}", "", f"> {pack['roles'][2]}", "", block, ""]
    for kind in order:
        sections[heads[kind]] = kind
        out += [f"## {heads[kind]}", "", *part[kind]]
    expected = {"name": person["name"], "email": person["email"], "city": person["city"], "country": pack["country"],
                "working_languages": sorted(working), "sections": sections, "contacts": contacts, "levels": levels,
                "skills": skills, "entries": entries}
    return "\n".join(out), expected


def render_body(person: dict, lang: str, *, reformat: bool = False) -> str:
    """The tailored CV in `lang` as a body in the tailor's vocabulary (`cv_body.body` on the reading `render_cv_md` expects: no model). `reformat` tells two
    figures of the first job another way (the same value: `40 000` as `40k`), which the CV backs."""
    md, expected = render_cv_md(person, lang, tailor=True)
    reading = {**cv_read._empty(), "sections": [{"heading": h, "kind": k} for h, k in expected["sections"].items()],
               "contacts": expected["contacts"], "entries": expected["entries"],
               "levels": [{"item": item, "level": level} for item, level in expected["levels"].items()]}
    body = cv_body.body(md, reading)
    if reformat:
        for ix in person["jobs"][0]["bullets"][:2]:
            _, anchor, same, _ = _BULLETS[lang][ix]
            body = body.replace(html.escape(anchor, quote=False), html.escape(same, quote=False), 1)
    return body


def render_letter(person: dict, lang: str) -> str:
    """The cover letter in `lang`: it echoes the posting, and says one thing of the latest job that the CV backs."""
    extra, job = _EXTRA[lang], person["jobs"][0]
    claim = _BULLETS[lang][job["bullets"][0]][0]
    e = lambda t: html.escape(t, quote=False)  # noqa: E731
    return (f'<header class="letter-header"><h1>{e(person["name"])}</h1>\n<p class="contact"><span class="phone">{person["phone"]}</span>'
            f'<span class="email"><a href="mailto:{person["email"]}">{person["email"]}</a></span><span class="location">{e(person["city"])}</span></p></header>\n'
            f'<div class="recipient"><p>{e(extra["recipient"])}</p><p>{e(extra.get("company", "Orchid Energy"))}</p></div>\n<p class="date"><<date>></p>\n'
            f'<p>{e(extra["greeting"])}</p>\n<p>{e(extra["echo"])}</p>\n<p>{e(job["org"])}: {e(claim)}</p>\n'
            f'<div class="closing"><p class="signoff">{e(extra["closing"])}</p><p>{e(person["name"])}</p></div>')


# --- planting fabrications --------------------------------------------------------------------------------------

def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def _insert_in_section(body: str, heading: str, snippet_ul: str, snippet_p: str) -> str:
    """Add to the end of the list or paragraph that follows `heading` (its `<h2>`)."""
    start = re.search(rf'<h2 class="kind-\w+">{re.escape(_esc(heading))}</h2>', body)
    start = start.start() if start else -1
    if start < 0:
        raise ValueError(f"no section {heading!r} to plant in")
    ul, p = body.find("</ul>", start), body.find("</p>", start)
    nxt = body.find("<h2", start + 1)
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


def plant(body: str, kind: str, person: dict, lang: str, pick: int, source: str) -> tuple[str, dict]:
    """`body` (the tailored CV in `lang`) with one fabrication of `kind` planted by an anchored replacement, and what
    was planted: `{kind, planted_value, quote, file}` (`quote` is a stretch of the new body's text). `source` is the
    CV it is made of, which a year is not taken from. Raises ValueError with no anchor."""
    pack, heads = _PACK[lang], _heads(person, lang)
    info = lambda value, quote: {"kind": kind, "planted_value": value, "quote": quote, "file": "cv"}  # noqa: E731
    if kind == "number":
        _, anchor, _, fake = _BULLETS[lang][person["jobs"][pick % 2]["bullets"][pick % 3]]
        return _swap(body, _esc(anchor), _esc(fake)), info(fake, fake)
    if kind == "year":
        job = person["jobs"][1]
        old = _dates(person, job["start"], job["end"], 1, lang)
        fake_year = next(y for y in (job["start"] - 2, job["start"] - 1, job["start"] - 3, job["start"] + 3) if str(y) not in source)
        new = old.replace(str(job["start"]), str(fake_year), 1)
        return _swap(body, _esc(old), _esc(new)), info(str(fake_year), new)
    if kind == "employer":
        fake = _FAKE_ORGS[pick % len(_FAKE_ORGS)]
        return _swap(body, _esc(person["jobs"][1]["org"]), _esc(fake)), info(fake, fake)
    if kind == "degree":
        fake = pack["fake_degrees"][pick % 2]
        return _swap(body, _esc(pack["degrees"][person["education"][1]["degree_i"]]), _esc(fake)), info(fake, fake)
    if kind == "skill":
        fake = _FAKE_SKILLS[pick % len(_FAKE_SKILLS)]
        return _insert_in_section(body, heads["skills"], f"<li>{fake}</li>", f", {fake}"), info(fake, fake)
    if kind == "certification":
        fake = _FAKE_CERTS[pick % len(_FAKE_CERTS)]
        return _insert_in_section(body, heads["certifications"], f"<li><strong>{fake}</strong></li>", f" {fake}"), info(fake, fake)
    raise ValueError(f"unknown kind {kind!r}")


def plant_letter(letter: str, kind: str, person: dict, lang: str, pick: int) -> tuple[str, dict]:
    """The cover letter with a `number` (the figure it tells of the latest job changed) or a `skill` (a sentence naming
    a tool the CV does not) planted, as `plant` does."""
    if kind == "number":
        _, anchor, _, fake = _BULLETS[lang][person["jobs"][0]["bullets"][0]]
        return _swap(letter, _esc(anchor), _esc(fake)), {"kind": kind, "planted_value": fake, "quote": fake, "file": "letter"}
    if kind == "skill":
        fake = _FAKE_SKILLS[pick % len(_FAKE_SKILLS)]
        sentence = _EXTRA[lang]["letter_skill"].format(x=fake)
        return (_swap(letter, '<div class="closing">', f'<p>{_esc(sentence)}</p>\n<div class="closing">'),
                {"kind": kind, "planted_value": fake, "quote": fake, "file": "letter"})
    raise ValueError(f"unknown letter kind {kind!r}")


# --- the two corpora ---------------------------------------------------------------------------------------------

def build_reader_corpus() -> dict:
    """The CVs the reader reads: `{name: {lang, md, expected}}` for the first 15 people (every language, every heading,
    contact and date style, levels in words and in CEFR, a level word outside the table, headings no word list knows)."""
    corpus = {}
    for person in PEOPLE[:15]:
        md, expected = render_cv_md(person)
        corpus[f"p{person['n']:02d}-{person['lang']}"] = {"lang": person["lang"], "md": md, "expected": expected}
    return corpus


def build_body_corpus() -> dict:
    """The cases of the fact check: `{name: {lang, body_lang, md, story, posting, body, letter, plants}}`. The first 20
    people's tailored documents carry one to three fabrications each (every kind, in the CV and, for two, in the letter);
    the other 8 are clean, with a figure told another way. Every other person has a story bank and every fourth a letter
    with its posting."""
    corpus, cursor = {}, 0
    for n, person in enumerate(PEOPLE):
        lang, blang = person["lang"], body_lang(person)
        md = render_cv_md(person)[0]
        body, letter, plants = render_body(person, blang, reformat=n >= 20), "", []
        if person["letter"]:
            letter = render_letter(person, blang)
        if n < 20:
            for c in range(1 + n % 3):
                body, info = plant(body, KINDS[(cursor + c) % len(KINDS)], person, blang, n + c, md)
                plants.append(info)
            cursor += 1 + n % 3
            if n in (4, 12):
                letter, info = plant_letter(letter, ("number", "skill")[n // 8], person, blang, n)
                plants.append(info)
        corpus[f"b{n:02d}-{lang}-{blang}"] = {
            "lang": lang, "body_lang": blang, "md": md, "story": STORY_BANK if person["story"] else "",
            "posting": _EXTRA[blang]["posting"] if person["letter"] else "", "body": body, "letter": letter, "plants": plants}
    return corpus


# --- the prompts ------------------------------------------------------------------------------------------------
# The reader's prompt and schema are `core/cv_read.py`'s (#430) and the facts check's `tailoring/facts.py`'s (#433): what is
# recorded here is what the app asks. The examples in them are made up (never a person or a text of the corpus) and each answers a miss of an earlier measurement; the
# history is in the issue.

AGENTS = {"reader": "cv-reader", "facts": "fact-checker"}   # the agent file of each task
PROMPTS = {
    "reader": claude_cli.prompt("cv-reader"),
    "facts": claude_cli.prompt("fact-checker"),
}

SCHEMAS = {
    "reader": cv_read.SCHEMA,
    "facts": facts.SCHEMA,
}

MODELS = ("haiku", "sonnet")


def case_input(task: str, case: dict) -> str:
    """What the model is shown for `case`."""
    if task == "reader":
        return f"CV:\n<<<\n{case['md']}\n>>>\n"
    return facts.input_text(case["md"], case["story"], case["posting"], case["body"], case["letter"])


def _key(task: str, case: dict) -> str:
    """Names the prompt and input an answer is for, so a record of other text is not read."""
    return hashlib.sha256((PROMPTS[task] + "\0" + case_input(task, case)).encode()).hexdigest()[:12]


def ask_case(task: str, model: str, case: dict):
    """One call to the model for `case`: the reader's answer (a dict) or the facts check's findings (a list).
    Plan quota through `claude_cli.ask`; the feature keys are the nearest existing ones (see the module's docstring)."""
    from door.core import claude_cli

    answer = claude_cli.ask(AGENTS[task], case_input(task, case), model=model, feature="cv_read" if task == "reader" else "facts",
                            schema=SCHEMAS[task], effort="low", timeout_s=240)
    return answer if task == "reader" else [f for f in answer.get("findings") or [] if isinstance(f, dict)]


# --- recorded answers and the report -----------------------------------------------------------------------------

RECORDED = REPO / "tests" / "tailoring" / "fixtures" / "cv_reading"


def _recorded_ok(path: Path, key: str | None = None) -> bool:
    """The record at `path` is an answer (not an error) and, when `key` is given, one of that prompt and input."""
    if not path.is_file():
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    return "answer" in data and (key is None or data.get("key") == key)


def load_recorded(model: str, task: str, corpus: dict, root: Path = RECORDED) -> dict:
    """`{case: [answer per run]}` from `<root>/<model>/<task>/<case>.<run>.json`; an error, or a record of another
    prompt or input, is `{"error"}` (a miss)."""
    folder = Path(root) / model / task
    answers = {}
    for case, data in corpus.items():
        runs = sorted(folder.glob(f"{case}.*.json"), key=lambda p: int(p.stem.rsplit(".", 1)[1]))
        if runs:
            answers[case] = [json.loads(p.read_text(encoding="utf-8"))["answer"] if _recorded_ok(p, _key(task, data))
                             else {"error": "failed, or recorded for another prompt or input"} for p in runs]
    return answers


def run(task: str, model: str, corpus: dict, *, runs: int = 3, root: Path = RECORDED, workers: int = 4) -> None:
    """Ask for every (case, run) with no recorded answer (an error, or a record of other text, is asked again) and
    record it as raw JSON with its key."""
    from concurrent.futures import ThreadPoolExecutor

    folder = Path(root) / model / task
    folder.mkdir(parents=True, exist_ok=True)

    def one(job):
        name, run_no = job
        try:
            record = {"key": _key(task, corpus[name]), "answer": ask_case(task, model, corpus[name])}
        except Exception as exc:  # noqa: BLE001 - a failed call is a miss to count, not a stop
            record = {"error": str(exc)[:300]}
        (folder / f"{name}.{run_no}.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        return name, run_no, "error" in record

    jobs = [(n, r) for n in sorted(corpus) for r in range(runs) if not _recorded_ok(folder / f"{n}.{r}.json", _key(task, corpus[n]))]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for name, run_no, failed in pool.map(one, jobs):
            print(f"{model} {task} {name}.{run_no}: {'ERROR' if failed else 'recorded'}", file=sys.stderr)


def summarize(task: str, answers: dict, corpus: dict) -> dict:
    """The numbers of one model on one task from `answers` (`{case: [answer per run]}`), with the verdict; `calls` is
    what every figure rests on (a case and a run each), a failed one a miss."""
    calls = sum(len(a) for a in answers.values())
    runs = max((len(a) for a in answers.values()), default=0)
    if task == "reader":
        total = {f: [0, 0] for f in READER_FIELDS}
        stretch = [0, 0]
        for case, runs_ in answers.items():
            for answer in runs_:
                for field, cell in score_reader(corpus[case]["expected"], answer).items():
                    total[field][0] += cell["hit"]
                    total[field][1] += cell["total"]
                hit, all_ = stretches(corpus[case]["md"], answer)
                stretch[0] += hit
                stretch[1] += all_
        fields = {f: (h / t if t else 0.0) for f, (h, t) in total.items()}
        return {"cases": len(answers), "runs": runs, "calls": calls, "fields": fields, "verdict": reader_verdict(fields),
                "stretches": stretch[0] / stretch[1] if stretch[1] else 0.0}
    kinds = {k: [0, 0] for k in KINDS}
    verbatim, false_clean, false_planted = [0, 0], [], []
    for case, runs_ in answers.items():
        c = corpus[case]
        for answer in runs_:
            score = score_facts(c["plants"], answer, c["body"], c["letter"])
            for kind, cell in score["per_kind"].items():
                kinds[kind][0] += cell["found"]
                kinds[kind][1] += cell["planted"]
            verbatim[0] += score["verbatim"][0]
            verbatim[1] += score["verbatim"][1]
            (false_planted if c["plants"] else false_clean).append(score["false_flags"])
    report = {
        "cases": len(answers), "runs": runs, "calls": calls, "per_kind": {k: h / t for k, (h, t) in kinds.items() if t},
        "planted": {k: t // max(runs, 1) for k, (_, t) in kinds.items() if t},
        "false_clean_max": max(false_clean, default=0), "false_clean_mean": sum(false_clean) / max(len(false_clean), 1),
        "false_planted_mean": sum(false_planted) / max(len(false_planted), 1),
        "verbatim": verbatim[0] / verbatim[1] if verbatim[1] else 1.0,
        "stable": stability(answers) if runs > 1 else None,
    }
    report["verdict"] = facts_verdict({**report, "stable": 1.0 if report["stable"] is None else report["stable"]})
    return report


def to_markdown(task: str, report: dict) -> str:
    """The report as a markdown table."""
    pct = lambda x: "n/a" if x is None else f"{100 * x:.1f}%"  # noqa: E731
    head = f"{report['cases']} cases, up to {report['runs']} runs each, {report['calls']} calls: verdict **{report['verdict']}**\n\n"
    if task == "reader":
        return (head + "| field | right |\n|---|---|\n" + "".join(f"| {f} | {pct(v)} |\n" for f, v in report["fields"].items()) +
                f"\nvalues that are a stretch of the CV: {pct(report['stretches'])} (the country is an ISO code and the levels are "
                "numbers, so neither can be; the country is scored apart and no verdict rests on it).\n")
    rows = "".join(f"| {k} | {pct(v)} | {report['planted'][k]} |\n" for k, v in report["per_kind"].items())
    return (head + "| kind | recall | planted per run |\n|---|---|---|\n" + rows +
            f"\nfalse flags: clean bodies max {report['false_clean_max']}, mean {report['false_clean_mean']:.2f}; planted bodies mean "
            f"{report['false_planted_mean']:.2f}. verbatim: {pct(report['verbatim'])}. stable: {pct(report['stable'])}.\n")


def main(argv: list[str] | None = None) -> None:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--task", choices=("reader", "facts"), required=True)
    ap.add_argument("--model", choices=MODELS, default="haiku")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--report", action="store_true", help="print the numbers of the recorded answers ")
    ap.add_argument("--held-out", action="store_true", help="the held-out corpus, recorded under its own folder (the prompts were not tuned on it)")
    args = ap.parse_args(argv)
    if args.held_out:
        with held_out():
            return _main(args, RECORDED / "held-out")
    _main(args, RECORDED)


def _main(args, root: Path) -> None:
    corpus = build_reader_corpus() if args.task == "reader" else build_body_corpus()
    if not args.report:
        run(args.task, args.model, corpus, runs=args.runs, root=root)
    else:
        print(to_markdown(args.task, summarize(args.task, load_recorded(args.model, args.task, corpus, root), corpus)))


if __name__ == "__main__":
    main()
