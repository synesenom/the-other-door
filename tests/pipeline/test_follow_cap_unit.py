"""`follow` asks the careers model about at most `careers_ai.MAX_ASKS` employers a run (#551)."""

import re
from datetime import datetime, timezone

import responses

from door.core.employers import careers_ai
from door.core.jobs import candidates
from door.pipeline import follow

NOW = datetime.now(timezone.utc)


@responses.activate
def test_the_careers_model_is_asked_about_at_most_the_cap_and_the_rest_stay_queued(env, monkeypatch):
    calls = []
    monkeypatch.setattr(careers_ai, "ask_careers_url", lambda name, *a, **k: calls.append(name))
    queue = candidates.load(env.jobs_dir)
    for i in range(50):
        candidates.add(queue, f"Acme{i}", links=[f"https://acme{i}.dk/jobs/1"], titles=["Data Scientist"],
                       source="linkedin" if i % 2 else "profession", now=NOW)
    candidates.save(env.jobs_dir, queue)
    responses.add(responses.GET, re.compile(r"https?://.*"), status=404)

    block = follow._follow_core(jobs_dir=env.jobs_dir, profile_dir=env.profile_dir)

    assert len(calls) == careers_ai.MAX_ASKS == 30
    assert block["kept"] == 20
    assert len(candidates.load(env.jobs_dir)) == 20
