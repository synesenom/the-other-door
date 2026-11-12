"""`list`: ranked, unapplied matches.

Split out of the former tests/test_door_cli.py (issue #15 onward); the shared
`cli_env` fixture is in tests/commands/conftest.py, helpers in tests/cli_utils.py.
"""

import json

from click.testing import CliRunner

from door.cli import cli
from cli_utils import result_text, write_list_posting


# --------------------------------------------------------------------------- #
# list (issue #67)
# --------------------------------------------------------------------------- #


def test_list_empty_state_shows_friendly_message(cli_env):
    result = CliRunner().invoke(cli, ["jobs"])
    assert result.exit_code == 0, result_text(result)
    assert "no matches" in result_text(result).lower()
    assert "`./door find`" in result_text(result)


def test_list_shows_matches_sorted_by_score_descending(cli_env):
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-mid", score=0.7, title="Mid Job")
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-top", score=0.95, title="Top Job")

    result = CliRunner().invoke(cli, ["jobs"])
    assert result.exit_code == 0, result_text(result)
    text = result_text(result)
    assert text.index("Top Job") < text.index("Mid Job")


def test_list_excludes_already_applied(cli_env):
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-applied", score=0.9, title="Applied Job")
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-new", score=0.9, title="New Job")

    import door.core.tracker as tracker_mod
    app_tracker = tracker_mod.ApplicationTracker(cli_env.jobs_dir / "applications.json")
    app_tracker.set_status("job-applied", "applied")
    app_tracker.save()

    result = CliRunner().invoke(cli, ["jobs"])
    assert result.exit_code == 0, result_text(result)
    text = result_text(result)
    assert "New Job" in text
    assert "Applied Job" not in text


def test_list_without_score_shows_everything_scored_above_zero(cli_env):
    # The config's min_score is the conversation's default (list_matches), not the shell's.
    config = json.loads((cli_env.profile_dir / "config.json").read_text())
    config["min_score"] = 0.8
    (cli_env.profile_dir / "config.json").write_text(json.dumps(config))

    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-low", score=0.1, title="Low Job")
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-zero", score=0.0, title="Dropped Job")
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-high", score=0.9, title="High Job")

    text = result_text(CliRunner().invoke(cli, ["jobs"]))

    assert "Low Job" in text
    assert "Dropped Job" not in text
    assert "2 matches scored above 0" in text


def test_list_score_flag_overrides_config(cli_env):
    config = json.loads((cli_env.profile_dir / "config.json").read_text())
    config["min_score"] = 0.8
    (cli_env.profile_dir / "config.json").write_text(json.dumps(config))

    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-below", score=0.7, title="Below Threshold")

    result = CliRunner().invoke(cli, ["jobs", "list", "--score", "0.5"])
    assert result.exit_code == 0, result_text(result)
    assert "Below Threshold" in result_text(result)


def test_list_score_flag_keeps_scores_greater_or_equal(cli_env):
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-a", score=0.9, title="Job A")
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-b", score=0.7, title="Job B")
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-c", score=0.69, title="Job C")

    text = result_text(CliRunner().invoke(cli, ["jobs", "list", "--score", "0.7"]))

    assert "Job A" in text
    assert "Job B" in text
    assert "Job C" not in text


def test_list_table_includes_expected_columns(cli_env):
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-abc", score=0.75, title="Data Scientist", company="Acme", location="Copenhagen")

    result = CliRunner().invoke(cli, ["jobs"])
    assert result.exit_code == 0, result_text(result)
    text = result_text(result)
    assert "Data Scientist" in text
    assert "Acme" in text
    assert "Copenhagen" in text
    assert "0.75" in text
    assert "job-abc" not in text


def test_list_shows_the_english_title_next_to_a_translated_one(cli_env):
    path = write_list_posting(
        cli_env.jobs_dir, "2026-07-01", "jobindex", "job-da", score=0.9, title="Ledende dataforsker"
    )
    data = json.loads(path.read_text())
    data["title_en"] = "Lead Data Scientist"
    path.write_text(json.dumps(data))

    result = CliRunner().invoke(cli, ["jobs"])
    assert result.exit_code == 0, result_text(result)
    lines = [line.strip(" │") for line in result_text(result).splitlines()]
    assert any("Ledende dataforsker" in line for line in lines)
    assert any("Lead Data Scientist" in line for line in lines)


