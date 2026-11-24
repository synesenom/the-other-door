"""A chunk's answer is kept only for the jobs in that chunk (#551)."""

import json

from door.matching import scorer


class _Done:
    returncode = 0
    stderr = ""

    def __init__(self, stdout):
        self.stdout = stdout


def _item(job_id, score=0.7):
    return {"job_id": job_id, "score": score, "score_reason": "fits well", "matching_skills": ["Python"],
            "missing_skills": [], "language_requirement": "none", "flags": []}


def test_a_chunk_answer_naming_a_job_outside_its_chunk_changes_nothing():
    postings = [{"id": "job-a", "title": "T", "company": "C"}, {"id": "job-b", "title": "T", "company": "C"}]
    items = [_item("job-a"), _item("other-job", 0.1), _item("job-b"), _item("job-a", 0.0)]
    envelope = json.dumps({"type": "result", "is_error": False, "result": json.dumps({"results": items})})
    seen = []

    results, failed = scorer.score_postings(
        postings, system_prompt="sys", workers=1, chunk=2, run_fn=lambda *a, **k: _Done(envelope),
        sleep_fn=lambda s: None, on_result=lambda i, r: seen.append(i))

    assert failed == [] and set(results) == {"job-a", "job-b"}
    assert results["job-a"]["score"] == 0.7  # the first answer wins
    assert sorted(seen) == ["job-a", "job-b"]
