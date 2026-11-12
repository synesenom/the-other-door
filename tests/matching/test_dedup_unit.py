"""Unit tests for matching/dedup.py (issue #44).

Covers _normalise() and dedup() with synthetic JobPosting fixtures written to
tmp_path.  Pure and offline — no network, no LLM.
"""

from __future__ import annotations

import json
from pathlib import Path


from door.matching.dedup import _normalise, dedup


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_SCRAPED_AT = "2026-06-16T00:00:00+00:00"


def _write_posting(path: Path, **kwargs) -> Path:
    """Write a minimal posting JSON file and return the path."""
    defaults = dict(
        id="site-acme-data-scientist",
        title="Data Scientist",
        company="Acme",
        location="Copenhagen",
        url="https://example.com/1",
        description="Build models.",
        source="jobindex",
        scraped_at=_SCRAPED_AT,
    )
    defaults.update(kwargs)
    path.write_text(json.dumps(defaults, indent=2))
    return path


# --------------------------------------------------------------------------- #
# _normalise — legal suffix stripping and case
# --------------------------------------------------------------------------- #

def test_normalise_strips_as_suffix():
    key = _normalise("Novo Nordisk A/S", "Data Engineer")
    assert "a/s" not in key
    assert "novo nordisk" in key or "novonordisk" in key


def test_normalise_strips_ltd_suffix():
    key = _normalise("Widget Ltd", "Product Manager")
    assert "ltd" not in key


def test_normalise_removes_punctuation():
    key = _normalise("Acme, Inc.", "Data-Scientist!")
    # Should not contain standalone punctuation
    assert "," not in key
    assert "." not in key
    assert "!" not in key


# --------------------------------------------------------------------------- #
# _normalise — Danish transliteration
# --------------------------------------------------------------------------- #

def test_normalise_transliterates_danish_letters():
    assert _normalise("Ørsted", "Blæst Åland") == "oersted blaest aaland"


# --------------------------------------------------------------------------- #
# dedup — edge cases
# --------------------------------------------------------------------------- #

def test_dedup_empty_list_returns_empty():
    assert dedup([], {}) == []


# --------------------------------------------------------------------------- #
# dedup — duplicate detection + JSON rewrite
# --------------------------------------------------------------------------- #

def test_dedup_identical_normalised_key_collapses_to_one(tmp_path):
    """Two postings with the same normalised (company, title) → one survives."""
    p1 = _write_posting(tmp_path / "a.json",
                        id="jobindex-acme-data-scientist",
                        title="Data Scientist", company="Acme",
                        source="jobindex")
    p2 = _write_posting(tmp_path / "b.json",
                        id="thehub-acme-data-scientist",
                        title="Data Scientist", company="Acme",
                        source="thehub")
    result = dedup([p1, p2], {})
    assert len(result) == 1

    # The dropped one should be rewritten with duplicate markers
    survivors = set(result)
    dropped = p1 if p2 in survivors else p2
    dropped_data = json.loads(dropped.read_text())
    assert dropped_data["score"] == 0.0
    assert dropped_data["score_reason"] == "duplicate"
    assert "duplicate_of" in dropped_data
    assert dropped_data["duplicate_of"] is not None


def test_dedup_dropped_duplicate_of_references_kept_id(tmp_path):
    """The duplicate_of field in the dropped file must equal the kept posting's id."""
    p1 = _write_posting(tmp_path / "a.json",
                        id="jobindex-acme-data-scientist",
                        title="Data Scientist", company="Acme",
                        source="jobindex")
    p2 = _write_posting(tmp_path / "b.json",
                        id="thehub-acme-data-scientist",
                        title="Data Scientist", company="Acme",
                        source="thehub")
    result = dedup([p1, p2], {})
    kept = result[0]
    kept_data = json.loads(kept.read_text())
    kept_id = kept_data["id"]

    dropped = p1 if p2 == kept else p2
    dropped_data = json.loads(dropped.read_text())
    assert dropped_data["duplicate_of"] == kept_id


# --------------------------------------------------------------------------- #
# dedup — source priority
# --------------------------------------------------------------------------- #

def test_dedup_source_priority_keeps_preferred_source(tmp_path):
    """When two postings have no score, dedup_source_priority determines the winner."""
    p1 = _write_posting(tmp_path / "a.json",
                        id="jobindex-acme-ds",
                        title="Data Scientist", company="Acme",
                        source="jobindex")
    p2 = _write_posting(tmp_path / "b.json",
                        id="thehub-acme-ds",
                        title="Data Scientist", company="Acme",
                        source="thehub")
    config = {"dedup_source_priority": ["thehub", "jobindex"]}
    result = dedup([p1, p2], config)
    assert len(result) == 1
    kept_data = json.loads(result[0].read_text())
    assert kept_data["source"] == "thehub"


