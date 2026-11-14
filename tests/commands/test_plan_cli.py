"""The Claude plan's room, where a user sees it (#575, plan §7): the `plan` block of
`status_summary`, its line in `jobs summary`, before `jobs prepare` and at the end of `find`.

Offline: the usage log is written by hand; nothing calls `claude`.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from click.testing import CliRunner

from door.cli import cli
from door.commands import _common as common
from door.commands import find as find_cmd
from door.commands import prepare as prepare_cmd
from door.commands import status as status_cmd
from door.core import usage
from cli_utils import result_text, stub_steps

_NOW = datetime.now(timezone.utc)
_RESETS = (_NOW + timedelta(hours=2)).replace(microsecond=0)


def _clock(when: datetime) -> str:
    """As `common._clock`: "HH:MM" today, "Mon HH:MM" another day (a reset two hours on
    crosses midnight late in the evening)."""
    local = when.astimezone()
    today = datetime.now().astimezone().date()
    return local.strftime("%H:%M" if local.date() == today else "%a %H:%M")


def _plan(**over):
    plan = {"as_of": _NOW.isoformat(), "status": "allowed",
            "five_hour": {"used": 0.42, "resets_at": _RESETS.isoformat()},
            "seven_day": {"used": 0.31, "resets_at": (_RESETS + timedelta(days=3)).isoformat()},
            "room": {"find": 6, "prepare": 2}, "binding": "five_hour"}
    plan.update(over)
    return plan


# --------------------------------------------------------------------------- the lines
def test_the_summary_line_says_use_room_and_when():
    assert common._plan_line(_plan()) == (
        f"42% of this 5-hour window used (resets {_clock(_RESETS)}) · room for about 6 finds or 2 prepares"
        f" · as of {_clock(_NOW)}")


def test_the_summary_line_names_the_window_that_binds_and_counts_one_of_each():
    line = common._plan_line(_plan(binding="seven_day", room={"find": 1, "prepare": 1}))
    assert line.startswith("31% of this week's window used (resets ")
    assert "room for about 1 find or 1 prepare ·" in line


def test_uncalibrated_the_summary_line_has_no_room():
    line = common._plan_line(_plan(room=None, binding=None))
    assert line.startswith("42% of this 5-hour window used") and "room" not in line


def test_a_warning_leads_the_summary_line():
    assert common._plan_line(_plan(status="allowed_warning", warning="Claude's usage limit is close")).startswith(
        "Claude's usage limit is close · 42% of this 5-hour window used")


def test_a_refused_plan_says_so_and_no_room():
    line = common._plan_line(_plan(status="rejected", warning="Claude's usage limit is reached",
                                   room={"find": 0, "prepare": 0}))
    assert line.startswith("Claude's usage limit is reached · 42%") and "room" not in line


def test_without_utilization_the_line_says_when_the_window_resets():
    line = common._plan_line(_plan(five_hour={"resets_at": _RESETS.isoformat()}, seven_day={}, room=None))
    assert line.startswith(f"this 5-hour window resets {_clock(_RESETS)}")


@pytest.mark.parametrize("plan, line", [
    (_plan(), f"This window has room for about 2 more prepares (resets {_clock(_RESETS)})."),
    (_plan(room={"find": 9, "prepare": 1}), f"This window has room for about 1 more prepare (resets {_clock(_RESETS)})."),
    (_plan(room={"find": 9, "prepare": 4}), None),  # plenty: nothing to say
    (_plan(room={"find": 9, "prepare": 9}, status="allowed_warning", warning="Claude's usage limit is close"),
     f"This window has room for about 9 more prepares (resets {_clock(_RESETS)})."),
    (_plan(room=None, status="allowed_warning", warning="Claude's usage limit is close"),
     f"Claude's usage limit is close (resets {_clock(_RESETS)})."),
    (_plan(status="rejected", warning="Claude's usage limit is reached", room={"find": 0, "prepare": 0}),
     f"Claude's usage limit is reached (resets {_clock(_RESETS)})."),
    (_plan(room=None), None),
    (None, None),
])
def test_before_a_prepare_a_line_only_when_room_is_short(plan, line):
    assert common._prepare_room_line(plan) == line


def test_after_a_find_the_line_says_the_windows_use():
    assert common._plan_use_line(_plan()) == f"Claude plan: 42% of this 5-hour window used (resets {_clock(_RESETS)})"
    assert common._plan_use_line(None) is None


# --------------------------------------------------------------------------- status_summary
def _reading(jobs_dir, **fields):
    jobs_dir.mkdir(parents=True, exist_ok=True)
    line = {"at": _NOW.isoformat(), "feature": "match_scoring", "units": 1, "weight": 0.01,
            "u5": 0.42, "r5": int(_RESETS.timestamp()), "status": "allowed", **fields}
    with (jobs_dir / usage.LOG_NAME).open("a") as fh:
        fh.write(json.dumps(line) + "\n")


def test_status_summary_has_no_plan_before_a_call_read_it(cli_env):
    assert status_cmd._status_summary_core(cli_env.jobs_dir, cli_env.profile_dir)["plan"] is None


def test_status_summary_carries_the_plan_and_this_weeks_shares(cli_env):
    _reading(cli_env.jobs_dir)
    plan = status_cmd._status_summary_core(cli_env.jobs_dir, cli_env.profile_dir)["plan"]
    assert plan["five_hour"]["used"] == 0.42 and plan["room"] is None
    assert plan["week"]["heaviest"] == "find"


# --------------------------------------------------------------------------- the commands
def test_jobs_summary_prints_the_plan_line(cli_env):
    _reading(cli_env.jobs_dir)
    text = result_text(CliRunner().invoke(cli, ["jobs", "summary"]))
    assert "Claude plan" in text and "42% of this 5-hour window used" in text


def test_jobs_summary_says_nothing_of_the_plan_before_a_call_read_it(cli_env):
    assert "Claude plan" not in result_text(CliRunner().invoke(cli, ["jobs", "summary"]))


def test_prepare_says_first_when_the_window_is_short(cli_env, monkeypatch):
    monkeypatch.setattr(usage, "room", lambda *a, **k: _plan())
    monkeypatch.setattr(prepare_cmd, "_prepare_core", lambda *a, **k: {"outcome": "no_matches"})
    text = result_text(CliRunner().invoke(cli, ["jobs", "prepare"]))
    assert text.index("This window has room for about 2 more prepares") < text.index("No matches found")


def test_prepare_says_nothing_with_room_to_spare(cli_env, monkeypatch):
    monkeypatch.setattr(usage, "room", lambda *a, **k: _plan(room={"find": 9, "prepare": 9}))
    monkeypatch.setattr(prepare_cmd, "_prepare_core", lambda *a, **k: {"outcome": "no_matches"})
    assert "room" not in result_text(CliRunner().invoke(cli, ["jobs", "prepare"]))


def test_a_find_ends_with_the_windows_use(cli_env, monkeypatch):
    stub_steps(monkeypatch, cli_env.jobs_dir)
    monkeypatch.setattr(usage, "room", lambda *a, **k: _plan())
    lines = CliRunner().invoke(cli, ["find"]).output.strip().splitlines()
    assert lines[-1] == f"Claude plan: 42% of this 5-hour window used (resets {_clock(_RESETS)})"


def test_a_find_that_scored_nothing_says_nothing_of_the_plan(cli_env, monkeypatch):
    stub_steps(monkeypatch, cli_env.jobs_dir)
    monkeypatch.setattr(usage, "room", lambda *a, **k: _plan())
    assert "Claude plan" not in CliRunner().invoke(cli, ["find", "--skip", "match"]).output


# --------------------------------------------------------------------------- what it cost (#64)
def _weighed(jobs_dir, *rows):
    """(feature, weight, units) lines of today."""
    jobs_dir.mkdir(parents=True, exist_ok=True)
    with (jobs_dir / usage.LOG_NAME).open("a") as fh:
        for feature, weight, units in rows:
            fh.write(json.dumps({"at": _NOW.isoformat(), "feature": feature, "units": units, "weight": weight}) + "\n")


def test_usd_reads_as_dollars_and_cents():
    assert [common._usd(x) for x in (0, 0.004, 0.012, 1.5, 12.345)] == ["$0.00", "<$0.01", "$0.01", "$1.50", "$12.35"]


def test_status_summary_has_no_cost_before_a_call_was_weighed(cli_env):
    assert status_cmd._status_summary_core(cli_env.jobs_dir, cli_env.profile_dir)["cost"] is None


def test_status_summary_carries_what_the_last_week_cost(cli_env):
    _weighed(cli_env.jobs_dir, ("match_scoring", 0.40, 100), ("tailoring", 1.20, 1))
    cost = status_cmd._status_summary_core(cli_env.jobs_dir, cli_env.profile_dir)["cost"]
    assert cost["usd"] == pytest.approx(1.60) and cost["activities"][0]["activity"] == "prepare"


def test_jobs_summary_prints_what_each_activity_cost(cli_env):
    _weighed(cli_env.jobs_dir, ("match_scoring", 0.40, 100), ("title_translation", 0.05, 1), ("tailoring", 1.20, 1))
    text = result_text(CliRunner().invoke(cli, ["jobs", "summary"]))
    assert "Claude usage, last 7 days, at API prices" in text
    assert "$1.65 in all" in text and "one prepare about $1.20" in text
    assert "Preparing applications" in text and "1 application prepared" in text
    assert "Finding jobs" in text and "$0.45" in text and "100 postings scored" in text
    assert "Scoring postings" in text and "$0.40" in text and "Translating job titles" in text


def test_cost_lines_say_one_of_each_in_the_singular_and_a_sliver_as_under_a_cent():
    head, rows = common._cost_lines({"days": 7, "usd": 0.003, "per_run": {"find": 0.25, "prepare": None}, "activities": [
        {"activity": "other", "label": "Everything else", "usd": 0.003, "count": 1, "of": "other requests",
         "features": [{"feature": "ask", "label": "Questions about your jobs", "usd": 0.003, "calls": 1}]}]})
    assert head == "<$0.01 in all · one find about $0.25"
    assert rows == [("Everything else", "<$0.01", "1 other request")]


def test_jobs_summary_with_nothing_this_week_says_so(cli_env):
    cli_env.jobs_dir.mkdir(parents=True, exist_ok=True)
    old = (_NOW - timedelta(days=20)).isoformat()
    (cli_env.jobs_dir / usage.LOG_NAME).write_text(
        json.dumps({"at": old, "feature": "ask", "units": 1, "weight": 0.02}) + "\n")
    text = result_text(CliRunner().invoke(cli, ["jobs", "summary"]))
    assert "Claude usage, last 7 days" in text and "nothing in the last 7 days" in text


def test_jobs_summary_says_nothing_of_cost_before_a_call_was_weighed(cli_env):
    assert "Claude usage" not in result_text(CliRunner().invoke(cli, ["jobs", "summary"]))