def test_list_draws_each_score_as_a_bar(cli_env):
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-abc", score=0.7)

    result = CliRunner().invoke(cli, ["jobs"])

    assert result.exit_code == 0, result_text(result)
    assert "███████░░░ 0.70" in result_text(result)


def test_list_header_says_how_many_matches_clear_the_threshold(cli_env):
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-a", score=0.9)
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-b", score=0.8)

    result = CliRunner().invoke(cli, ["jobs", "list", "--score", "0.5"])

    assert "2 matches ≥ 0.50" in result_text(result)


def test_list_marks_postings_new_since_the_last_review(cli_env):
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-abc", score=0.9)
    review = cli_env.jobs_dir / "last_review.json"

    review.write_text(json.dumps({"reviewed_at": "2000-01-01T00:00:00Z"}))
    assert "✦" in result_text(CliRunner().invoke(cli, ["jobs"]))

    review.write_text(json.dumps({"reviewed_at": "2999-01-01T00:00:00Z"}))
    assert "✦" not in result_text(CliRunner().invoke(cli, ["jobs"]))


def test_list_before_any_review_marks_nothing(cli_env):
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-abc", score=0.9)

    assert "✦" not in result_text(CliRunner().invoke(cli, ["jobs"]))


def test_list_into_a_pipe_has_no_colour_codes(cli_env):
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-abc", score=0.9)

    assert "\x1b[" not in CliRunner().invoke(cli, ["jobs"]).output


def test_list_rows_do_not_show_the_job_id(cli_env):
    job_id = "jobindex.novo-nordisk.senior-machine-learning-engineer"
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", job_id, score=0.9, title="Senior Machine Learning Engineer")

    text = result_text(CliRunner().invoke(cli, ["jobs"]))

    assert job_id not in text and "jobindex." not in text
    assert any(line.strip().endswith("Senior Machine Learning Engineer · Acme · Copenhagen") for line in text.splitlines())


def test_list_fits_each_row_in_one_line(cli_env):
    path = write_list_posting(
        cli_env.jobs_dir, "2026-07-01", "jobindex", "job-long", score=0.6,
        title="Ledende dataforsker til evalueringsmetodik og kunstig intelligens",
        company="Danske Bank", location="Finland, København, Litauen, Polen, Sverige",
    )
    data = json.loads(path.read_text())
    data["title_en"] = "Lead Data Scientist for Evaluation Methodology and AI"
    path.write_text(json.dumps(data))
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-short", score=0.5)

    lines = result_text(CliRunner().invoke(cli, ["jobs"])).splitlines()
    rows = lines[lines.index(next(line for line in lines if "─" in line)) + 1:]
    first = next(i for i, line in enumerate(rows) if "0.60" in line)
    second = next(i for i, line in enumerate(rows) if "0.50" in line)

    assert second == first + 1  # one line per row, no id line, no blank line between rows
    assert "Ledende dataforsker" in rows[first] and rows[first].rstrip().endswith("…")


# --------------------------------------------------------------------------- #
# list --status
# --------------------------------------------------------------------------- #


def _set_statuses(jobs_dir, **statuses):
    import door.core.tracker as tracker_mod

    app_tracker = tracker_mod.ApplicationTracker(jobs_dir / "applications.json")
    for job_id, status in statuses.items():
        app_tracker.set_status(job_id.replace("_", "-"), status)
    app_tracker.save()


def test_list_status_shows_only_postings_with_that_status(cli_env):
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-applied", score=0.9, title="Applied Job")
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-dropped", score=0.9, title="Dropped Job")
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-fresh", score=0.9, title="Fresh Job")
    _set_statuses(cli_env.jobs_dir, job_applied="applied", job_dropped="discarded")

    result = CliRunner().invoke(cli, ["jobs", "list", "--status", "applied"])

    assert result.exit_code == 0, result_text(result)
    text = result_text(result)
    assert "Applied Job" in text
    assert "Dropped Job" not in text
    assert "Fresh Job" not in text


def test_list_status_new_is_the_default_listing(cli_env):
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-applied", score=0.9, title="Applied Job")
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-fresh", score=0.9, title="Fresh Job")
    _set_statuses(cli_env.jobs_dir, job_applied="applied")

    text = result_text(CliRunner().invoke(cli, ["jobs", "list", "--status", "unapplied"]))

    assert "Fresh Job" in text
    assert "Applied Job" not in text


