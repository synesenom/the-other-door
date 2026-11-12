"""Unit tests for matching/prefilter.py (issue #15).

All tests are offline/pure — no network, no scraper calls.
The prefilter function reads JSON files from disk, applies exclusion rules,
writes score=0.0/score_reason="excluded" for dropped postings, and returns
a list of Path objects for surviving postings.
"""

import json
from pathlib import Path

import pytest

from door.matching.prefilter import prefilter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_POSTING = {
    "id": "test-acme-engineer",
    "title": "Software Engineer",
    "company": "Acme Corp",
    "location": "Copenhagen",
    "url": "https://example.com/job/1",
    "description": "A great engineering role.",
    "source": "jobindex",
    "scraped_at": "2026-06-14T00:00:00Z",
}


def _write_posting(directory: Path, posting: dict, filename: str = "posting.json") -> Path:
    """Write a posting dict to a JSON file and return its path."""
    path = directory / filename
    path.write_text(json.dumps(posting))
    return path


def _make_site_dir(jobs_dir: Path, site: str = "jobindex") -> Path:
    """Create a site subdirectory under jobs_dir (mimics candidates_dir/<site>/)."""
    site_dir = jobs_dir / site
    site_dir.mkdir(parents=True, exist_ok=True)
    return site_dir


def _read_posting(path: Path) -> dict:
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _config(
    location: str = "Copenhagen",
    remote: str = "hybrid",
    exclude_companies: list | None = None,
    exclude_keywords: list | None = None,
) -> dict:
    return {
        "location": location,
        "remote": remote,
        "exclude": {
            "companies": exclude_companies or [],
            "keywords": exclude_keywords or [],
        },
    }


# ---------------------------------------------------------------------------
# Empty candidates_dir → returns []
# ---------------------------------------------------------------------------

def test_empty_dir_returns_empty(tmp_path):
    """prefilter on an empty candidates_dir returns an empty list."""
    result = prefilter(tmp_path, _config())
    assert result == []


# ---------------------------------------------------------------------------
# Excluded company
# ---------------------------------------------------------------------------

def test_excluded_company_writes_score_zero(tmp_path):
    """Dropped company posting is rewritten with score=0.0 and score_reason='excluded'."""
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "company": "BadCorp"})
    config = _config(exclude_companies=["BadCorp"])

    prefilter(tmp_path, config)
    data = _read_posting(path)
    assert data["score"] == 0.0
    assert data["score_reason"] == "excluded"


def test_excluded_company_case_insensitive(tmp_path):
    """Company exclusion is case-insensitive."""
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "company": "badcorp"})
    config = _config(exclude_companies=["BadCorp"])

    surviving = prefilter(tmp_path, config)
    assert path not in surviving


# ---------------------------------------------------------------------------
# Excluded keywords
# ---------------------------------------------------------------------------

def test_excluded_keyword_in_title_is_dropped(tmp_path):
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "title": "Unpaid Data Fellowship"})

    surviving = prefilter(tmp_path, _config(exclude_keywords=["unpaid"]))
    assert path not in surviving


def test_an_excluded_keyword_only_in_the_description_does_not_drop_the_ad(tmp_path):
    """ROCKWOOL's "AI Team Lead" leads "data scientists ... and student assistants": an
    exclude keyword "student" is about the role, so only the title is checked (the
    scorer still sees exclude.keywords and the whole ad)."""
    site_dir = _make_site_dir(tmp_path)
    posting = {**_BASE_POSTING, "title": "AI Team Lead",
               "description": "You lead a team of AI engineers, data scientists and student assistants."}
    path = _write_posting(site_dir, posting)

    surviving = prefilter(tmp_path, _config(exclude_keywords=["student"]))
    assert path in surviving


def test_excluded_keyword_case_insensitive(tmp_path):
    """Keyword exclusion is case-insensitive."""
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "title": "INTERN DATA ANALYST"})
    config = _config(exclude_keywords=["intern"])

    surviving = prefilter(tmp_path, config)
    assert path not in surviving