def test_dedup_higher_score_wins_over_source_priority(tmp_path):
    """When one posting has a higher score, it is kept regardless of priority."""
    p1 = _write_posting(tmp_path / "a.json",
                        id="jobindex-acme-ds",
                        title="Data Scientist", company="Acme",
                        source="jobindex", score=0.9)
    p2 = _write_posting(tmp_path / "b.json",
                        id="thehub-acme-ds",
                        title="Data Scientist", company="Acme",
                        source="thehub", score=0.5)
    # Even though thehub is preferred, jobindex has a higher score
    config = {"dedup_source_priority": ["thehub", "jobindex"]}
    result = dedup([p1, p2], config)
    assert len(result) == 1
    kept_data = json.loads(result[0].read_text())
    assert kept_data["source"] == "jobindex"


# --------------------------------------------------------------------------- #
# dedup — graceful handling of bad JSON
# --------------------------------------------------------------------------- #

def test_dedup_skips_posting_missing_id(tmp_path):
    """A posting JSON without an 'id' field is skipped gracefully."""
    p1 = tmp_path / "bad.json"
    p1.write_text(json.dumps({"title": "X", "company": "Y"}))  # no 'id'
    p2 = _write_posting(tmp_path / "good.json",
                        id="jobindex-acme-ds",
                        title="Data Scientist", company="Acme")
    result = dedup([p1, p2], {})
    # p1 has no 'id' so it is skipped; p2 survives
    assert p2 in result


# --------------------------------------------------------------------------- #
# dedup — similarity threshold defaults to exact match (1.0)
# --------------------------------------------------------------------------- #

def test_dedup_default_threshold_is_exact_match(tmp_path):
    """With default threshold (1.0), near-similar but not identical keys both survive."""
    p1 = _write_posting(tmp_path / "a.json",
                        id="jobindex-acme-senior-data-scientist",
                        title="Senior Data Scientist", company="Acme",
                        source="jobindex")
    p2 = _write_posting(tmp_path / "b.json",
                        id="thehub-acme-data-scientist",
                        title="Data Scientist", company="Acme",
                        source="thehub")
    result = dedup([p1, p2], {})
    # Titles differ → both survive
    assert len(result) == 2


def test_dedup_collapses_two_links_to_the_same_hr_manager_project(tmp_path):
    """Jobindex's copy of an HR-Manager ad and the feed's own posting differ in
    company ("Rigshospitalet" vs "Region Hovedstaden") but share the project (#228)."""
    p1 = _write_posting(tmp_path / "a.json", id="jobindex.rigshospitalet.sygeplejerske", title="Sygeplejerske",
                        company="Rigshospitalet", source="jobindex",
                        apply_url="https://candidate.hr-manager.net/ApplicationInit.aspx?cid=342&ProjectId=270627&DepartmentId=1&MediaId=4630")
    p2 = _write_posting(tmp_path / "b.json", id="hr_manager.region-hovedstaden.sygeplejerske", title="Sygeplejerske!",
                        company="Region Hovedstaden", source="hr_manager",
                        url="https://candidate.hr-manager.net/ApplicationInit.aspx?cid=342&ProjectId=270627&DepartmentId=18836&MediaId=5")
    p3 = _write_posting(tmp_path / "c.json", id="hr_manager.region-hovedstaden.laege", title="Læge",
                        company="Region Hovedstaden", source="hr_manager",
                        url="https://candidate.hr-manager.net/ApplicationInit.aspx?cid=342&ProjectId=999&MediaId=5")

    assert sorted(dedup([p1, p2, p3], {})) in ([p1, p3], [p2, p3])


def test_hr_manager_project_key():
    from door.matching.dedup import _project_key

    assert _project_key("https://candidate.hr-manager.net/ApplicationInit.aspx?cid=342&projectid=270627&MediaId=5") == "hr-manager:342:270627"
    assert _project_key("https://example.com/jobs/1") is None
    assert _project_key("") is None


# --------------------------------------------------------------------------- #
# LinkedIn and board copies of an employer-feed ad (they dedupe like any other source)
# --------------------------------------------------------------------------- #