def test_list_status_keeps_old_postings_and_low_scores(cli_env):
    # Your applications stay visible however old or low-scoring they are.
    write_list_posting(cli_env.jobs_dir, "2020-01-01", "jobindex", "job-old", score=0.1, title="Old Applied Job")
    _set_statuses(cli_env.jobs_dir, job_old="applied")

    assert "Old Applied Job" in result_text(CliRunner().invoke(cli, ["jobs", "list", "--status", "applied"]))


def test_list_status_rejects_an_unknown_status(cli_env):
    assert CliRunner().invoke(cli, ["jobs", "list", "--status", "bogus"]).exit_code == 2


def test_list_status_works_through_the_list_subcommand(cli_env):
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-applied", score=0.9, title="Applied Job")
    _set_statuses(cli_env.jobs_dir, job_applied="applied")

    assert "Applied Job" in result_text(CliRunner().invoke(cli, ["jobs", "list", "--status", "applied"]))


# --------------------------------------------------------------------------- #
# list --ongoing
# --------------------------------------------------------------------------- #


def test_list_ongoing_shows_every_status_still_in_play(cli_env):
    for job_id, title in [("job-prep", "Prepared Job"), ("job-app", "Applied Job"), ("job-int", "Interview Job"),
                          ("job-off", "Offer Job"), ("job-rej", "Rejected Job"), ("job-gho", "Ghosted Job"),
                          ("job-dis", "Dropped Job"), ("job-new", "Fresh Job")]:
        write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", job_id, score=0.9, title=title)
    _set_statuses(cli_env.jobs_dir, job_prep="prepared", job_app="applied", job_int="interview:technical", job_off="offer",
                  job_rej="rejected", job_gho="ghosted", job_dis="discarded")

    result = CliRunner().invoke(cli, ["jobs", "list", "--ongoing"])

    assert result.exit_code == 0, result_text(result)
    text = result_text(result)
    for shown in ("Prepared Job", "Applied Job", "Interview Job", "Offer Job"):
        assert shown in text
    for hidden in ("Rejected Job", "Ghosted Job", "Dropped Job", "Fresh Job"):
        assert hidden not in text


def test_list_ongoing_keeps_old_postings_and_low_scores(cli_env):
    write_list_posting(cli_env.jobs_dir, "2020-01-01", "jobindex", "job-old", score=0.1, title="Old Applied Job")
    _set_statuses(cli_env.jobs_dir, job_old="applied")

    assert "Old Applied Job" in result_text(CliRunner().invoke(cli, ["jobs", "list", "--ongoing"]))


def test_list_ongoing_cannot_be_combined_with_status(cli_env):
    result = CliRunner().invoke(cli, ["jobs", "list", "--ongoing", "--status", "applied"])

    assert result.exit_code != 0


def test_list_ongoing_shows_each_postings_status(cli_env):
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-app", score=0.9, title="Applied Job")
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-int", score=0.8, title="Interview Job")
    _set_statuses(cli_env.jobs_dir, job_app="applied", job_int="interview:technical")

    text = result_text(CliRunner().invoke(cli, ["jobs", "list", "--ongoing"]))

    assert "Status" in text and "applied" in text and "interview" in text


# --------------------------------------------------------------------------- #
# list --closed, and each row's date and interview rounds (the app's board)
# --------------------------------------------------------------------------- #


def test_list_closed_shows_applications_that_ended_not_dismissed_matches(cli_env):
    import door.core.tracker as tracker_mod

    for job_id, title in [("job-rej", "Rejected Job"), ("job-gho", "Ghosted Job"), ("job-wd", "Withdrawn Job"),
                          ("job-dis", "Dismissed Job"), ("job-app", "Applied Job")]:
        write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", job_id, score=0.9, title=title)
    app_tracker = tracker_mod.ApplicationTracker(cli_env.jobs_dir / "applications.json")
    for job_id, statuses in {"job-rej": ["applied", "rejected"], "job-gho": ["applied", "ghosted"],
                             "job-wd": ["prepared", "discarded"], "job-dis": ["discarded"], "job-app": ["applied"]}.items():
        for status in statuses:
            app_tracker.set_status(job_id, status)
    app_tracker.save()

    result = CliRunner().invoke(cli, ["jobs", "list", "--closed"])

    assert result.exit_code == 0, result_text(result)
    text = result_text(result)
    for shown in ("Rejected Job", "Ghosted Job", "Withdrawn Job"):
        assert shown in text
    for hidden in ("Dismissed Job", "Applied Job"):
        assert hidden not in text


