"""The shared helper that runs a feed's entries on a small pool, grouped by host (issue #254)."""

import threading

import pytest

from door.core import progress
from door.scrapers import _parallel


def test_host_group_is_the_registrable_domain():
    assert _parallel.host_group("https://acme.teamtailor.com/jobs") == "teamtailor.com"
    assert _parallel.host_group("https://beta.teamtailor.com") == "teamtailor.com"
    assert _parallel.host_group("careers.novonordisk.com") == "novonordisk.com"
    assert _parallel.host_group("https://Jobs.Acme.com:8443/x") == "acme.com"
    assert _parallel.host_group("localhost") == "localhost"


def test_workers_comes_from_scrape_workers_with_a_default():
    assert _parallel.workers({}) == 8
    assert _parallel.workers({"scrape_workers": 3}) == 3
    assert _parallel.workers({"scrape_workers": None}) == 8


def _entries():
    return ["a1", "b1", "a2", "c1", "b2", "a3"]


def _group(entry):
    return entry[0]


def test_results_come_back_in_entry_order_whatever_the_workers():
    for workers in (1, 2, 8):
        assert _parallel.map_by_group(_entries(), _group, lambda e: e.upper(), workers) == [
            "A1", "B1", "A2", "C1", "B2", "A3"
        ]


def test_one_group_runs_in_entry_order_on_one_thread():
    seen: dict[str, list[tuple[str, str]]] = {}
    lock = threading.Lock()

    def fn(entry):
        with lock:
            seen.setdefault(entry[0], []).append((entry, threading.current_thread().name))

    _parallel.map_by_group(_entries(), _group, fn, 4)

    assert [e for e, _ in seen["a"]] == ["a1", "a2", "a3"]
    assert [e for e, _ in seen["b"]] == ["b1", "b2"]
    for calls in seen.values():
        assert len({thread for _, thread in calls}) == 1


def test_groups_overlap_when_there_are_workers():
    barrier = threading.Barrier(3, timeout=5)  # releases only if three groups run at once

    def fn(entry):
        if entry.endswith("1"):
            barrier.wait()
        return entry

    assert _parallel.map_by_group(_entries(), _group, fn, 3) == _entries()


def test_one_worker_is_the_plain_serial_loop_on_the_calling_thread():
    order, threads = [], set()

    def fn(entry):
        order.append(entry)
        threads.add(threading.current_thread())

    _parallel.map_by_group(_entries(), _group, fn, 1)

    assert order == _entries()
    assert threads == {threading.current_thread()}


def test_the_first_error_in_entry_order_is_raised():
    def fn(entry):
        if entry in ("b1", "c1"):
            raise ValueError(entry)
        return entry

    with pytest.raises(ValueError, match="b1"):
        _parallel.map_by_group(_entries(), _group, fn, 4)


def test_workers_report_under_the_callers_scope(progress_events):
    def fn(entry):
        progress.report(f"fetching {entry}")

    with progress.scope(site="career_sites", stage="scrape"):
        _parallel.map_by_group(["a1", "b1"], _group, fn, 2)

    own = [e for e in progress_events if e.message.startswith("fetching")]
    assert {(e.message, e.site, e.stage) for e in own} == {
        ("fetching a1", "career_sites", "scrape"),
        ("fetching b1", "career_sites", "scrape"),
    }
    assert all(e.site == "career_sites" for e in progress_events)


def test_host_of_is_the_whole_host():
    assert _parallel.host_of("https://Maersk.wd3.myworkdayjobs.com/x") == "maersk.wd3.myworkdayjobs.com"
    assert _parallel.host_of("careers.novonordisk.com") == "careers.novonordisk.com"


def _max_concurrency(entries, group_of, workers, per_provider):
    running: dict[str, int] = {}
    peak: dict[str, int] = {}
    lock = threading.Lock()

    def fn(entry):
        provider = _parallel.host_group(group_of(entry))
        with lock:
            running[provider] = running.get(provider, 0) + 1
            peak[provider] = max(peak.get(provider, 0), running[provider])
        threading.Event().wait(0.05)
        with lock:
            running[provider] -= 1
        return entry

    assert _parallel.map_by_group(entries, group_of, fn, workers, per_provider=per_provider) == entries
    return peak


def test_hosts_of_one_provider_run_side_by_side_up_to_the_per_provider_cap():
    tenants = [f"https://t{i}.wd3.myworkdayjobs.com" for i in range(8)] + ["https://careers.acme.com"]
    peak = _max_concurrency(tenants, _parallel.host_of, workers=8, per_provider=3)
    assert peak["myworkdayjobs.com"] == 3  # eight tenants, never more than three at once
    assert peak["acme.com"] == 1


def test_the_per_provider_cap_defaults_to_four():
    assert _parallel.PER_PROVIDER == 4


def test_a_provider_at_its_cap_does_not_hold_workers_other_hosts_could_use():
    entries = [f"https://t{i}.wd3.myworkdayjobs.com" for i in range(3)] + ["https://careers.acme.com"]
    started = []
    lock = threading.Lock()

    def fn(entry):
        with lock:
            started.append(_parallel.host_group(entry))
        threading.Event().wait(0.05)
        return entry

    _parallel.map_by_group(entries, _parallel.host_of, fn, 2, per_provider=1)
    # Two workers: one Workday tenant and acme start together; acme does not wait
    # behind a worker blocked on Workday's cap.
    assert sorted(started[:2]) == ["acme.com", "myworkdayjobs.com"]


@pytest.mark.parametrize("workers", [1, 4])
def test_each_entry_reports_when_it_starts_and_ends_under_its_group(workers):
    from cli_utils import CaptureReporter

    cap = CaptureReporter()
    with progress.activate(cap):
        _parallel.map_by_group(["a1", "b1", "a2"], _group, lambda e: e, workers)
    events = [(e.message, e.stage) for e in cap.events]
    assert sorted(events) == sorted([("a", "entry_start")] * 2 + [("a", "entry_end")] * 2
                                    + [("b", "entry_start"), ("b", "entry_end")])


@pytest.mark.parametrize("workers", [1, 4])
def test_on_result_hears_every_result_on_the_calling_thread(workers):
    heard, threads = [], set()

    def on_result(index, result):
        heard.append((index, result))
        threads.add(threading.current_thread())

    out = _parallel.map_by_group(_entries(), _group, lambda e: e.upper(), workers, on_result=on_result)

    assert sorted(heard) == [(i, e.upper()) for i, e in enumerate(_entries())] and out == [e.upper() for e in _entries()]
    assert threads == {threading.current_thread()}
