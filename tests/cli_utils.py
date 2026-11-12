"""Helpers shared by the command tests (tests/commands/)."""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path


FRESH_SCRAPED_AT = datetime.now(timezone.utc).isoformat()


def result_text(result) -> str:
    """Combined stdout+stderr, tolerant of Click version differences."""
    text = result.output or ""
    try:
        text += result.stderr or ""
    except (ValueError, AttributeError):
        pass
    return text


class FakeCompleted:
    def __init__(self, returncode=0, stderr="", stdout=""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout


def write_list_posting(jobs_dir: Path, date: str, site: str, job_id: str, **overrides) -> Path:
    site_dir = jobs_dir / "postings" / date / site
    site_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "id": job_id,
        "title": "Data Scientist",
        "company": "Acme",
        "location": "Copenhagen",
        "url": "https://example.com/job/1",
        "description": "d",
        "source": site,
        "scraped_at": FRESH_SCRAPED_AT,
    }
    data.update(overrides)
    path = site_dir / f"{job_id}.json"
    path.write_text(json.dumps(data))
    return path


TAILOR_OUTPUTS = ("posting.json", "cv.tex", "cover_letter.tex", "cv.pdf", "cover_letter.pdf")


def write_tailor_outputs(output_dir, names=TAILOR_OUTPUTS):
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        (output_dir / name).write_text("x")


def fake_tailor(jobs_dir, called=None, *, writes=TAILOR_OUTPUTS, ok=True):
    """A `_run_tailor` stand-in that records the call and writes `writes`."""

    def _run(job_id, posting_path, **kwargs):
        if called is not None:
            called.append(job_id)
        write_tailor_outputs(jobs_dir / "output" / job_id, writes)
        return ok

    return _run


def stub_scrape_result(jobs_dir: Path, *, sites=None) -> dict:
    return {
        "run_date": "2026-07-01",
        "days": None,
        "mode": "search",
        "employers": None,
        "written": [],
        "sites": sites if sites is not None else [{"site": "jobindex", "outcome": "ok", "count": 1, "dir": "x"}],
        "liveness": None,
        "prefilter": None,
        "dedup": None,
        "condense": None,
        "prescreen": None,
        "candidates_dir": str(jobs_dir / "postings" / "2026-07-01"),
        "surviving_paths": [],
    }


def stub_match_result(jobs_dir: Path, *, scored=1, failed=None, above_threshold=0) -> dict:
    return {
        "candidates_dir": str(jobs_dir / "postings" / "2026-07-01"),
        "unscored_before": scored,
        "scored": scored,
        "failed": failed if failed is not None else [],
        "above_threshold": above_threshold,
        "model": "haiku",
        "elapsed_s": 0.1,
    }


class CaptureReporter:
    """A `Reporter` that records every `Progress` event it receives."""

    def __init__(self):
        self.events = []

    def report(self, event):
        self.events.append(event)


def stub_blocks(jobs_dir: Path) -> dict:
    """A valid block for each of `find`'s five steps (what their cores return), for tests that fake them."""
    return {
        "search": {"step": "search", "days": None, "run_date": "2026-07-01",
                   "sites": [{"site": "jobindex", "outcome": "ok", "count": 1, "dir": "x"}], "postings": 1,
                   "queued": 1, "failed": 0, "liveness": None, "candidates_dir": str(jobs_dir / "postings" / "2026-07-01"),
                   "elapsed_s": 0.1, "summary": "1 postings from 1 boards"},
        "discover": {"step": "discover", "skipped": None, "employers": 0, "details": 0, "queued": 0,
                     "easy_apply": 0, "stopped": None, "error": None, "elapsed_s": 0.1,
                     "summary": "0 employers, 0 read, 0 queued"},
        "follow": {"step": "follow", "dry_run": False, "queued": 0, "checked": 0, "followed": [],
                   "unfollowable": [], "unresolved": [], "kept": 0, "settled": 0, "expired": 0, "errors": [],
                   "results": [], "elapsed_s": 0.1, "summary": "nothing to check"},
        "collect": {"step": "collect", "employers": 0, "days": None, "run_date": "2026-07-01", "sites": [],
                    "postings": 0, "failed": 0, "liveness": None, "candidates_dir": str(jobs_dir / "postings" / "2026-07-01"),
                    "elapsed_s": 0.1, "summary": "no followed employers"},
        "match": {**stub_match_result(jobs_dir), "step": "match", "passes": {}, "min_score": 0.65,
                  "new_above_threshold": [], "top": [], "scoring_s": 0.1, "elapsed_s": 0.1,
                  "summary": "1 scored, 0 above 0.65"},
    }


def stub_steps(monkeypatch, jobs_dir: Path, *, real=(), **overrides):
    """Fake the five step cores of `find`: no network, no `claude`.

    ``.calls`` lists ``(step, kwargs)`` in the order they ran; ``.blocks`` holds the block each
    returns (a test may change them); ``overrides`` replace blocks by step name; the steps named in
    ``real`` are left alone. ``.on_call``, if set, is called with the step name as each fake runs.

    A full run starts discover in the background (`discover.begin`): its call is recorded when it
    begins, the fake handle is ``ready()`` once ``.discover_ready`` is true (default false: it is
    settled after collect) and ``.handles`` lists the handles made (with ``.cancelled``).
    """
    import types

    from door import pipeline
    from door.pipeline import collect, discover, follow, match, search

    state = types.SimpleNamespace(calls=[], blocks={**stub_blocks(jobs_dir), **overrides}, on_call=None,
                                  discover_ready=False, handles=[])

    def fake(name):
        def core(*args, **kwargs):
            state.calls.append((name, kwargs))
            if state.on_call:
                state.on_call(name)
            block = copy.deepcopy(state.blocks[name])  # a run folds late passes into its blocks
            if block.get("skipped"):
                pipeline.skipped(name, block["skipped"])
            else:
                with pipeline.running(name) as step:
                    step.summary = block["summary"]
            return block
        return core

    class Handle:
        def __init__(self):
            self.block = state.blocks["discover"]
            self.skipped = self.block.get("skipped")
            self.cancelled = self.finished = False
            if not self.skipped:
                pipeline.started("discover")

        def ready(self):
            return state.discover_ready or bool(self.skipped)

        def cancel(self):
            self.cancelled = True

        def finish(self):
            if not self.finished:
                self.finished = True
                if self.skipped:
                    pipeline.skipped("discover", self.skipped)
                else:
                    pipeline.finished("discover", self.block["summary"])
            return self.block

    def begin(**kwargs):
        state.calls.append(("discover", kwargs))
        if state.on_call:
            state.on_call("discover")
        state.handles.append(Handle())
        return state.handles[-1]

    if "discover" not in real:
        monkeypatch.setattr(discover, "begin", begin)
    for module, attr, name in (x for x in ((search, "_search_core", "search"), (discover, "_discover_core", "discover"),
                               (follow, "_follow_core", "follow"), (collect, "_collect_core", "collect"),
                               (match, "_match_step_core", "match")) if x[2] not in real):
        monkeypatch.setattr(module, attr, fake(name))
    state.order = lambda: [name for name, _ in state.calls]
    return state