def test_excluded_keyword_matches_whole_words_only(tmp_path):
    """"intern" must not drop an ad about an international or internal team."""
    site_dir = _make_site_dir(tmp_path)
    posting = {**_BASE_POSTING, "title": "International Data Lead, internal tools"}
    path = _write_posting(site_dir, posting)

    surviving = prefilter(tmp_path, _config(exclude_keywords=["intern"]))
    assert path in surviving


def test_excluded_keyword_with_a_star_matches_a_prefix(tmp_path):
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "title": "Internship in Data"})

    surviving = prefilter(tmp_path, _config(exclude_keywords=["internsh*"]))
    assert path not in surviving


_DANISH_INTERN_AD = (
    "Vi søger en analytiker til vores team for intern kommunikation. Du skal "
    "arbejde med data og have erfaring med Python, og du er god til at samarbejde."
)


def test_a_false_friend_keyword_is_not_applied_to_an_ad_in_that_language(tmp_path):
    """Danish "intern" means "internal": an English "intern" exclude keyword
    must not drop a Danish ad that says "intern kommunikation"."""
    site_dir = _make_site_dir(tmp_path)
    posting = {**_BASE_POSTING, "title": "Analytiker til intern kommunikation", "description": _DANISH_INTERN_AD}
    path = _write_posting(site_dir, posting)

    surviving = prefilter(tmp_path, _config(exclude_keywords=["intern"]))
    assert path in surviving


def test_a_false_friend_keyword_still_applies_to_an_english_ad(tmp_path):
    site_dir = _make_site_dir(tmp_path)
    posting = {
        **_BASE_POSTING,
        "title": "Data Intern",
        "description": "We are looking for an intern who will join our team and work with data.",
    }
    path = _write_posting(site_dir, posting)

    surviving = prefilter(tmp_path, _config(exclude_keywords=["intern"]))
    assert path not in surviving


# ---------------------------------------------------------------------------
# Location filtering
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("location", ["2300 København S", "Frederiksberg C", "Hørsholm", "Rungsted Kyst"])
def test_a_local_name_of_the_profile_city_survives(tmp_path, location):
    """Danish boards give Danish place names; "Copenhagen" must still match them."""
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": location})

    surviving = prefilter(tmp_path, _config(location="Copenhagen", remote="no"))
    assert path in surviving


def test_the_english_name_matches_a_danish_profile_city(tmp_path):
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": "Copenhagen, Denmark"})

    surviving = prefilter(tmp_path, _config(location="København", remote="no"))
    assert path in surviving


def test_another_danish_city_is_still_dropped(tmp_path):
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": "Aarhus C"})

    surviving = prefilter(tmp_path, _config(location="Copenhagen", remote="no"))
    assert path not in surviving


def test_a_danish_work_from_home_location_survives(tmp_path):
    site_dir = _make_site_dir(tmp_path)
    posting = {**_BASE_POSTING, "location": "Roskilde og mulighed for hjemmearbejde"}
    path = _write_posting(site_dir, posting)

    surviving = prefilter(tmp_path, _config(location="Copenhagen", remote="no"))
    assert path in surviving


def test_empty_location_survives(tmp_path):
    """A posting with an empty location string is ambiguous — kept."""
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": ""})
    config = _config(location="Copenhagen", remote="no")

    surviving = prefilter(tmp_path, config)
    assert path in surviving


def test_remote_in_location_survives(tmp_path):
    """A posting whose location contains 'Remote' is kept regardless of profile city."""
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": "Remote - Europe"})
    config = _config(location="Copenhagen", remote="no")

    surviving = prefilter(tmp_path, config)
    assert path in surviving


def test_profile_location_in_posting_location_survives(tmp_path):
    """A posting location that contains the profile city is kept."""
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": "Greater Copenhagen Area"})
    config = _config(location="Copenhagen")

    surviving = prefilter(tmp_path, config)
    assert path in surviving


