"""`_with_progress`, `_locked` progress activation and `_stdout_is_tty` (issue #202)."""

import json

from cli_utils import CaptureReporter
from door.commands import _common as common
from door.core import progress


def test_with_progress_activates_kwarg_reporter_for_the_call():
    @common._with_progress
    def core(*, progress=None):
        from door.core import progress as p

        p.report("inside")

    cap = CaptureReporter()
    core(progress=cap)
    progress.report("outside")
    assert [e.message for e in cap.events] == ["inside"]


def test_with_progress_without_kwarg_is_noop(progress_events):
    @common._with_progress
    def core(x, *, progress=None):
        return x + 1

    assert core(1) == 2
    assert progress_events == []


def test_locked_activates_progress_and_attaches_progress_file(tmp_path):
    seen = {}

    @common._locked("toy")
    def core(*, jobs_dir=None, progress=None):
        from door.core import progress as p

        p.report("working", 1, 2)
        seen["file"] = json.loads((jobs_dir / ".progress.json").read_text())

    cap = CaptureReporter()
    core(jobs_dir=tmp_path, progress=cap)
    assert [e.message for e in cap.events] == ["working"]
    assert seen["file"]["message"] == "working"
    assert not (tmp_path / ".progress.json").exists()


def test_stdout_is_tty_is_false_under_capture_and_monkeypatchable(monkeypatch):
    assert common._stdout_is_tty() is False
    monkeypatch.setattr(common, "_stdout_is_tty", lambda: True)
    assert common._stdout_is_tty() is True