def test_list_closed_is_not_combined_with_status_or_ongoing(cli_env):
    assert CliRunner().invoke(cli, ["jobs", "list", "--closed", "--ongoing"]).exit_code != 0
    assert CliRunner().invoke(cli, ["jobs", "list", "--closed", "--status", "rejected"]).exit_code != 0


def test_list_rows_carry_their_last_change_and_interview_rounds(cli_env):
    from door.commands import matches as matches_cmd
    import door.core.tracker as tracker_mod

    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-int", score=0.9, title="Interview Job")
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-new", score=0.9, title="Fresh Job")
    app_tracker = tracker_mod.ApplicationTracker(cli_env.jobs_dir / "applications.json")
    for status in ("applied", "interview:screening", "interview:technical"):
        app_tracker.set_status("job-int", status)
    app_tracker.save()

    rows = {m["id"]: m for m in matches_cmd._list_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir, ongoing=True)["matches"]}
    row = rows["job-int"]
    assert row["updated_at"] is not None and row["updated_at"] == app_tracker.updated_at("job-int")
    assert row["rounds"] == [{"stage": "screening", "result": "passed"}, {"stage": "technical", "result": "pending"}]
    fresh = matches_cmd._list_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir, min_score=0.0)["matches"]
    assert {m["id"]: (m["updated_at"], m["rounds"]) for m in fresh}["job-new"] == (None, [])


# --------------------------------------------------------------------------- #
# list_matches `scored` (issue #636)
# --------------------------------------------------------------------------- #


def _list_core_result(cli_env, **kwargs):
    from door.commands import matches as matches_cmd

    return matches_cmd._list_core(jobs_dir=cli_env.jobs_dir, profile_dir=cli_env.profile_dir, **kwargs)


def test_list_core_scored_is_zero_with_nothing_on_disk(cli_env):
    assert _list_core_result(cli_env)["scored"] == 0


def test_list_core_scored_counts_postings_below_the_bar(cli_env):
    config = json.loads((cli_env.profile_dir / "config.json").read_text())
    config["min_score"] = 0.8
    (cli_env.profile_dir / "config.json").write_text(json.dumps(config))
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-low", score=0.1, title="Low Job")

    result = _list_core_result(cli_env)

    assert result["matches"] == []
    assert result["scored"] == 1


def test_list_core_scored_ignores_dropped_and_unscored_postings(cli_env):
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-zero", score=0.0, title="Dropped Job")
    path = cli_env.jobs_dir / "postings" / "2026-07-01" / "jobindex" / "job-unscored.json"
    path.write_text(json.dumps({"id": "job-unscored", "title": "Unscored", "company": "X"}))

    assert _list_core_result(cli_env)["scored"] == 0


def test_list_core_scored_does_not_depend_on_status_or_filters(cli_env):
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-a", score=0.9, title="A Job")
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-b", score=0.9, title="B Job")
    import door.core.tracker as tracker_mod
    app_tracker = tracker_mod.ApplicationTracker(cli_env.jobs_dir / "applications.json")
    app_tracker.set_status("job-a", "applied")
    app_tracker.save()

    assert _list_core_result(cli_env, limit=1, new_only=True)["scored"] == 2


# --------------------------------------------------------------------------- #
# list_matches `weak` (issue #643)
# --------------------------------------------------------------------------- #


def _set_config(cli_env, **keys):
    config = json.loads((cli_env.profile_dir / "config.json").read_text())
    config.update(keys)
    (cli_env.profile_dir / "config.json").write_text(json.dumps(config))


def _weak_env(cli_env, scores, **config):
    _set_config(cli_env, min_score=0.6, **config)
    for i, score in enumerate(scores):
        write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", f"job-{i}", score=score, title=f"Job {i}")


def test_weak_is_the_three_best_below_the_bar_when_nothing_cleared_it(cli_env):
    _weak_env(cli_env, [0.4, 0.3, 0.2, 0.1, 0.05])

    result = _list_core_result(cli_env)

    assert result["matches"] == []
    assert [m["id"] for m in result["weak"]["matches"]] == ["job-0", "job-1", "job-2"]
    assert set(result["weak"]["matches"][0]) == {
        "id", "score", "title", "title_en", "company", "location", "work_permit", "status", "is_new", "updated_at", "rounds"}


def test_weak_has_fewer_than_three_when_fewer_were_scored(cli_env):
    _weak_env(cli_env, [0.4, 0.3])
    assert len(_list_core_result(cli_env)["weak"]["matches"]) == 2


