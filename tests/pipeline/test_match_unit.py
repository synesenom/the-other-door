"""Step 5, `match`: the passes once, then scoring, then the selection of matches."""

import json
from datetime import date

import pytest

from door.commands import match as match_cmd
from door.commands import scrape as scrape_cmd
from door.pipeline import match as match_step
from cli_utils import stub_match_result, write_list_posting
from pipeline_utils import posting


def run(env, **kw):
    return match_step._match_step_core(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir, **kw)


@pytest.fixture
def fakes(env, monkeypatch):
    f = type("Fake", (), {})()
    f.order = []
    f.scored = {}
    f.scores = {}  # job id -> the score this run gives it

    def score(jobs_dir):
        for path in (jobs_dir / "postings").glob("*/*/*.json"):
            data = json.loads(path.read_text())
            if data["id"] in f.scores:
                path.write_text(json.dumps({**data, "score": f.scores[data["id"]]}))

    def passes(candidates_dir, config, profile_dir):
        f.order.append(("passes", candidates_dir.name))
        return {"prefilter": {"available": True, "survived": 2}, "dedup": None, "language": None,
                "condense": None, "prescreen": {"available": True, "scored": 2, "kept": 1}, "surviving_paths": ["x"]}

    def match_core(*, jobs_dir, profile_dir):
        f.order.append("match")
        score(jobs_dir)
        return stub_match_result(jobs_dir, **f.scored)

    monkeypatch.setattr(scrape_cmd, "_scrape_passes", passes)
    monkeypatch.setattr(match_cmd, "_match_core", match_core)
    return f


def test_the_passes_run_over_today_before_the_postings_are_scored(env, fakes):
    block = run(env)
    assert fakes.order == [("passes", date.today().isoformat()), "match"]
    assert block["passes"]["prescreen"] == {"available": True, "scored": 2, "kept": 1}
    assert "surviving_paths" not in block["passes"]


def test_the_block_carries_the_scoring_result_and_the_selection(env, fakes):
    write_list_posting(env.jobs_dir, date.today().isoformat(), "jobindex", "job-top")
    write_list_posting(env.jobs_dir, date.today().isoformat(), "jobindex", "job-low")
    fakes.scores = {"job-top": 0.95, "job-low": 0.2}
    fakes.scored = {"scored": 3, "above_threshold": 1}

    block = run(env)

    assert block["step"] == "match" and block["scored"] == 3 and block["failed"] == [] and block["model"] == "haiku"
    assert block["new_above_threshold"] == ["job-top"]
    assert [(t["id"], t["score"]) for t in block["top"]] == [("job-top", 0.95)]
    assert block["summary"] == "3 scored, 1 above 0.65"


def test_only_the_matches_this_run_scored_are_new(env, fakes):
    """A match an earlier run found and the user has not acted on is not new again (#585)."""
    from datetime import timedelta

    earlier = (date.today() - timedelta(days=1)).isoformat()
    write_list_posting(env.jobs_dir, earlier, "jobindex", "job-old", score=0.9)
    write_list_posting(env.jobs_dir, date.today().isoformat(), "jobindex", "job-new")
    write_list_posting(env.jobs_dir, earlier, "jobindex", "job-left", company="Left")  # an interrupted run left it unscored
    fakes.scores = {"job-new": 0.8, "job-left": 0.7}

    block = run(env)

    assert sorted(block["new_above_threshold"]) == ["job-left", "job-new"]
    assert [t["id"] for t in block["top"]] == ["job-new", "job-left"]


def test_a_run_that_scored_nothing_has_no_new_matches(env, fakes):
    write_list_posting(env.jobs_dir, date.today().isoformat(), "jobindex", "job-old", score=0.9)
    block = run(env)
    assert block["new_above_threshold"] == [] and block["top"] == []


def test_failed_postings_are_listed_and_counted_in_the_summary(env, fakes):
    fakes.scored = {"scored": 1, "failed": ["job-x", "job-y"]}
    block = run(env)
    assert block["failed"] == ["job-x", "job-y"] and block["summary"].endswith(", 2 failed")


def test_a_day_with_nothing_written_still_has_a_directory_to_score(env, fakes):
    run(env)
    assert (env.jobs_dir / "postings" / date.today().isoformat()).is_dir()


def test_the_real_passes_condense_and_prescreen_what_the_other_steps_wrote(env, monkeypatch):
    path = write_list_posting(env.jobs_dir, date.today().isoformat(), "jobindex", "job-a",
                              description="We are looking for a data scientist who will join our team and work with Python.")
    monkeypatch.setattr(match_cmd, "_match_core", lambda **kw: stub_match_result(env.jobs_dir))
    run(env)
    data = json.loads(path.read_text())
    assert "description_condensed" in data and "prescreen_score" in data


def test_the_step_reports_itself_and_its_passes(env, fakes, progress_events):
    run(env)
    assert [(e.site, e.outcome) for e in progress_events if e.stage == "step"] == [("match", "start"), ("match", "done")]


