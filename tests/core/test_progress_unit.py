"""The progress channel (issue #202): events, reporters, scope, file sink, heartbeat."""

import json
import re
import threading
import time

import pytest

from cli_utils import CaptureReporter
from door.core import progress
from door.core.progress import Progress


def test_progress_text_and_line_formats():
    assert Progress("scored", 3, 12).text == "scored 3/12"
    assert Progress("x", 2).text == "x 2"
    assert Progress("plain").text == "plain"
    assert Progress("m", site="jobindex").line == "jobindex: m"
    assert Progress("jobindex: 5 posting(s)", site="jobindex").line == "jobindex: 5 posting(s)"
    assert Progress("no site").line == "no site"
    assert Progress("jobindex: 5 posting(s)", 2, 5, site="jobindex", outcome="ok").text == "jobindex: 5 posting(s)"


def test_an_event_can_carry_a_detail_that_the_text_ignores(progress_events):
    progress.report("search", stage="step", outcome="done", detail="41 postings")
    event = progress_events[0]
    assert event.detail == "41 postings" and event.text == "search" and event.to_dict()["detail"] == "41 postings"
    assert Progress("x").detail is None


def test_report_without_active_reporter_is_noop():
    progress.report("nobody listens")


def test_activate_routes_events_and_detaches_even_on_exception():
    cap = CaptureReporter()
    with pytest.raises(RuntimeError):
        with progress.activate(cap):
            progress.report("one", 1, 2)
            raise RuntimeError("boom")
    progress.report("after")
    assert [e.message for e in cap.events] == ["one"]
    assert (cap.events[0].done, cap.events[0].total) == (1, 2)


def test_activate_none_is_noop():
    with progress.activate(None) as got:
        assert got is None
        progress.report("x")


def test_nested_activation_fans_out_to_every_active_reporter():
    outer, inner = CaptureReporter(), CaptureReporter()
    with progress.activate(outer):
        progress.report("a")
        with progress.activate(inner):
            progress.report("b")
        progress.report("c")
    assert [e.message for e in outer.events] == ["a", "b", "c"]
    assert [e.message for e in inner.events] == ["b"]


def test_fan_out_reporter_calls_all_and_survives_a_broken_reporter():
    class Broken:
        def report(self, event):
            raise ValueError("nope")

    good = CaptureReporter()
    fan = progress.FanOutReporter(Broken(), good)
    fan.report(Progress("x"))
    assert [e.message for e in good.events] == ["x"]

    with progress.activate(Broken()), progress.activate(good):
        progress.report("y")
    assert [e.message for e in good.events] == ["x", "y"]


def test_scope_fills_site_and_stage_and_explicit_kwargs_override(progress_events):
    with progress.scope(site="jobindex", stage="scrape"):
        progress.report("a")
        progress.report("b", site="other", outcome="ok")
    e1, e2 = progress_events
    assert (e1.site, e1.stage, e1.outcome) == ("jobindex", "scrape", None)
    assert (e2.site, e2.stage, e2.outcome) == ("other", "scrape", "ok")


def test_scope_restores_previous_on_exit(progress_events):
    with progress.scope(site="a"):
        with progress.scope(site="b", stage="s"):
            progress.report("inner")
        progress.report("outer")
    progress.report("none")
    assert [(e.site, e.stage) for e in progress_events] == [("b", "s"), ("a", None), (None, None)]


def test_report_from_other_thread_reaches_reporter(progress_events):
    t = threading.Thread(target=lambda: progress.report("from thread"))
    t.start()
    t.join()
    assert [e.message for e in progress_events] == ["from thread"]


def test_null_reporter_ignores_events():
    progress.NullReporter().report(Progress("x"))


# --- ProgressFile / read_progress ------------------------------------------------


def test_progress_file_writes_snapshot_with_updated_at_and_pid(tmp_path):
    path = tmp_path / ".progress.json"
    sink = progress.ProgressFile(path)
    sink.report(Progress("scraping", 1, 3, site="jobindex", stage="scrape"))
    data = json.loads(path.read_text())
    assert data["message"] == "scraping"
    assert (data["done"], data["total"]) == (1, 3)
    assert data["site"] == "jobindex" and data["stage"] == "scrape"
    assert data["pid"] > 0
    assert data["updated_at"]


def test_progress_file_write_is_atomic_no_tmp_left(tmp_path):
    sink = progress.ProgressFile(tmp_path / ".progress.json")
    sink.report(Progress("a"))
    assert sorted(p.name for p in tmp_path.iterdir()) == [".progress.json"]


