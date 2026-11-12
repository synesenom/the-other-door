"""The tailor and reviewer agents keep their French rules (#389)."""

import re

from door.tailoring import tex_guard
from tests.paths import REPO_ROOT

AGENTS = REPO_ROOT / ".claude" / "agents"


def _french_section() -> str:
    text = (AGENTS / "tailor.md").read_text(encoding="utf-8")
    language = text.split("\n## Language", 1)[1].split("\n## ", 1)[0]
    assert "\n### French" in language, "tailor.md's Language section lost its French subsection"
    return language.split("\n### French", 1)[1].split("\n### ", 1)[0]


def test_tailor_keeps_the_french_letter_conventions():
    french = _french_section()
    for rule in ("Objet :", "Madame, Monsieur,", "le 29 octobre 2026", "salutations distinguées", r"\selectlanguage{french}"):
        assert rule in french, rule


def test_tailor_keeps_the_french_cv_and_typography_rules():
    french = _french_section()
    for rule in ("Expérience professionnelle", "Formation", "Compétences", "Langues", "Centres d'intérêt",
                 "courant", "bilingue", "« »", "non-breaking"):
        assert rule in french, rule


def test_the_latex_the_french_rules_tell_the_tailor_to_write_passes_the_tex_guard():
    for snippet in re.findall(r"`([^`]*\\[^`]*)`", _french_section()):
        assert tex_guard.unsafe(snippet) == [], snippet


def test_reviewer_checks_the_french_conventions():
    text = (AGENTS / "reviewer.md").read_text(encoding="utf-8")
    assert "French" in text.split("### 5. Tone", 1)[1].split("## Output format", 1)[0]
    assert "Objet" in text and "Madame, Monsieur" in text
