"""Unit tests for matching/condense.py (issue #143).

Pure/offline: exercises split_sections, condense_description, and
extract_skill_terms directly on hand-written Danish/English descriptions
and the saved Jobindex fixture detail page text. No network, no LLM.
"""

import pytest

from door.matching.condense import (
    condense_description,
    extract_skill_terms,
    split_sections,
)
from paths import TESTS_DIR

_FIXTURES = TESTS_DIR / "scrapers" / "boards" / "fixtures"  # saved real Jobindex pages


# ---------------------------------------------------------------------------
# split_sections
# ---------------------------------------------------------------------------

def test_split_sections_splits_on_colon_heading():
    text = "Intro sentence.\n\nRequirements:\nMust have 5 years experience."
    sections = split_sections(text)
    headings = [h for h, _ in sections]
    assert "Requirements" in headings


def test_split_sections_keeps_intro_before_first_heading():
    text = "This is the intro.\n\nRequirements:\nMust have Python."
    sections = split_sections(text)
    assert sections[0][0] == ""
    assert "intro" in sections[0][1].lower()


def test_split_sections_detects_all_caps_heading():
    text = "Intro sentence.\n\nREQUIREMENTS\nMust know SQL."
    sections = split_sections(text)
    headings = [h for h, _ in sections]
    assert "REQUIREMENTS" in headings


# ---------------------------------------------------------------------------
# condense_description — hand-written English description
# ---------------------------------------------------------------------------

_ENGLISH_DESCRIPTION = """We are a growing analytics team building forecasting tools for the business.

Responsibilities:
You will design and maintain machine learning pipelines.
You will collaborate with engineering and product on data-driven features.

Requirements:
5+ years of experience with Python and SQL is required.
You must be fluent in English.
Danish is a plus but not required.

Location: Copenhagen, hybrid work arrangement available.
Salary: 55.000-65.000 kr. per month depending on experience.

About us:
We are a friendly, diverse workplace with free lunch and great coffee.

Benefits:
We offer a pension plan, free parking and a health insurance package.

Equal opportunity:
We are committed to diversity and are an equal opportunity employer.

How to apply:
Send your CV and cover letter through our application portal.
"""


def test_condense_removes_about_us_and_benefits():
    result = condense_description(_ENGLISH_DESCRIPTION, keep_terms=set())
    assert "free lunch" not in result.lower()
    assert "pension plan" not in result.lower()


def test_condense_keeps_requirement_sentences():
    result = condense_description(_ENGLISH_DESCRIPTION, keep_terms=set())
    assert "5+ years of experience with python and sql is required" in result.lower()
    assert "you must be fluent in english" in result.lower()


def test_condense_keeps_salary_and_remote_lines():
    result = condense_description(_ENGLISH_DESCRIPTION, keep_terms=set())
    assert "kr." in result.lower()
    assert "hybrid" in result.lower()


# ---------------------------------------------------------------------------
# condense_description — hand-written Danish description
# ---------------------------------------------------------------------------

_DANISH_DESCRIPTION = """Vi søger en erfaren udvikler til vores team i vækst.

Krav:
Dansk er et krav for denne stilling, både skriftligt og mundtligt.
Du har mindst 3 års erfaring med Python.

Om os:
Vi er en hyggelig arbejdsplads med gratis frokost og kaffe.

Vi tilbyder:
Pensionsordning, sundhedsforsikring og gratis parkering.
"""


def test_condense_keeps_danish_language_requirement_without_skill_term():
    # "dansk er et krav" contains no term from keep_terms, but must survive
    # because it's a language requirement always-keep pattern.
    result = condense_description(_DANISH_DESCRIPTION, keep_terms={"java", "kubernetes"})
    assert "dansk er et krav" in result.lower()


def test_condense_drops_danish_about_us_and_benefits():
    result = condense_description(_DANISH_DESCRIPTION, keep_terms=set())
    assert "gratis frokost" not in result.lower()
    assert "pensionsordning" not in result.lower()


# Danish headings that are neither colon-terminated nor Title Case (Danish
# capitalises only the first word), or that end in a question mark.
_DANISH_UNMARKED_HEADINGS = """Vi søger en dataforsker til vores team.
Det er et spændende job.
Om stillingen
Du skal bygge modeller i produktion.
Hvem er du?
Du har erfaring med Python og statistik.
Om virksomheden
Vi har kontorer i hele landet og skal vokse med 200 ansatte i år.
"""