def test_an_employer_with_a_posting_that_cleared_min_score_counts_as_relevant(env, fakes):
    from door.core import companies

    items = []
    companies.record(items, "Acme", feed=("lever", "acme"), status="followed", found_via="jobindex",
                     now="2026-01-01T00:00:00+00:00")
    companies.record(items, "Other", feed=("lever", "other"), status="followed", found_via="jobindex",
                     now="2026-01-01T00:00:00+00:00")
    companies.save(env.profile_dir, items)
    write_list_posting(env.jobs_dir, date.today().isoformat(), "lever", "job-a", score=0.9, company="Acme")
    write_list_posting(env.jobs_dir, date.today().isoformat(), "lever", "job-o", score=0.2, company="Other")

    run(env)

    got = {c.name: c.last_relevant for c in companies.load(env.profile_dir)}
    assert got["Acme"] is not None and got["Other"] is None


def test_a_copy_the_language_pass_drops_is_never_kept_as_the_original(env, monkeypatch):
    """Language runs before dedup: a board copy whose text is a scraped cookie banner (language
    unknown) must not win dedup and take the employer's readable copy down with it."""
    day = date.today().isoformat()
    junk = "Accept Close Dansk (Danmark) Deutsch (Deutschland) Ελληνικά (Ελλάδα) Español (España) Français (France)"
    board = write_list_posting(env.jobs_dir, day, "jobindex", "jobindex-novo-lds", company="Novo Nordisk",
                               title="Lead Data Scientist", description=junk)
    feed = write_list_posting(env.jobs_dir, day, "successfactors", "successfactors-novo-lds", company="Novo Nordisk",
                              title="Lead Data Scientist",
                              description="As Lead Data Scientist you will set the technical direction for AI, "
                                          "data science and machine learning in our supply chain team.")
    monkeypatch.setattr(match_cmd, "_match_core", lambda **kw: stub_match_result(env.jobs_dir))
    config = json.loads((env.profile_dir / "config.json").read_text())
    config.update(languages=["en"], dedup_source_priority=["jobindex"])  # the board would win dedup
    (env.profile_dir / "config.json").write_text(json.dumps(config))

    run(env)

    kept = json.loads(feed.read_text())
    assert kept.get("score_reason") != "duplicate" and not kept.get("duplicate_of")
    assert json.loads(board.read_text())["score_reason"].startswith("language")


def test_the_top_carries_location_and_english_title_and_no_ranks(env, fakes):
    write_list_posting(env.jobs_dir, date.today().isoformat(), "jobindex", "job-low", location="Aarhus")
    write_list_posting(env.jobs_dir, date.today().isoformat(), "jobindex", "job-top", title_en="Data Scientist")
    fakes.scores = {"job-low": 0.8, "job-top": 0.95}

    block = run(env)

    assert [(t["id"], t["location"]) for t in block["top"]] == [("job-top", "Copenhagen"), ("job-low", "Aarhus")]
    assert block["top"][0]["title_en"] == "Data Scientist"
    assert all("rank" not in t for t in block["top"])
    assert not (env.jobs_dir / "last_list.json").exists()


def test_a_match_on_a_shared_feed_counts_for_the_feed_entry(env, fakes):
    from door.core import companies

    items = []
    companies.record(items, "Statens Rekrutteringsløsning", feed=("hr_manager", "statensrekrutteringsloesning_tr"),
                     status="followed", found_via="jobindex", now="2026-01-01T00:00:00+00:00")
    companies.save(env.profile_dir, items)
    write_list_posting(env.jobs_dir, date.today().isoformat(), "hr_manager",
                       "hr_manager.statensrekrutteringsloesning_tr-9", score=0.9, company="Det Kongelige Bibliotek")

    run(env)

    assert companies.load(env.profile_dir)[0].last_relevant is not None


FRENCH = ("Nous recherchons un ingénieur de données pour rejoindre notre équipe à Paris. "
          "Vous travaillerez avec Python et SQL sur des projets variés pour nos clients, "
          "dans un environnement dynamique et convivial, avec de belles perspectives d'évolution.")


def test_postings_left_in_an_earlier_day_directory_go_through_the_passes_too(env, scorer):
    """A run that crosses midnight: search wrote into yesterday's directory, match runs today (#551)."""
    from datetime import timedelta

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    french = write_list_posting(env.jobs_dir, yesterday, "jobindex", "fr-1", description=FRENCH)
    english = write_list_posting(env.jobs_dir, yesterday, "jobindex", "en-1",
                                 description="We are looking for a data scientist who will join our team and work with Python.")

    block = run(env)

    assert scorer == ["en-1"]
    assert json.loads(french.read_text())["score"] == 0.0
    assert "language" in json.loads(english.read_text())
    assert block["passes"]["language"]["dropped"] == 1


def test_days_with_nothing_unscored_are_not_passed_again(env, monkeypatch):
    from datetime import timedelta

    old = (date.today() - timedelta(days=2)).isoformat()
    write_list_posting(env.jobs_dir, old, "jobindex", "done-1", score=0.8)
    seen = []
    monkeypatch.setattr(scrape_cmd, "_scrape_passes", lambda d, c, p: seen.append(d.name) or {"surviving_paths": []})
    monkeypatch.setattr(match_cmd, "_match_core", lambda **kw: stub_match_result(env.jobs_dir))
    run(env)
    assert seen == [date.today().isoformat()]