def test_a_linkedin_or_board_copy_and_the_employer_feed_posting_are_one_job(tmp_path):
    feed = _write_posting(tmp_path / "a.json", id="greenhouse.novo-nordisk-a-s.lead-data-scientist",
                          source="greenhouse", company="Novo Nordisk A/S", title="Lead Data Scientist")
    li = _write_posting(tmp_path / "b.json", id="linkedin.novo-nordisk.lead-data-scientist",
                        source="linkedin", company="Novo Nordisk", title="Lead Data Scientist")
    board = _write_posting(tmp_path / "c.json", id="jobindex.novo-nordisk.lead-data-scientist",
                           source="jobindex", company="Novo Nordisk", title="Lead Data Scientist")

    kept = dedup([li, board, feed], {"dedup_source_priority": ["greenhouse", "linkedin", "jobindex"]})

    assert kept == [feed]
    assert json.loads(li.read_text())["duplicate_of"] == "greenhouse.novo-nordisk-a-s.lead-data-scientist"
    assert json.loads(board.read_text())["score_reason"] == "duplicate"


def test_the_employers_own_copy_wins_over_a_board_copy_without_a_configured_priority(tmp_path):
    # Jobindex first in encounter order; Novo Nordisk's own feed copy must still be kept.
    board = _write_posting(tmp_path / "a.json", id="jobindex.novo-nordisk.lead-data-scientist",
                           source="jobindex", company="Novo Nordisk", title="Lead Data Scientist",
                           description="Accept cookies. Dansk Deutsch English Español Français")
    feed = _write_posting(tmp_path / "b.json", id="successfactors.novo-nordisk.lead-data-scientist",
                          source="successfactors", company="Novo Nordisk", title="Lead Data Scientist",
                          description="As Lead Data Scientist, you will set the technical direction for AI.")

    kept = dedup([board, feed], {})

    assert kept == [feed]
    assert json.loads(board.read_text())["duplicate_of"] == "successfactors.novo-nordisk.lead-data-scientist"


def test_a_configured_source_priority_still_beats_the_employer_copy(tmp_path):
    board = _write_posting(tmp_path / "a.json", id="jobindex.acme.ds", source="jobindex")
    feed = _write_posting(tmp_path / "b.json", id="greenhouse.acme.ds", source="greenhouse")
    assert dedup([board, feed], {"dedup_source_priority": ["jobindex"]}) == [board]


def test_names_of_one_followed_employer_are_one_company(tmp_path):
    """companies.json knows "Flugger" (its SuccessFactors feed) is also "Flügger group A/S"
    (Jobindex's name): their copies of one ad are one job."""
    feed = _write_posting(tmp_path / "a.json", id="successfactors.flugger.ai-martech-lead",
                          source="successfactors", company="Flugger", title="AI & MarTech Lead")
    board = _write_posting(tmp_path / "b.json", id="jobindex.flugger-group-a-s.ai-martech-lead",
                           source="jobindex", company="Flügger group A/S", title="AI & MarTech Lead")

    assert len(dedup([feed, board], {})) == 2
    assert dedup([feed, board], {}, aliases=[["Flugger", "Flügger group A/S"]]) == [feed]


# --------------------------------------------------------------------------- #
# earlier postings: an ad seen on an earlier day is the original of a new copy
# --------------------------------------------------------------------------- #

def test_a_new_copy_of_an_earlier_posting_is_its_duplicate_and_the_earlier_one_is_untouched(tmp_path):
    earlier = _write_posting(tmp_path / "manual.json", id="manual.wpp.data-scientist-team-lead", company="WPP",
                             title="Data Scientist Team Lead", source="manual", score=0.8)
    before = earlier.read_text()
    new = _write_posting(tmp_path / "gh.json", id="greenhouse.wpp.data-scientist-team-lead", company="WPP",
                         title="Data Scientist Team Lead", source="greenhouse", score=0.85)
    other = _write_posting(tmp_path / "other.json", id="greenhouse.wpp.data-engineer", company="WPP",
                           title="Data Engineer", source="greenhouse")

    kept = dedup([new, other], {}, earlier=[earlier])

    assert kept == [other]
    marked = json.loads(new.read_text())
    assert marked["duplicate_of"] == "manual.wpp.data-scientist-team-lead" and marked["score_reason"] == "duplicate"
    assert earlier.read_text() == before  # the earlier one wins whatever the scores, and is never rewritten


def test_an_earlier_posting_that_was_itself_a_duplicate_is_no_original(tmp_path):
    earlier = _write_posting(tmp_path / "old.json", id="jobindex-acme-ds", duplicate_of="lever-acme-ds")
    new = _write_posting(tmp_path / "new.json", id="thehub-acme-ds", source="thehub")
    assert dedup([new], {}, earlier=[earlier]) == [new]
    assert json.loads(new.read_text()).get("duplicate_of") is None