@pytest.mark.parametrize("heading", ["Om stillingen", "Hvem er du"])
def test_split_sections_detects_unmarked_danish_headings(heading):
    headings = [h for h, _ in split_sections(_DANISH_UNMARKED_HEADINGS)]
    assert heading in headings


def test_condense_ranks_hvem_er_du_as_requirements_and_drops_om_virksomheden():
    result = condense_description(_DANISH_UNMARKED_HEADINGS, keep_terms=set())
    assert "Hvem er du\nDu har erfaring med Python og statistik." in result
    assert "Om virksomheden" not in result


def test_a_question_that_is_not_a_known_heading_stays_body_text():
    text = "Intro.\nKan du lide data?\nDu har erfaring med SQL."
    assert [h for h, _ in split_sections(text)] == [""]


# ---------------------------------------------------------------------------
# max_chars truncation
# ---------------------------------------------------------------------------

def test_condense_respects_max_chars():
    long_text = _ENGLISH_DESCRIPTION * 20
    result = condense_description(long_text, keep_terms=set(), max_chars=500)
    assert len(result) <= 500


def test_condense_truncation_prefers_requirements_over_responsibilities():
    # With a very small budget, the requirement sentence should survive
    # while the (lower-priority) responsibilities content is cut.
    result = condense_description(_ENGLISH_DESCRIPTION, keep_terms=set(), max_chars=250)
    assert "fluent in english" in result.lower() or "required" in result.lower()


# ---------------------------------------------------------------------------
# Idempotency and determinism
# ---------------------------------------------------------------------------

def test_condense_is_idempotent():
    once = condense_description(_ENGLISH_DESCRIPTION, keep_terms={"python"})
    twice = condense_description(once, keep_terms={"python"})
    assert once == twice


def test_condense_empty_text_returns_empty():
    assert condense_description("", keep_terms=set()) == ""


# ---------------------------------------------------------------------------
# Against the real Jobindex fixture detail page text
# ---------------------------------------------------------------------------

def _jobindex_description_text() -> str:
    """Extract the same plain-text description the jobindex scraper would produce."""
    from bs4 import BeautifulSoup

    html = (_FIXTURES / "jobindex" / "detail_h1673146.html").read_text()
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find("section", class_="read-more-container")
    return container.get_text(separator="\n", strip=True)


def test_condense_shrinks_real_fixture_substantially():
    text = _jobindex_description_text()
    result = condense_description(text, keep_terms={"data scientist", "python", "sql"})
    assert len(result) < len(text) * 0.6


def test_condense_drops_benefits_from_real_fixture():
    text = _jobindex_description_text()
    result = condense_description(text, keep_terms=set())
    assert "gratis parkering" not in result.lower()
    assert "fysioterapi" not in result.lower()


def test_condense_keeps_danish_language_clause_from_real_fixture():
    text = _jobindex_description_text()
    result = condense_description(text, keep_terms=set())
    assert "dansk" in result.lower()


# ---------------------------------------------------------------------------
# extract_skill_terms
# ---------------------------------------------------------------------------

_CV_MD = """# Jane Doe

## Profile

Experienced data scientist.

## Skills

Python (scikit-learn, pytorch, pandas), SQL, AWS, Spark, data visualization (d3, matplotlib), Docker, Git.

## Languages

- English — fluent
"""


def test_extract_skill_terms_includes_cv_skills():
    terms = extract_skill_terms(_CV_MD, {})
    assert "python" in terms
    assert "sql" in terms
    assert "docker" in terms


def test_extract_skill_terms_excludes_short_tokens():
    terms = extract_skill_terms(_CV_MD, {})
    assert "d3" not in terms  # < 3 chars


def test_extract_skill_terms_includes_role_targets_and_search_keywords():
    config = {
        "role_targets": ["Lead Data Scientist"],
        "search_keywords": ["machine learning manager"],
    }
    terms = extract_skill_terms(_CV_MD, config)
    assert "lead data scientist" in terms
    assert "machine learning manager" in terms


def test_extract_skill_terms_is_lowercase_and_deduplicated():
    config = {"role_targets": ["Python Developer", "python developer"]}
    terms = extract_skill_terms(_CV_MD, config)
    assert sum(1 for t in terms if t == "python developer") == 1


