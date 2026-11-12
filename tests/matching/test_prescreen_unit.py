"""Unit tests for matching/prescreen.py (issue #143).

Pure/offline: exercises prescreen_score and prescreen directly against
JSON files on disk. No network, no LLM.
"""

import json
from pathlib import Path

import pytest

from door.matching.prescreen import _seniority_match, prescreen, prescreen_score


_BASE_POSTING = {
    "id": "test-acme-engineer",
    "title": "Lead Data Scientist",
    "company": "Acme Corp",
    "location": "Copenhagen",
    "url": "https://example.com/job/1",
    "description": "A great role.",
    "description_condensed": "A great role.",
    "source": "jobindex",
    "scraped_at": "2026-06-14T00:00:00Z",
}


def _config(**overrides) -> dict:
    base = {
        "role_targets": ["Lead Data Scientist"],
        "location": "Copenhagen",
        "remote": "hybrid",
        "prescreen_top_n": 40,
        "prescreen_min": 0.15,
    }
    base.update(overrides)
    return base


def _write_posting(directory: Path, posting: dict, filename: str) -> Path:
    path = directory / filename
    path.write_text(json.dumps(posting))
    return path


# ---------------------------------------------------------------------------
# prescreen_score
# ---------------------------------------------------------------------------

def test_exact_title_match_scores_higher_than_partial():
    config = _config()
    exact = {**_BASE_POSTING, "title": "Lead Data Scientist"}
    partial = {**_BASE_POSTING, "title": "Data Entry Clerk"}

    score_exact = prescreen_score(exact, set(), config)
    score_partial = prescreen_score(partial, set(), config)
    assert score_exact > score_partial


def test_full_skill_overlap_outranks_no_overlap():
    config = _config()
    profile_terms = {"python", "sql", "machine learning"}
    rich = {
        **_BASE_POSTING,
        "description_condensed": "Requires Python, SQL, and machine learning experience.",
    }
    poor = {**_BASE_POSTING, "description_condensed": "Requires woodworking and welding."}

    score_rich = prescreen_score(rich, profile_terms, config)
    score_poor = prescreen_score(poor, profile_terms, config)
    assert score_rich > score_poor


@pytest.mark.parametrize(
    "title, target",
    [
        ("Seniorudvikler", "Senior Developer"),
        ("Ledende dataforsker", "Lead Data Scientist"),
    ],
)
def test_seniority_matches_across_languages_and_compounds(title, target):
    assert _seniority_match(title, [target]) == 1.0


@pytest.mark.parametrize(
    "title, target",
    [
        ("Postdoc in Astrophysics", "Assistant Professor of Physics"),
        ("Adjunkt i fysik", "Postdoc in Physics"),
        ("Lektor i kvantefysik", "Assistant Professor of Physics"),
        ("Tenure-track Assistant Professor, Niels Bohr Institute", "Postdoc in Physics"),
        ("Professor of Experimental Physics", "Associate Professor"),
    ],
)
def test_any_academic_rank_matches_any_other(title, target):
    assert _seniority_match(title, [target], "da") == 1.0


def test_an_academic_rank_is_no_match_for_a_senior_target():
    assert _seniority_match("Professor of Physics", ["Senior Developer"]) == 0.0


def test_a_danish_seniority_word_mismatch_is_still_a_mismatch():
    assert _seniority_match("Juniorudvikler", ["Senior Developer"]) == 0.0


def test_the_english_title_counts_when_it_is_the_better_match():
    danish = {**_BASE_POSTING, "title": "Ledende dataforsker"}
    translated = {**danish, "title_en": "Lead Data Scientist"}
    assert prescreen_score(translated, set(), _config()) > prescreen_score(danish, set(), _config())
    assert prescreen_score(translated, set(), _config()) == pytest.approx(
        prescreen_score(_BASE_POSTING, set(), _config())
    )


def test_the_original_title_counts_when_it_is_the_better_match():
    """Danish role_targets: a translation must never make a Danish title worse."""
    config = _config(role_targets=["Ledende dataforsker"])
    danish = {**_BASE_POSTING, "title": "Ledende dataforsker"}
    translated = {**danish, "title_en": "Lead Data Scientist"}
    assert prescreen_score(translated, set(), config) == pytest.approx(
        prescreen_score(danish, set(), config)
    )