def test_progress_file_throttles_but_always_writes_first_and_outcome_and_final_count(tmp_path):
    now = [0.0]
    path = tmp_path / ".progress.json"
    sink = progress.ProgressFile(path, min_interval=0.25, clock=lambda: now[0])

    def msg():
        return json.loads(path.read_text())["message"]

    sink.report(Progress("first"))
    assert msg() == "first"
    now[0] = 0.1
    sink.report(Progress("second"))
    assert msg() == "first"  # throttled
    now[0] = 0.2
    sink.report(Progress("done site", outcome="ok"))
    assert msg() == "done site"  # outcome always writes
    now[0] = 0.21
    sink.report(Progress("scored", 2, 5))
    assert msg() == "done site"
    sink.report(Progress("scored", 5, 5))
    assert msg() == "scored"  # final count always writes
    now[0] = 1.0
    sink.report(Progress("later"))
    assert msg() == "later"


def test_progress_file_close_stops_writes_and_does_not_recreate_file(tmp_path):
    path = tmp_path / ".progress.json"
    sink = progress.ProgressFile(path)
    sink.report(Progress("a"))
    path.unlink()
    sink.close()
    sink.report(Progress("b"))
    assert not path.exists()


def _plan(sink):
    sink.report(Progress("plan", stage="steps", detail="search,discover,follow,collect,match"))


def test_progress_file_folds_every_event_into_steps(tmp_path):
    path = tmp_path / ".progress.json"
    wall = [1_700_000_000.0]
    sink = progress.ProgressFile(path, min_interval=1000, wall=lambda: wall[0])
    _plan(sink)
    sink.report(Progress("search", total=2, site="search", stage="step", outcome="start"))
    wall[0] += 3
    sink.report(Progress("kw", stage="keyword", site="jobindex"))
    sink.report(Progress("kw", stage="keyword", site="jobindex"))
    sink.report(Progress("postings", 5, stage="postings", site="jobindex"))
    wall[0] += 7
    sink.report(Progress("search", site="search", stage="step", outcome="done", detail="5 postings"))
    data = json.loads(path.read_text())
    steps = data["steps"]
    assert [(s["name"], s["status"]) for s in steps] == [
        ("search", "done"), ("discover", "waiting"), ("follow", "waiting"),
        ("collect", "waiting"), ("match", "waiting"),
    ]
    search = steps[0]
    assert search["detail"] == "5 postings"
    assert search["sites"] == {"jobindex": 5}
    assert search["started_at"].startswith("2023-11-14T22:13:20")
    assert search["finished_at"].startswith("2023-11-14T22:13:30")
    assert "started_at" not in steps[1]
    assert data["message"] == "search"  # the old top-level fields stay
    assert data["pid"] > 0 and data["updated_at"]


def test_throttled_events_still_count_in_the_fold(tmp_path):
    path = tmp_path / ".progress.json"
    sink = progress.ProgressFile(path, min_interval=1000, wall=lambda: 1_700_000_000.0)
    _plan(sink)
    sink.report(Progress("collect", total=3, site="collect", stage="step", outcome="start"))
    sink.report(Progress("a.example", stage="entry_start"))
    sink.report(Progress("a.example", stage="entry_end"))  # swallowed by the throttle
    sink.report(Progress("m", 1, 2, stage="scored"))  # swallowed
    sink.report(Progress("collect", site="collect", stage="step", outcome="done", detail="ok"))
    collect = next(s for s in json.loads(path.read_text())["steps"] if s["name"] == "collect")
    assert collect["hosts"] == [] and collect["done"] == 1 and collect["total"] == 3


def test_running_step_carries_hosts_and_a_skipped_step_its_reason(tmp_path):
    path = tmp_path / ".progress.json"
    sink = progress.ProgressFile(path, min_interval=0, wall=lambda: 1_700_000_000.0)
    _plan(sink)
    sink.report(Progress("discover", site="discover", stage="step", outcome="skipped", detail="off"))
    sink.report(Progress("collect", total=3, site="collect", stage="step", outcome="start"))
    sink.report(Progress("a.example", stage="entry_start"))
    steps = {s["name"]: s for s in json.loads(path.read_text())["steps"]}
    assert (steps["discover"]["status"], steps["discover"]["detail"]) == ("skipped", "off")
    assert steps["collect"]["status"] == "running" and steps["collect"]["hosts"] == ["a.example"]
    assert "finished_at" not in steps["collect"]