def test_extract_skill_terms_without_a_cv_still_has_the_role_targets():
    terms = extract_skill_terms("", {"role_targets": ["Data Engineer"]})
    assert "data engineer" in terms


_SALARY_IN_DANISH = "Intro one.\nIntro two.\n\nDetails\nLøn efter aftale.\nWe like coffee."


def test_condense_keeps_a_marker_in_the_ads_own_language():
    assert "Løn efter aftale." in condense_description(_SALARY_IN_DANISH, language="da")


def test_condense_ignores_another_languages_markers():
    """A Danish salary word is no marker in an English ad."""
    assert "Løn" not in condense_description(_SALARY_IN_DANISH, language="en")


def test_condense_without_a_language_uses_every_language():
    assert "Løn efter aftale." in condense_description(_SALARY_IN_DANISH)


def test_condense_postings_scopes_each_posting_to_its_language(tmp_path):
    import json

    from door.matching.condense import condense_postings

    paths = []
    for code in ("da", "en"):
        p = tmp_path / f"{code}.json"
        p.write_text(json.dumps({"id": code, "description": _SALARY_IN_DANISH, "language": code}))
        paths.append(p)
    condense_postings(paths, set(), {})
    da, en = (json.loads(p.read_text())["description_condensed"] for p in paths)
    assert "Løn" in da and "Løn" not in en


# ---------------------------------------------------------------------------
# Hungarian (hu.toml)
# ---------------------------------------------------------------------------

_HUNGARIAN_DESCRIPTION = """Adatelemzőt keresünk budapesti csapatunkba.

Elvárások:
A magyar nyelv ismerete elvárás, szóban és írásban egyaránt.
Legalább 3 év tapasztalat Pythonnal.

Amit kínálunk:
Ingyenes kávé, gyümölcs és céges telefon.

Rólunk:
Dinamikusan növekvő cég vagyunk, irodánk a belvárosban van.

Fizetés: bruttó 900 000 - 1 200 000 Ft/hó.
"""


def test_condense_keeps_hungarian_requirements_and_salary_and_drops_offers():
    result = condense_description(_HUNGARIAN_DESCRIPTION, keep_terms=set(), language="hu")
    assert "3 év tapasztalat" in result
    assert "900 000" in result
    assert "ingyenes kávé" not in result.lower()
    assert "dinamikusan növekvő" not in result.lower()


_HUNGARIAN_UNMARKED = """Adatmérnököt keresünk a csapatunkba.
Ez egy izgalmas lehetőség.
A pozícióról
Adatfolyamokat építesz éles környezetben.
Milyen vagy?
Van tapasztalatod Pythonnal és SQL-lel.
A cégről
Irodáink az egész országban vannak, és idén 200 új kollégát veszünk fel.
"""


def test_hungarian_headings_are_found_without_a_colon():
    headings = [h for h, _ in split_sections(_HUNGARIAN_UNMARKED)]
    assert "Milyen vagy?" in headings or "A pozícióról" in headings
    result = condense_description(_HUNGARIAN_UNMARKED, keep_terms=set(), language="hu")
    assert "A cégről" not in result


def test_condense_keeps_a_hungarian_language_requirement_without_skill_term():
    text = "Intro egy.\nIntro kettő.\n\nRészletek\nMagyar nyelvtudás elvárás.\nKávét főzünk."
    result = condense_description(text, keep_terms={"java"}, language="hu")
    assert "magyar nyelvtudás elvárás" in result.lower() or "elvárás" in result.lower()


# ---------------------------------------------------------------------------
# French (fr.toml)
# ---------------------------------------------------------------------------

_FRENCH_DESCRIPTION = """Nous recherchons un chef de projet data pour notre équipe parisienne.

Profil recherché :
Vous avez 5 ans d’expérience minimum en gestion de projet.
Le français courant est exigé, l'anglais est un plus.

Ce que nous offrons :
Des tickets restaurant, un café gratuit et une salle de sport.

Qui sommes-nous ?
Une entreprise en pleine croissance, présente dans toute la France.

Salaire : 55 000 € brut par an.
"""


def test_condense_keeps_french_requirements_and_salary_and_drops_offers():
    result = condense_description(_FRENCH_DESCRIPTION, keep_terms=set(), language="fr")
    assert "5 ans d’expérience" in result
    assert "55 000" in result
    assert "tickets restaurant" not in result.lower()
    assert "pleine croissance" not in result.lower()


