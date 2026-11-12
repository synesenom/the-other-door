"""Tests for door.matching.scorer.score_postings — the parallel/chunked
`claude -p` pool (issue #128).

`subprocess.run` is never called for real: every test injects a fake
`run_fn`/`sleep_fn` via score_postings' dependency-injection parameters.
Covers: env scrubbing (the scope-addition from the issue's comment),
order-independence of the returned results dict, usage-limit retry with
backoff, and chunk=1 vs chunk=5 shape parity.
"""

import json

from door.matching import scorer


class _FakeCompleted:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _item(job_id, score=0.7):
    return {
        "job_id": job_id,
        "score": score,
        "score_reason": "fits well",
        "matching_skills": ["Python"],
        "missing_skills": [],
        "language_requirement": "none",
        "flags": [],
    }


def _chunk_envelope(items):
    return json.dumps(
        {
            "type": "result",
            "is_error": False,
            "result": json.dumps({"results": items}),
        }
    )


def _posting(job_id, **overrides):
    data = {
        "id": job_id,
        "title": "Data Scientist",
        "company": "Acme",
        "location": "Copenhagen",
        "posted_at": "2026-01-01",
        "description_condensed": "Build models.",
    }
    data.update(overrides)
    return data


# --------------------------------------------------------------------------- #
# Env scrubbing (issue comment scope addition)
# --------------------------------------------------------------------------- #


def test_score_chunk_scrubs_claude_code_env(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "parent-session-id")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("KEEP_ME", "yes")

    captured = {}

    def fake_run(argv, **kwargs):
        captured.update(kwargs)
        return _FakeCompleted(0, stdout=_chunk_envelope([_item("job-1")]))

    results, failed = scorer.score_postings(
        [_posting("job-1")],
        system_prompt="sys",
        workers=1,
        chunk=1,
        run_fn=fake_run,
        sleep_fn=lambda s: None,
    )

    assert failed == []
    assert "job-1" in results

    env = captured["env"]
    assert not [k for k in env if k.startswith("CLAUDE_CODE_")]
    assert "CLAUDECODE" not in env
    assert env.get("KEEP_ME") == "yes"


# --------------------------------------------------------------------------- #
# Order independence
# --------------------------------------------------------------------------- #


def test_results_keyed_by_job_id_regardless_of_completion_order():
    postings = [_posting("job-a"), _posting("job-b")]

    def fake_run(argv, *, input, **kwargs):
        job_id = "job-a" if "job-a" in input else "job-b"
        return _FakeCompleted(0, stdout=_chunk_envelope([_item(job_id)]))

    seen = []
    results, failed = scorer.score_postings(
        postings,
        system_prompt="sys",
        workers=2,
        chunk=1,
        run_fn=fake_run,
        sleep_fn=lambda s: None,
        on_result=lambda job_id, result: seen.append(job_id),
    )

    assert failed == []
    assert set(results) == set(seen) == {"job-a", "job-b"}
    assert results["job-a"]["score"] == 0.7
    assert results["job-b"]["score"] == 0.7


# --------------------------------------------------------------------------- #
# Usage-limit retry with backoff
# --------------------------------------------------------------------------- #


def test_usage_limit_retried_then_recovers():
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            return _FakeCompleted(1, stderr="Error: usage limit reached, try again later")
        return _FakeCompleted(0, stdout=_chunk_envelope([_item("job-1")]))

    sleeps = []
    results, failed = scorer.score_postings(
        [_posting("job-1")],
        system_prompt="sys",
        workers=1,
        chunk=1,
        run_fn=fake_run,
        sleep_fn=lambda s: sleeps.append(s),
        max_retries=3,
    )

    assert len(calls) == 3
    assert failed == []
    assert results["job-1"]["score"] == 0.7
    # Exponential backoff: each sleep strictly greater than the last.
    assert len(sleeps) == 2
    assert sleeps[1] > sleeps[0]


def test_usage_limit_exhausts_retries_and_reports_failed():
    def fake_run(argv, **kwargs):
        return _FakeCompleted(1, stderr="usage limit reached")

    results, failed = scorer.score_postings(
        [_posting("job-1")],
        system_prompt="sys",
        workers=1,
        chunk=1,
        run_fn=fake_run,
        sleep_fn=lambda s: None,
        max_retries=3,
    )

    assert results == {}
    assert failed == ["job-1"]


def test_other_failure_is_retried_once_then_reported_with_its_reason():
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(1)
        return _FakeCompleted(1, stderr="unrelated crash\n" + "x" * 500)

    errors = {}
    results, failed = scorer.score_postings(
        [_posting("job-1")], system_prompt="sys", workers=1, chunk=1,
        run_fn=fake_run, sleep_fn=lambda s: None, max_retries=3, errors=errors,
    )

    assert len(calls) == 2
    assert failed == ["job-1"]
    assert errors["job-1"].startswith("claude exited 1: unrelated crash")
    assert len(errors["job-1"]) <= scorer.ERROR_CHARS


def test_transient_failure_recovers_on_the_single_retry():
    answers = [_FakeCompleted(1, stderr="overloaded"), _FakeCompleted(0, stdout=_chunk_envelope([_item("job-1")]))]

    results, failed = scorer.score_postings(
        [_posting("job-1")], system_prompt="sys", workers=1, chunk=1,
        run_fn=lambda argv, **kw: answers.pop(0), sleep_fn=lambda s: None,
    )

    assert failed == [] and "job-1" in results


def test_malformed_output_is_reported_failed_not_raised():
    def fake_run(argv, **kwargs):
        return _FakeCompleted(0, stdout="not valid json")

    results, failed = scorer.score_postings(
        [_posting("job-1")],
        system_prompt="sys",
        workers=1,
        chunk=1,
        run_fn=fake_run,
        sleep_fn=lambda s: None,
    )

    assert results == {}
    assert failed == ["job-1"]


# --------------------------------------------------------------------------- #
# chunk=1 vs chunk=5 shape parity
# --------------------------------------------------------------------------- #


def test_chunk_size_does_not_change_result_shape():
    postings = [_posting(f"job-{i}") for i in range(5)]

    def fake_run(argv, *, input, **kwargs):
        ids_in_request = [p["id"] for p in postings if f"job_id: {p['id']}" in input]
        return _FakeCompleted(0, stdout=_chunk_envelope([_item(jid) for jid in ids_in_request]))

    results_c1, failed_c1 = scorer.score_postings(
        postings, system_prompt="sys", workers=1, chunk=1, run_fn=fake_run, sleep_fn=lambda s: None
    )
    results_c5, failed_c5 = scorer.score_postings(
        postings, system_prompt="sys", workers=1, chunk=5, run_fn=fake_run, sleep_fn=lambda s: None
    )

    assert failed_c1 == failed_c5 == []
    expected_ids = {p["id"] for p in postings}
    assert set(results_c1) == set(results_c5) == expected_ids
    for job_id in results_c1:
        assert set(results_c1[job_id]) == set(results_c5[job_id])