def test_profile_remote_hybrid_keeps_location_mismatch(tmp_path):
    """When profile remote='hybrid', even a different-city posting is kept (could be remote)."""
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": "Sydney, Australia"})
    config = _config(location="Copenhagen", remote="hybrid")

    surviving = prefilter(tmp_path, config)
    assert path in surviving


# ---------------------------------------------------------------------------
# Return values
# ---------------------------------------------------------------------------

def test_surviving_postings_not_modified(tmp_path):
    """Surviving postings are not rewritten (no score/score_reason injected)."""
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, _BASE_POSTING)
    config = _config()

    prefilter(tmp_path, config)
    data = _read_posting(path)
    assert "score" not in data
    assert "score_reason" not in data


# ---------------------------------------------------------------------------
# Recursive glob (two-level dir structure)
# ---------------------------------------------------------------------------

def test_recursive_glob_finds_files_in_subdirs(tmp_path):
    """prefilter finds JSON files two levels deep (candidates_dir/<site>/<id>.json)."""
    site1_dir = _make_site_dir(tmp_path, "jobindex")
    site2_dir = _make_site_dir(tmp_path, "thehub")
    p1 = _write_posting(site1_dir, {**_BASE_POSTING, "id": "j1", "company": "A"})
    p2 = _write_posting(site2_dir, {**_BASE_POSTING, "id": "j2", "company": "B"})
    config = _config()

    surviving = prefilter(tmp_path, config)
    assert p1 in surviving
    assert p2 in surviving


def test_multiple_postings_partial_exclusion(tmp_path):
    """Only the excluded posting is dropped; others survive."""
    site_dir = _make_site_dir(tmp_path)
    p_good = _write_posting(site_dir, {**_BASE_POSTING, "company": "GoodCorp"}, "good.json")
    p_bad = _write_posting(site_dir, {**_BASE_POSTING, "company": "BadCorp"}, "bad.json")
    config = _config(exclude_companies=["BadCorp"])

    surviving = prefilter(tmp_path, config)
    assert p_good in surviving
    assert p_bad not in surviving


# ---------------------------------------------------------------------------
# Missing exclude config keys (graceful defaults)
# ---------------------------------------------------------------------------

def test_missing_exclude_key_does_not_crash(tmp_path):
    """prefilter works when 'exclude' is absent from config."""
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, _BASE_POSTING)
    config = {"location": "Copenhagen", "remote": "no"}  # no "exclude" key

    surviving = prefilter(tmp_path, config)
    assert path in surviving


# ---------------------------------------------------------------------------
# Hungary (country/hu.toml)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("location", ["Budapest", "Budapest XI. ker.", "Budaörs", "Törökbálint", "Gödöllő", "Pest_megye"])
def test_a_hungarian_name_of_budapest_survives(tmp_path, location):
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": location})

    surviving = prefilter(tmp_path, _config(location="Budapest, Hungary", remote="no"))
    assert path in surviving


def test_another_hungarian_city_is_dropped_for_a_budapest_profile(tmp_path):
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": "Debrecen"})

    assert path not in prefilter(tmp_path, _config(location="Budapest", remote="no"))


def test_a_posting_in_another_country_is_dropped_for_a_budapest_profile(tmp_path):
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": "Vienna, Austria"})

    assert path not in prefilter(tmp_path, _config(location="Budapest", remote="no"))


@pytest.mark.parametrize("location", ["Pécs", "Pecs", "Pécs, Baranya"])
def test_a_second_hungarian_city_works_the_same_way(tmp_path, location):
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": location})

    assert path in prefilter(tmp_path, _config(location="Pécs", remote="no"))
    other = _write_posting(site_dir, {**_BASE_POSTING, "location": "Győr"}, "other.json")
    assert other not in prefilter(tmp_path, _config(location="Pécs", remote="no"))


def test_hungarian_seniority_words_map_to_canonical_levels():
    from door import i18n

    levels = i18n.seniority_words(("hu",))
    assert levels["senior*"] == "senior"
    assert levels["junior*"] == "junior"
    assert levels["gyakornok*"] == "junior"
    assert levels["vezető"] == "manager"
    assert levels["osztályvezető"] == "manager"
    assert levels["igazgató*"] == "head"