_FRENCH_UNMARKED = """Nous cherchons un analyste de données pour notre équipe.
C'est une belle opportunité.
Vos missions
Vous construisez des tableaux de bord pour la direction.
Votre profil
Une première expérience en SQL est indispensable.
Avantages
Mutuelle prise en charge à 100 % et tickets restaurant.
Comment postuler
Envoyez votre CV avant la fin du mois.
"""


def test_french_headings_are_found_without_a_colon():
    headings = [h for h, _ in split_sections(_FRENCH_UNMARKED, "fr")]
    assert "Votre profil" in headings and "Avantages" in headings
    result = condense_description(_FRENCH_UNMARKED, keep_terms=set(), language="fr")
    assert "expérience en sql" in result.lower()
    assert "mutuelle" not in result.lower()
    assert "envoyez votre cv" not in result.lower()


def test_a_french_remote_line_is_kept_even_under_a_dropped_heading():
    text = "Intro une.\nIntro deux.\n\nAvantages\nMutuelle à 100 %.\nTélétravail deux jours par semaine.\n"
    result = condense_description(text, keep_terms={"java"}, language="fr")
    assert "Télétravail deux jours" in result and "Mutuelle" not in result


def test_a_french_salary_line_with_k_euros_and_a_language_requirement_are_kept():
    text = "Intro une.\nIntro deux.\n\nDétails\nRémunération : 38 k€ brut annuel.\nMaîtrise du français exigée.\nCafé offert."
    result = condense_description(text, keep_terms={"java"}, language="fr")
    assert "38 k€" in result and "français" in result.lower()
    assert "café offert" not in result.lower()


# ---------------------------------------------------------------------------
# Work permit sentences are always kept (#326)
# ---------------------------------------------------------------------------

def _long_ad(sentence: str, heading: str = "") -> str:
    filler = "\n".join(f"Vi arbejder med ting nummer {i} hver dag." for i in range(60))
    mid = f"{heading}\n{sentence}\n" if heading else f"{sentence}\n"
    return filler + "\n" + mid + filler


@pytest.mark.parametrize(
    "sentence,language",
    [
        ("We are unable to offer visa sponsorship for this role.", "en"),
        ("We are unable to offer visa sponsorship for this role.", None),
        ("Vi kan ikke tilbyde sponsorering af arbejdstilladelse.", "da"),
        ("Vi kan ikke tilbyde sponsorering af arbejdstilladelse.", None),
        ("We are unable to offer visa sponsorship for this role.", "da"),
        ("Visa sponsorship is available.", "en"),
        ("EU work permit required", "en"),
    ],
)
def test_work_permit_sentence_survives_condensing(sentence, language):
    out = condense_description(_long_ad(sentence), max_chars=300, language=language)
    assert sentence in out


def test_work_permit_sentence_kept_inside_a_dropped_section():
    sentence = "We are unable to offer visa sponsorship for this role."
    out = condense_description(_long_ad(sentence, heading="Benefits:"), max_chars=300, language="en")
    assert sentence in out


def _over_budget_ad(sentence: str, heading: str) -> str:
    requirements = "\n".join(f"- You must have experience with tool number {i} in production." for i in range(80))
    return f"Requirements:\n{requirements}\n\n{heading}\n- Build pipelines every day.\n- {sentence}\n"


@pytest.mark.parametrize("heading", ["Responsibilities:", "How to apply:"])
def test_work_permit_sentence_outranks_requirements_under_the_cap(heading):
    sentence = "We are unable to offer visa sponsorship for this role."
    out = condense_description(_over_budget_ad(sentence, heading), max_chars=3000, language="en")
    assert len(out) <= 3000
    assert sentence in out


def test_work_permit_sentence_kept_once():
    sentence = "We are unable to offer visa sponsorship for this role."
    out = condense_description(f"Intro line.\nSecond line.\n\nResponsibilities:\n- {sentence}\n", language="en")
    assert out.count(sentence) == 1


# ---------------------------------------------------------------------------
# Sweden (lang/sv.toml)
# ---------------------------------------------------------------------------