def test_incompatible_location_lowers_score():
    config = _config(location="Copenhagen", remote="no")
    compatible = {**_BASE_POSTING, "location": "Copenhagen"}
    incompatible = {**_BASE_POSTING, "location": "Sydney, Australia"}

    score_ok = prescreen_score(compatible, set(), config)
    score_bad = prescreen_score(incompatible, set(), config)
    assert score_ok > score_bad


# ---------------------------------------------------------------------------
# prescreen driver
# ---------------------------------------------------------------------------

def test_prescreen_writes_score_to_every_posting(tmp_path):
    config = _config(prescreen_top_n=10, prescreen_min=0.0)
    paths = [
        _write_posting(tmp_path, {**_BASE_POSTING, "id": f"p{i}"}, f"p{i}.json")
        for i in range(3)
    ]

    prescreen(paths, config, set())

    for p in paths:
        data = json.loads(p.read_text())
        assert "prescreen_score" in data


def test_prescreen_honours_top_n(tmp_path):
    config = _config(prescreen_top_n=2, prescreen_min=0.0)
    paths = []
    for i, title in enumerate(
        ["Lead Data Scientist", "Data Scientist", "Sales Associate", "Warehouse Worker"]
    ):
        p = _write_posting(
            tmp_path, {**_BASE_POSTING, "id": f"p{i}", "title": title}, f"p{i}.json"
        )
        paths.append(p)

    surviving = prescreen(paths, config, set())
    assert len(surviving) <= 2


def test_prescreen_honours_min_cutoff(tmp_path):
    config = _config(prescreen_top_n=40, prescreen_min=0.9)
    paths = [
        _write_posting(
            tmp_path,
            {**_BASE_POSTING, "id": "p0", "title": "Totally Unrelated Job", "location": "Mars"},
            "p0.json",
        )
    ]

    surviving = prescreen(paths, config, set())
    assert surviving == []


def test_prescreen_cut_postings_get_prescreen_reason(tmp_path):
    config = _config(prescreen_top_n=0, prescreen_min=0.0)
    path = _write_posting(
        tmp_path, {**_BASE_POSTING, "id": "p0", "title": "Customer Marketing Manager"}, "p0.json"
    )

    prescreen([path], config, set())

    data = json.loads(path.read_text())
    assert data["score"] == 0.0
    assert data["score_reason"].startswith("prescreen:")


def test_prescreen_empty_paths_returns_empty():
    assert prescreen([], _config(), set()) == []


def test_prescreen_surviving_postings_not_score_marked(tmp_path):
    config = _config(prescreen_top_n=10, prescreen_min=0.0)
    path = _write_posting(tmp_path, {**_BASE_POSTING, "id": "p0"}, "p0.json")

    surviving = prescreen([path], config, set())

    assert path in surviving
    data = json.loads(path.read_text())
    assert data.get("score") is None


def test_a_titles_seniority_is_read_in_the_ads_language():
    """Danish "chef" is a head of something; in an English title it is a cook."""
    assert _seniority_match("Chef", ["Head of Data"], language="da") == 1.0
    assert _seniority_match("Chef", ["Head of Data"], language="en") == 0.5


def test_role_targets_match_in_any_language():
    """The targets are the candidate's own words, whatever the ad's language."""
    assert _seniority_match("Head of Data", ["Data-chef"], language="en") == 1.0


def test_prescreen_reads_an_english_title_with_english_words_only():
    posting = {"title": "Chef", "language": "en", "description_condensed": "", "location": ""}
    config = {"role_targets": ["Head of Data"], "remote": "yes"}
    cook = prescreen_score(posting, set(), config)
    boss = prescreen_score({**posting, "language": "da"}, set(), config)
    assert cook < boss


@pytest.mark.parametrize(
    "title, target",
    [
        ("Stagiaire data H/F", "Junior Data Analyst"),
        ("Analyste de données junior (H/F)", "Junior Data Analyst"),
        ("Alternance - Assistant marketing F/H", "Junior Marketing Assistant"),
        ("Responsable data H/F", "Data Manager"),
        ("Directrice des opérations", "Head of Operations"),
        ("Ingénieur data senior H/F/X", "Senior Data Engineer"),
        ("Maître de conférences en informatique", "Postdoc in Computer Science"),
    ],
)
def test_french_seniority_words_match_the_canonical_levels(title, target):
    assert _seniority_match(title, [target], "fr") == 1.0