# ---------------------------------------------------------------------------
# The commute area (#429)
# ---------------------------------------------------------------------------


def _survives(tmp_path, location: str, remote: str = "no") -> bool:
    site_dir = tmp_path / "jobindex"
    site_dir.mkdir(exist_ok=True)
    _write_posting(site_dir, {**_BASE_POSTING, "location": location})
    return bool(prefilter(tmp_path, _config(location="Copenhagen", remote=remote)))


@pytest.mark.parametrize("location", ["Hillerød", "Roskilde", "4600 Køge", "Rigshospitalet", "Hovedkontoret"])
def test_on_site_profile_keeps_the_commute_area_and_unknown_workplaces(tmp_path, location):
    assert _survives(tmp_path, location)


@pytest.mark.parametrize("location", ["Aarhus", "Odense C", "Aalborg", "Berlin, Germany", "Stockholm"])
def test_on_site_profile_drops_a_known_place_outside_the_commute_area(tmp_path, location):
    assert not _survives(tmp_path, location)


@pytest.mark.parametrize("location", ["Aarhus", "Berlin, Germany", "Hillerød", "Rigshospitalet"])
def test_hybrid_profile_keeps_every_location(tmp_path, location):
    assert _survives(tmp_path, location, remote="hybrid")


# --- #432 ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("location", ["Home-based", "Home based, Kenya", "Hjemmebaseret", "Homebased (Uganda)"])
def test_a_home_based_location_survives_for_a_profile_who_wants_local_work(location):
    from door.matching.prefilter import _is_location_compatible
    assert _is_location_compatible(location, _config(location="Copenhagen", remote="no"))


# ---------------------------------------------------------------------------
# France (country/fr.toml)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("location", [
    "Paris", "75 - Paris 8e Arrondissement", "92 - Puteaux", "La Défense", "Île-de-France", "Ile-de-France",
    "Boulogne-Billancourt", "93 - Montreuil", "Nanterre",
])
def test_a_french_name_of_paris_survives(tmp_path, location):
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": location})

    assert path in prefilter(tmp_path, _config(location="Paris, France", remote="no"))


@pytest.mark.parametrize("location", ["Lyon", "Berlin, Germany", "Copenhagen"])
def test_another_city_or_country_is_dropped_for_a_paris_profile(tmp_path, location):
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": location})

    assert path not in prefilter(tmp_path, _config(location="Paris", remote="no"))


@pytest.mark.parametrize("location", ["Lyon", "69 - Lyon 3e Arrondissement", "Villeurbanne", "Rhône"])
def test_a_second_french_city_works_the_same_way(tmp_path, location):
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": location})

    assert path in prefilter(tmp_path, _config(location="Lyon", remote="no"))
    other = _write_posting(site_dir, {**_BASE_POSTING, "location": "Paris"}, "other.json")
    assert other not in prefilter(tmp_path, _config(location="Lyon", remote="no"))


def test_the_commute_area_of_paris_survives_for_an_on_site_profile(tmp_path):
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": "91 - Palaiseau"})

    assert path in prefilter(tmp_path, _config(location="Paris", remote="no"))


_FRENCH_STAGE_AD = (
    "Nous recherchons un chef de projet pour notre équipe parisienne. Vous pilotez le stage de conception "
    "avec les équipes techniques et vous présentez les résultats à la direction chaque mois."
)


def test_a_false_friend_keyword_is_not_applied_to_a_french_ad(tmp_path):
    """French "stage" is a phase of a project (or an internship) and "chef" a lead: an English exclude keyword
    spelled the same must not drop a French ad."""
    site_dir = _make_site_dir(tmp_path)
    posting = {**_BASE_POSTING, "location": "Paris", "title": "Chef de projet H/F", "description": _FRENCH_STAGE_AD}
    path = _write_posting(site_dir, posting)

    assert path in prefilter(tmp_path, _config(location="Paris", exclude_keywords=["chef", "stage"]))