_SWEDISH_DESCRIPTION = """Vi söker en erfaren utvecklare till vårt team i tillväxt.

Krav:
Svenska i tal och skrift är ett krav för tjänsten.
Du har minst 3 års erfarenhet av Python.
Månadslön 45 000 kr.

Om oss:
Vi är en trevlig arbetsplats med gratis frukt och kaffe.

Vi erbjuder:
Friskvårdsbidrag, tjänstepension och gratis parkering.
"""


def test_condense_keeps_swedish_requirements_and_salary_and_drops_offers():
    result = condense_description(_SWEDISH_DESCRIPTION, keep_terms=set(), language="sv")
    assert "3 års erfarenhet" in result
    assert "45 000" in result
    assert "gratis frukt" not in result.lower()
    assert "tjänstepension" not in result.lower()


def test_condense_keeps_a_swedish_language_requirement_without_skill_term():
    result = condense_description(_SWEDISH_DESCRIPTION, keep_terms={"java", "kubernetes"})
    assert "svenska i tal och skrift" in result.lower()


_SWEDISH_UNMARKED = """Vi söker en dataingenjör till vårt team.
Det här är en spännande möjlighet.
Om tjänsten
Du bygger dataflöden i en skarp miljö.
Vem är du?
Du har erfarenhet av Python och SQL.
Om företaget
Vi har kontor över hela landet och anställer 200 nya kollegor i år.
"""


def test_swedish_headings_are_found_without_a_colon():
    headings = [h for h, _ in split_sections(_SWEDISH_UNMARKED)]
    assert "Vem är du?" in headings or "Om tjänsten" in headings
    result = condense_description(_SWEDISH_UNMARKED, keep_terms=set(), language="sv")
    assert "Om företaget" not in result and "200 nya kollegor" not in result


_SWEDISH_SALARY = "Intro ett.\nIntro två.\n\nDetaljer\nLön enligt överenskommelse.\nVi gillar kaffe."


def test_condense_keeps_a_swedish_salary_marker_in_a_swedish_ad_only():
    assert "Lön enligt överenskommelse." in condense_description(_SWEDISH_SALARY, language="sv")
    assert "Lön" not in condense_description(_SWEDISH_SALARY, language="en")


@pytest.mark.parametrize("sentence", [
    "Vi kan inte erbjuda visumsponsring för den här tjänsten.",
    "Giltigt arbetstillstånd i Sverige krävs.",
    "We are unable to offer visa sponsorship for this role.",
])
@pytest.mark.parametrize("language", ["sv", None])
def test_swedish_work_permit_sentence_survives_condensing(sentence, language):
    out = condense_description(_long_ad(sentence), max_chars=300, language=language)
    assert sentence in out


@pytest.mark.parametrize("heading", ["## Skills", "## Technical Skills", "## Kompetencer", "## Compétences", "## **Skills:**"])
def test_extract_skill_terms_reads_a_skills_section_under_any_of_its_names(heading):
    assert "pandas" in extract_skill_terms(f"# Jane\n\n{heading}\n\npandas, Spark\n\n## Profile\n\nNotpandas person\n", {})


def test_extract_skill_terms_reads_every_skills_section_and_nothing_else():
    terms = extract_skill_terms("## Skills\n\npandas\n\n## Profile\n\nleadership\n\n## Tools\n\nSpark\n", {})
    assert {"pandas", "spark"} <= terms
    assert "leadership" not in terms


def test_extract_skill_terms_without_a_skills_section_has_only_the_profile_terms():
    assert extract_skill_terms("## Profile\n\npandas\n", {"role_targets": ["Analyst"]}) == {"analyst"}


@pytest.mark.parametrize("sentence", [
    "You must have the right to work in the UK.",
    "Applicants must hold SC clearance.",
    "Enhanced DBS check required.",
    "We hold a sponsor licence and can offer a certificate of sponsorship.",
    "Sorry, sponsorship is not available for this vacancy.",
    "We are not able to provide sponsorship for this role.",
])
@pytest.mark.parametrize("language", ["en", None])
def test_british_work_permit_sentence_survives_condensing(sentence, language):
    out = condense_description(_long_ad(sentence), max_chars=300, language=language)
    assert sentence in out


def test_condense_keeps_a_british_salary_line():
    ad = "Intro one.\nIntro two.\n\nDetails\nSalary: GBP 45,000 per annum, pro rata.\nWe like tea."
    assert "per annum" in condense_description(ad, language="en")