def test_weak_is_none_when_nothing_was_scored(cli_env):
    assert _list_core_result(cli_env)["weak"] is None


def test_weak_is_none_once_any_posting_cleared_the_bar_even_discarded_or_old(cli_env):
    _weak_env(cli_env, [0.4, 0.8])
    import door.core.tracker as tracker_mod
    app_tracker = tracker_mod.ApplicationTracker(cli_env.jobs_dir / "applications.json")
    app_tracker.set_status("job-1", "discarded")
    app_tracker.save()
    assert _list_core_result(cli_env)["weak"] is None

    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-old", score=0.9, scraped_at="2020-01-01T00:00:00+00:00")
    assert _list_core_result(cli_env)["weak"] is None


def test_weak_is_none_when_the_below_bar_ones_are_tracked_or_stale(cli_env):
    _weak_env(cli_env, [0.4])
    import door.core.tracker as tracker_mod
    app_tracker = tracker_mod.ApplicationTracker(cli_env.jobs_dir / "applications.json")
    app_tracker.set_status("job-0", "applied")
    app_tracker.save()
    write_list_posting(cli_env.jobs_dir, "2026-07-01", "jobindex", "job-old", score=0.3, scraped_at="2020-01-01T00:00:00+00:00")

    assert _list_core_result(cli_env)["weak"] is None


def test_weak_bar_is_the_configs_not_the_calls(cli_env):
    _weak_env(cli_env, [0.4, 0.3])

    result = _list_core_result(cli_env, min_score=0.1)

    assert len(result["matches"]) == 2
    assert result["weak"] is not None


def test_weak_is_none_for_any_other_view(cli_env):
    _weak_env(cli_env, [0.4])
    for kwargs in ({"status": "applied"}, {"ongoing": True}, {"closed": True}, {"new_only": True}, {"limit": 1}):
        result = _list_core_result(cli_env, **kwargs)
        assert "weak" in result and result["weak"] is None, kwargs


def test_weak_hint_names_the_sources_that_are_off(cli_env):
    _weak_env(cli_env, [0.4], location="Budapest", linkedin_discovery=True)

    weak = _list_core_result(cli_env)["weak"]

    assert weak["hint"] == "sources"
    assert [s["key"] for s in weak["sources"]] == ["profession_discovery"]


def test_weak_hint_is_keywords_when_every_source_is_on(cli_env):
    _weak_env(cli_env, [0.4], linkedin_discovery=True)

    weak = _list_core_result(cli_env)["weak"]

    assert weak["hint"] == "keywords"
    assert weak["sources"] == []


def test_list_cli_shows_weak_matches_with_a_line_instead_of_no_matches(cli_env):
    _weak_env(cli_env, [0.4, 0.3, 0.2])

    result = CliRunner().invoke(cli, ["jobs", "list", "--score", "0.6"])

    text = " ".join(result_text(result).split())
    assert result.exit_code == 0, text
    assert "3 weak matches found" in text
    assert "Turn on more sources (LinkedIn) in your profile to widen the search, at your own risk (see LEGAL_DISCLAIMER.md)." in text
    assert "Job 0" in text
    assert "No matches found" not in text


def test_list_cli_plain_jobs_shows_the_weak_block_until_a_posting_clears_the_bar(cli_env):
    _weak_env(cli_env, [0.4, 0.3, 0.2, 0.1, 0.05])

    text = " ".join(result_text(CliRunner().invoke(cli, ["jobs"])).split())

    assert "3 weak matches found" in text
    assert "Job 2" in text
    assert "Job 3" not in text


def test_list_cli_score_option_lists_what_cleared_it_even_while_weak(cli_env):
    _weak_env(cli_env, [0.4, 0.3, 0.2, 0.1, 0.05])

    text = " ".join(result_text(CliRunner().invoke(cli, ["jobs", "list", "--score", "0.08"])).split())

    assert "weak match" not in text
    assert "Job 3" in text


def test_list_cli_weak_line_for_keywords_and_singular(cli_env):
    _weak_env(cli_env, [0.4], linkedin_discovery=True)

    text = " ".join(result_text(CliRunner().invoke(cli, ["jobs", "list", "--score", "0.6"])).split())

    assert "1 weak match found" in text
    assert "Broaden your search keywords to find closer ones." in text


def test_list_cli_says_no_matches_when_nothing_was_scored(cli_env):
    assert "No matches found" in result_text(CliRunner().invoke(cli, ["jobs"]))