# ---------------------------------------------------------------------------
# Sweden (country/se.toml)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("location", [
    "Stockholm", "Stockholms län", "Stockholm C", "Solna", "Sundbyberg", "Kista", "Lidingö", "Lidingo",
    "Södertälje", "Sodertalje", "Täby", "Järfälla",
])
def test_a_swedish_name_of_stockholm_survives(tmp_path, location):
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": location})

    assert path in prefilter(tmp_path, _config(location="Stockholm, Sweden", remote="no"))


@pytest.mark.parametrize("location", ["Göteborg", "Oslo, Norway", "Berlin, Germany"])
def test_another_city_or_country_is_dropped_for_a_stockholm_profile(tmp_path, location):
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": location})

    assert path not in prefilter(tmp_path, _config(location="Stockholm", remote="no"))


@pytest.mark.parametrize("profile", ["Göteborg", "Gothenburg", "Goteborg, Sweden"])
@pytest.mark.parametrize("location", ["Göteborg", "Gothenburg", "Mölndal", "Molndal", "Partille", "Västra Götaland"])
def test_a_second_swedish_city_works_the_same_way(tmp_path, profile, location):
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": location})
    other = _write_posting(site_dir, {**_BASE_POSTING, "location": "Malmö"}, "other.json")

    surviving = prefilter(tmp_path, _config(location=profile, remote="no"))
    assert path in surviving and other not in surviving


@pytest.mark.parametrize("location", ["Lund", "Limhamn", "Skåne", "Malmo"])
def test_a_third_swedish_city_keeps_its_area(tmp_path, location):
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": location})

    assert path in prefilter(tmp_path, _config(location="Malmö", remote="no"))


@pytest.mark.parametrize("location, kept", [("Norrtälje", True), ("Uppsala", True), ("Örebro", False), ("Göteborg", False)])
def test_an_on_site_stockholm_profile_keeps_the_commute_area(tmp_path, location, kept):
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": location})

    assert (path in prefilter(tmp_path, _config(location="Stockholm", remote="no"))) is kept


def test_swedish_seniority_words_map_to_canonical_levels():
    from door import i18n

    levels = i18n.seniority_words(("sv",))
    assert levels["senior*"] == "senior"
    assert levels["junior*"] == "junior"
    assert levels["praktikant*"] == "junior"
    assert levels["teamledare"] == "manager"
    assert levels["enhetschef"] == "manager"
    assert levels["chef"] == "head"
    assert levels["lektor"] == "academic"


# ---------------------------------------------------------------------------
# United Kingdom (country/gb.toml)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("location", [
    "London", "Greater London", "London W2 1NY", "Canary Wharf", "Croydon", "City of London", "Westminster",
    "London, UK", "Remote, UK",
])
def test_a_british_name_of_london_survives(tmp_path, location):
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": location})

    assert path in prefilter(tmp_path, _config(location="London, United Kingdom", remote="no"))


@pytest.mark.parametrize("location", ["Dublin, Ireland", "Paris, France", "New York, NY"])
def test_another_country_is_dropped_for_a_london_profile(tmp_path, location):
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": location})

    assert path not in prefilter(tmp_path, _config(location="London", remote="no"))


@pytest.mark.parametrize("location", ["Manchester", "Salford", "Greater Manchester", "MediaCity"])
def test_a_second_british_city_works_the_same_way(tmp_path, location):
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": location})
    other = _write_posting(site_dir, {**_BASE_POSTING, "location": "Glasgow"}, "other.json")

    surviving = prefilter(tmp_path, _config(location="Manchester, UK", remote="no"))
    assert path in surviving and other not in surviving


@pytest.mark.parametrize("location, kept", [("Guildford", True), ("Reading", True), ("Leeds", False), ("Dublin", False)])
def test_an_on_site_london_profile_keeps_the_commute_area(tmp_path, location, kept):
    site_dir = _make_site_dir(tmp_path)
    path = _write_posting(site_dir, {**_BASE_POSTING, "location": location})

    assert (path in prefilter(tmp_path, _config(location="London", remote="no"))) is kept