def test_a_french_chef_de_projet_is_no_head_and_confirme_is_no_level():
    assert _seniority_match("Chef de projet data H/F", ["Head of Data"], language="fr") == 0.5
    assert _seniority_match("Ingénieur data confirmé", ["Senior Data Engineer"], language="fr") == 0.5


@pytest.mark.parametrize("title", ["Szoftverfejlesztő", "Säljare", "Ingénieur logiciel", "Projektledare för IT"])
def test_a_title_with_letters_beyond_ascii_and_aeoa_is_whole_words(title):
    """#514: a word with ő, ä, é or ö is one token, so the title matches itself fully."""
    from door.matching import prescreen as prescreen_mod

    assert prescreen_mod._tokenize(title) == set(title.lower().split())
    assert prescreen_mod._title_similarity(title, [title]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# on-topic tier (issue #632)
# ---------------------------------------------------------------------------

_LEADERSHIP = dict(
    role_targets=["Head of Data Science", "Lead Data Scientist", "Data Science Manager"],
    topic_terms=["data*", "analytics", "AI", "machine learning"],
    languages=["en", "hu"],
    location="Copenhagen",
)


def _write_all(tmp_path: Path, titles: list[str], extra: dict | None = None) -> list[Path]:
    paths = []
    for i, title in enumerate(titles):
        posting = {**_BASE_POSTING, "id": f"p{i}", "title": title, **(extra or {})}
        paths.append(_write_posting(tmp_path, posting, f"p{i}.json"))
    return paths


def test_on_topic_leadership_titles_kept_over_off_topic_managers(tmp_path):
    on_topic = [
        "Data Scientist Maritime Logistics",
        "Global Advanced Analytics Lead",
        "AI Solution Lead",
        "Data Director CFO / PPC / CXT",
        "Director Marketing Data Enablement & Operations",
        "HealthCare Provider AI Lead",
    ]
    off_topic = ["Customer Marketing Manager", "Purchasing & Logistics Manager"]
    paths = _write_all(tmp_path, off_topic + on_topic)
    config = _config(**_LEADERSHIP, prescreen_top_n=2)

    kept = prescreen(paths, config, set())

    kept_titles = {json.loads(p.read_text())["title"] for p in kept}
    assert set(on_topic) <= kept_titles
    assert not kept_titles & set(off_topic)
    for p in paths[:2]:
        data = json.loads(p.read_text())
        assert data["score"] == 0.0
        assert data["score_reason"].startswith("prescreen:")


def test_on_topic_title_en_counts(tmp_path):
    paths = [
        _write_posting(
            tmp_path,
            {**_BASE_POSTING, "id": "a", "title": "Lead Data Scientist Manager"},
            "a.json",
        ),
        _write_posting(
            tmp_path,
            {**_BASE_POSTING, "id": "b", "title": "Afdelingsleder",
             "title_en": "Analytics Lead"},
            "b.json",
        ),
        _write_posting(
            tmp_path,
            {**_BASE_POSTING, "id": "c", "title": "Customer Marketing Manager"},
            "c.json",
        ),
    ]
    config = _config(**_LEADERSHIP, prescreen_top_n=1, prescreen_min=0.0)
    kept = prescreen(paths, config, set())
    assert paths[1] in kept
    assert paths[2] not in kept


def test_first_run_batch_keeps_every_on_topic(tmp_path):
    kinds = ["Lead", "Director", "Manager", "Head"]
    areas = ["Data", "Analytics", "AI", "Machine Learning", "Data Platform"]

    def titles(n_on):
        on = [
            f"{areas[i % 5]} {kinds[(i // 5) % 4]} {i}" for i in range(n_on)
        ]
        off = [f"Function{i} Manager" for i in range(300 - n_on)]
        return on, off

    for n_on, expected_off in [(60, 0), (10, 30)]:
        d = tmp_path / f"n{n_on}"
        d.mkdir()
        on, off = titles(n_on)
        paths = _write_all(d, off + on)
        config = _config(**_LEADERSHIP, prescreen_min=0.0)
        kept = prescreen(paths, config, set())
        kept_titles = [json.loads(p.read_text())["title"] for p in kept]
        assert set(on) <= set(kept_titles)
        assert len([t for t in kept_titles if t in set(off)]) == expected_off


def test_on_topic_below_min_is_cut(tmp_path):
    paths = _write_all(tmp_path, ["Data Wrangler"], {"location": "Tokyo"})
    config = _config(**_LEADERSHIP, prescreen_min=0.99)
    assert prescreen(paths, config, set()) == []