def test_a_running_step_carries_its_boards_each_with_how_far_it_got(tmp_path):
    path = tmp_path / ".progress.json"
    sink = progress.ProgressFile(path, min_interval=0, wall=lambda: 1_700_000_000.0)
    _plan(sink)
    sink.report(Progress("search", total=2, site="search", stage="step", outcome="start"))
    sink.report(Progress("items", site="search", stage="items", detail='[["jobindex", "Jobindex"], ["thehub", "The Hub"]]'))
    sink.report(Progress("jobindex", site="jobindex", stage="scrape", outcome="ok"))
    search = json.loads(path.read_text())["steps"][0]
    assert search["items"] == [{"id": "jobindex", "name": "Jobindex", "state": "done"},
                               {"id": "thehub", "name": "The Hub", "state": "waiting"}]
    assert (search["done"], search["total"]) == (1, 2)  # the app's bar: boards finished of boards read
    assert "items" not in json.loads(path.read_text())["steps"][1]
    # a board at work carries what it is doing, for the app to say in words
    sink.report(Progress("thehub", site="thehub", stage="scrape"))
    sink.report(Progress("data", 12, 40, site="thehub", stage="ad_details"))
    search = json.loads(path.read_text())["steps"][0]
    assert search["items"][1] == {"id": "thehub", "name": "The Hub", "state": "running",
                                  "activity": {"kind": "reading", "keyword": "data", "done": 12, "total": 40}}


def test_progress_file_close_stops_the_fold(tmp_path):
    path = tmp_path / ".progress.json"
    sink = progress.ProgressFile(path, min_interval=0, wall=lambda: 1_700_000_000.0)
    _plan(sink)
    sink.close()
    sink.report(Progress("search", total=1, site="search", stage="step", outcome="start"))
    assert [s["status"] for s in json.loads(path.read_text())["steps"]] == ["waiting"] * 5


def test_a_broken_fold_never_stops_the_file(tmp_path, monkeypatch):
    path = tmp_path / ".progress.json"
    sink = progress.ProgressFile(path, wall=lambda: 1.0)

    def boom(*a, **k):
        raise RuntimeError("fold bug")

    monkeypatch.setattr(sink._board, "apply", boom)
    sink.report(Progress("hello"))
    assert json.loads(path.read_text())["message"] == "hello"


def test_read_progress_missing_or_corrupt_returns_none(tmp_path):
    assert progress.read_progress(tmp_path) is None
    (tmp_path / ".progress.json").write_text("{not json")
    assert progress.read_progress(tmp_path) is None


def test_read_progress_roundtrip(tmp_path):
    progress.ProgressFile(tmp_path / progress.PROGRESS_NAME).report(Progress("hello", 1, 2, site="s"))
    data = progress.read_progress(tmp_path)
    assert data["message"] == "hello" and data["site"] == "s"


# --- heartbeat --------------------------------------------------------------------


def test_heartbeat_emits_elapsed_events_until_exit(progress_events):
    before = threading.active_count()
    with progress.heartbeat("tailoring job-a", stage="prepare", interval_s=0.01):
        deadline = time.monotonic() + 2
        while len(progress_events) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
    assert len(progress_events) >= 2
    for e in progress_events:
        assert re.fullmatch(r"tailoring job-a · \d+m\d+s elapsed", e.message)
        assert e.stage == "prepare"
    assert threading.active_count() <= before


def test_heartbeat_emits_nothing_when_block_is_faster_than_interval(progress_events):
    with progress.heartbeat("x", stage="prepare", interval_s=30):
        pass
    assert progress_events == []


def test_format_elapsed():
    assert progress.format_elapsed(200) == "3m20s"
    assert progress.format_elapsed(5) == "0m05s"


def test_scope_is_per_thread_so_concurrent_sites_do_not_mix(progress_events):
    inside, release = threading.Barrier(2, timeout=5), threading.Barrier(2, timeout=5)

    def worker(site):
        with progress.scope(site=site, stage="scrape"):
            inside.wait()  # both threads are in their scope now
            progress.report(f"from {site}")
            release.wait()

    threads = [threading.Thread(target=worker, args=(s,)) for s in ("a", "b")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert {(e.message, e.site) for e in progress_events} == {("from a", "a"), ("from b", "b")}


def test_current_scope_can_be_handed_to_a_worker_thread(progress_events):
    with progress.scope(site="a", stage="scrape"):
        captured = progress.current_scope()

    def worker():
        with progress.scope(**captured):
            progress.report("in worker")

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert [(e.site, e.stage) for e in progress_events] == [("a", "scrape")]


def test_a_boards_keyword_events_read_as_sentences_on_a_line():
    assert Progress("data", 3, 21, site="jobindex", stage="keyword_search").line == "jobindex: searching 'data' 3/21"
    assert Progress("data", 12, 40, site="jobindex", stage="ad_details").line == "jobindex: reading ads for 'data' 12/40"
