"""The problem log (#593): `<home>/logs/door.log`, one line per thing that went wrong, rotating."""

import pytest

from door.core import problem_log, workspace


@pytest.fixture
def log(tmp_path):
    """The log set up on a temporary data folder, closed again after the test."""
    home = tmp_path / "home"
    home.mkdir()
    path = problem_log.setup(home)
    yield path
    problem_log.close()


def test_setup_writes_to_logs_door_log_in_the_data_folder(log, tmp_path):
    assert log == tmp_path / "home" / "logs" / "door.log"
    problem_log.failure("tool show", "no posting found for job_id 'x'")
    line = log.read_text(encoding="utf-8").strip()
    assert line.endswith("ERROR tool show: no posting found for job_id 'x'")
    assert line[:4].isdigit() and "T" in line.split()[0] and line.split()[0].endswith("Z")


def test_without_setup_nothing_is_written_anywhere(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    problem_log.failure("tool show", "lost")
    problem_log.warning("tool market", "lost too")
    assert not (tmp_path / "logs").exists()


def test_nothing_is_made_until_something_goes_wrong(log):
    assert not log.parent.exists()
    problem_log.warning("tool market", "now")
    assert log.is_file()


def test_no_data_folder_no_log(tmp_path):
    assert problem_log.setup(tmp_path / "missing") is None
    problem_log.failure("tool show", "lost")
    assert not (tmp_path / "missing").exists()


def test_setup_defaults_to_the_workspace_home(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "HOME", tmp_path)
    try:
        assert problem_log.setup() == tmp_path / "logs" / "door.log"
    finally:
        problem_log.close()


def test_a_message_is_one_line_and_bounded(log):
    problem_log.warning("tool keywords", "first\nsecond\n\n" + "x" * 5000)
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert "first second" in lines[0]
    assert len(lines[0]) < 1000


def test_a_crash_is_one_line_with_where_it_happened(log):
    def inner():
        raise RuntimeError("boom\nmore")

    try:
        inner()
    except RuntimeError as exc:
        problem_log.crash("tool find_jobs", exc)
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert "ERROR tool find_jobs: RuntimeError: boom more" in lines[0]
    assert "inner" in lines[0]


def test_the_log_rotates_and_keeps_three_files(tmp_path, monkeypatch):
    monkeypatch.setattr(problem_log, "MAX_BYTES", 300)
    home = tmp_path / "home"
    home.mkdir()
    log = problem_log.setup(home)
    try:
        for n in range(100):
            problem_log.failure("tool show", f"failure number {n}")
    finally:
        problem_log.close()
    names = sorted(p.name for p in log.parent.iterdir())
    assert names == ["door.log", "door.log.1", "door.log.2"]
    assert all(p.stat().st_size <= 400 for p in log.parent.iterdir())
    assert "failure number 99" in log.read_text(encoding="utf-8")


def test_setup_again_moves_the_log_and_never_doubles_lines(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    problem_log.setup(first)
    problem_log.setup(second)
    try:
        problem_log.failure("tool show", "once")
    finally:
        problem_log.close()
    assert not (first / "logs").exists()
    assert (second / "logs" / "door.log").read_text(encoding="utf-8").count("once") == 1


def test_a_run_record_logs_its_failed_and_empty_sites_and_unscored_ads(log):
    record = {
        "search": {"sites": [
            {"site": "jobindex", "outcome": "ok", "count": 4},
            {"site": "thehub", "outcome": "failed", "count": 0, "errors": ["HTTP 503 from thehub.io"]},
            {"site": "euraxess", "outcome": "empty", "warning": "no records at all: the site may have changed"},
        ]},
        "collect": {"sites": [{"site": "greenhouse", "outcome": "error", "error": "KeyError: 'jobs'"}]},
        "match": {"failed": ["jobindex.1"], "failures": [{"id": "jobindex.1", "error": "claude timed out"}],
                  "top": [{"id": "jobindex.2", "title": "Head of Secret Plans", "company": "Acme"}]},
    }
    problem_log.run_record(record)
    text = log.read_text(encoding="utf-8")
    assert "ERROR site thehub failed: HTTP 503 from thehub.io" in text
    assert "WARNING site euraxess empty: no records at all" in text
    assert "ERROR site greenhouse error: KeyError: 'jobs'" in text
    assert "ERROR unscored jobindex.1: claude timed out" in text
    assert "site jobindex" not in text
    assert "Secret Plans" not in text and "Acme" not in text
