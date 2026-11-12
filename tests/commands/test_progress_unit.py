"""The live terminal renderer (issue #202): `LiveLine` and `live_progress`."""

import io

import click

from door.commands import _progress
from door.core import progress
from door.core.progress import Progress


def _line(stream=None):
    stream = stream or io.StringIO()
    return _progress.LiveLine(stream, animate=False), stream


def _plain(stream) -> str:
    return click.unstyle(stream.getvalue())


def test_final_line_for_ok_site_matches_scrape_wording():
    live, out = _line()
    live.report(Progress("jobindex: 5 posting(s)", 1, 2, site="jobindex", stage="scrape", outcome="ok"))
    assert "  ✓ jobindex: 5 posting(s)\n" in _plain(out)
    assert out.getvalue().count("\n") == 1


def test_failed_and_error_use_cross_and_empty_uses_warning():
    live, out = _line()
    live.report(Progress("a: 0 posting(s), 404 x2 — boom", site="a", stage="scrape", outcome="failed"))
    live.report(Progress("b: error — kaput", site="b", stage="scrape", outcome="error"))
    live.report(Progress("c: returned no results", site="c", stage="scrape", outcome="empty"))
    text = _plain(out)
    assert "  ✗ a: 0 posting(s), 404 x2 — boom\n" in text
    assert "  ✗ b: error — kaput\n" in text
    assert "  ⚠ c: returned no results\n" in text


def test_intermediate_events_draw_spinner_text_with_site_prefix():
    live, out = _line()
    live.report(Progress("'x': 3 results", site="jobindex", stage="scrape"))
    text = _plain(out)
    assert "jobindex: 'x': 3 results" in text
    assert "\n" not in text  # nothing final yet


def test_match_counter_event_draws_scored_3_over_12_and_prints_no_final_line():
    live, out = _line()
    live.report(Progress("scored", 3, 12, stage="match"))
    live.stop()
    assert "scored 3/12" in _plain(out)
    assert "\n" not in out.getvalue()


def test_stop_clears_the_line():
    live, out = _line()
    live.report(Progress("working"))
    live.stop()
    assert out.getvalue().endswith("\r\033[K")


def test_stop_without_drawing_writes_nothing():
    live, out = _line()
    live.stop()
    assert out.getvalue() == ""


def test_live_progress_disabled_yields_none_and_writes_nothing(capsys):
    with _progress.live_progress(False) as reporter:
        assert reporter is None
    assert capsys.readouterr().out == ""


def test_live_progress_enabled_yields_a_reporter_that_draws():
    out = io.StringIO()
    with _progress.live_progress(True, animate=False, stream=out) as reporter:
        with progress.activate(reporter):
            progress.report("hello", 1, 2)
        progress.report("after")
    text = _plain(out)
    assert "hello 1/2" in text
    assert "after" not in text
    assert out.getvalue().endswith("\r\033[K")


def test_animated_mode_redraws_from_a_thread_and_stops_cleanly():
    import time

    out = io.StringIO()
    live = _progress.LiveLine(out, animate=True, interval=0.01)
    live.report(Progress("spinning"))
    time.sleep(0.1)
    live.stop()
    assert out.getvalue().count("spinning") >= 2
    assert out.getvalue().endswith("\r\033[K")


def test_a_broken_stream_never_raises():
    class Broken(io.StringIO):
        def write(self, s):
            raise ValueError("closed")

    live = _progress.LiveLine(Broken(), animate=False)
    live.report(Progress("x"))
    live.stop()


def test_existing_step_spinner_format_unchanged(monkeypatch, capsys):
    monkeypatch.setattr(_progress.sys.stdout, "isatty", lambda: True, raising=False)
    _progress.step("Thing", lambda: (_progress.time.sleep(0.15), (True, None))[1])
    assert "\x1b[33m⠋\x1b[0m Thing" in capsys.readouterr().out


def test_any_stage_closing_a_step_leaves_a_permanent_line():
    live, out = _line()
    live.report(Progress("fetched jobs.example.com", stage="add", outcome="ok"))
    live.report(Progress("scoring failed", stage="add", outcome="failed"))
    assert "  ✓ fetched jobs.example.com\n" in _plain(out)
    assert "  ✗ scoring failed\n" in _plain(out)
    assert live.finished_sites == set()  # no site was closed
