"""`jobs/candidates.json`: the employers `follow` has yet to look at (restructure phase B)."""

import json
from datetime import datetime, timedelta, timezone

from door.core import candidates

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def test_a_missing_or_broken_file_is_an_empty_queue(tmp_path):
    assert candidates.load(tmp_path) == {}
    (tmp_path / "candidates.json").write_text("{nope")
    assert candidates.load(tmp_path) == {}
    (tmp_path / "candidates.json").write_text("[1]")
    assert candidates.load(tmp_path) == {}


def test_add_creates_an_entry_with_the_documented_shape(tmp_path):
    queue = {}
    candidates.add(queue, "Novo Nordisk A/S", links=["https://x/1"], titles=["Data Scientist"], source="jobindex", now=NOW)
    entry = queue["novonordisk"]
    assert entry == {"name": "Novo Nordisk A/S", "links": ["https://x/1"], "titles": ["Data Scientist"],
                     "sources": ["jobindex"], "first_seen": NOW.isoformat(), "last_seen": NOW.isoformat()}


def test_adding_the_same_employer_again_merges_without_duplicates(tmp_path):
    queue = {}
    candidates.add(queue, "Pleo", links=["a"], titles=["T1"], source="jobindex", now=NOW)
    later = NOW + timedelta(days=1)
    candidates.add(queue, "PLEO ApS", links=["a", "b"], titles=["T1", "T2"], source="linkedin", now=later)
    assert len(queue) == 1
    entry = queue["pleo"]
    assert entry["links"] == ["a", "b"] and entry["titles"] == ["T1", "T2"] and entry["sources"] == ["jobindex", "linkedin"]
    assert entry["first_seen"] == NOW.isoformat() and entry["last_seen"] == later.isoformat()
    assert entry["name"] == "Pleo"


def test_a_blank_name_is_ignored():
    queue = {}
    candidates.add(queue, "  ", links=["a"], titles=[], source="jobindex", now=NOW)
    assert queue == {}


def test_extra_fields_ride_along_and_merge(tmp_path):
    queue = {}
    candidates.add(queue, "Pleo", links=["a"], titles=[], source="linkedin", now=NOW, job_ids=["1"])
    candidates.add(queue, "Pleo", links=[], titles=[], source="linkedin", now=NOW, job_ids=["1", "2"])
    assert queue["pleo"]["job_ids"] == ["1", "2"]


def test_save_then_load_round_trips(tmp_path):
    queue = {}
    candidates.add(queue, "Pleo", links=["a"], titles=["T"], source="jobindex", now=NOW)
    candidates.save(tmp_path, queue)
    assert json.loads((tmp_path / "candidates.json").read_text()) == queue
    assert candidates.load(tmp_path) == queue


def test_expire_drops_entries_not_seen_for_max_age_days():
    queue = {}
    candidates.add(queue, "Old", links=["a"], titles=[], source="jobindex", now=NOW - timedelta(days=40))
    candidates.add(queue, "Recent", links=["a"], titles=[], source="jobindex", now=NOW - timedelta(days=5))
    gone = candidates.expire(queue, 30, NOW)
    assert [e["name"] for e in gone] == ["Old"] and list(queue) == ["recent"]


def test_expire_with_no_limit_keeps_everything():
    queue = {}
    candidates.add(queue, "Old", links=["a"], titles=[], source="jobindex", now=NOW - timedelta(days=400))
    assert candidates.expire(queue, None, NOW) == [] and len(queue) == 1


def test_needs_apply_link_for_a_linkedin_employer_with_only_linkedin_links():
    queue = {}
    candidates.add(queue, "Pleo", links=["https://www.linkedin.com/jobs/view/1"], titles=[], source="linkedin", now=NOW)
    candidates.add(queue, "Danske", links=["https://www.linkedin.com/jobs/view/2", "https://jobs.ashbyhq.com/x"],
                   titles=[], source="linkedin", now=NOW)
    candidates.add(queue, "Jobindex Co", links=["https://www.jobindex.dk/jobannonce/1"], titles=[], source="jobindex", now=NOW)
    assert candidates.needs_apply_link(queue["pleo"])
    assert not candidates.needs_apply_link(queue["danske"])
    assert not candidates.needs_apply_link(queue["jobindexco"])


def test_a_linkedin_employer_is_tried_by_name_before_it_awaits_its_job_page():
    queue = {}
    candidates.add(queue, "Pleo", links=["https://www.linkedin.com/jobs/view/1"], titles=[], source="linkedin", now=NOW)
    candidates.add(queue, "Danske", links=["https://jobs.ashbyhq.com/x"], titles=[], source="linkedin", now=NOW)
    pleo = queue["pleo"]
    assert candidates.needs_apply_link(pleo) and not candidates.name_tried(pleo)
    assert not candidates.awaiting_job_page(pleo)  # follow tries its name first

    candidates.mark_name_tried(pleo, NOW)

    assert candidates.name_tried(pleo) and candidates.awaiting_job_page(pleo)
    candidates.mark_name_tried(queue["danske"], NOW)
    assert not candidates.awaiting_job_page(queue["danske"])  # it has an apply link: nothing to wait for


def test_a_name_tried_mark_survives_a_merge_and_a_save(tmp_path):
    queue = {}
    candidates.add(queue, "Pleo", links=["https://www.linkedin.com/jobs/view/1"], titles=[], source="linkedin", now=NOW)
    candidates.mark_name_tried(queue["pleo"], NOW)
    candidates.add(queue, "Pleo", links=["https://www.linkedin.com/jobs/view/2"], titles=[], source="linkedin", now=NOW)
    candidates.save(tmp_path, queue)
    assert candidates.awaiting_job_page(candidates.load(tmp_path)["pleo"])


def test_a_profession_employer_never_awaits_a_job_page():
    from door.core import candidates as c

    entry = {"name": "Trendency Zrt.", "sources": ["profession"], "name_tried": "2026-10-20T00:00:00+00:00",
             "links": ["https://www.profession.hu/allas/data-scientist-1234567"], "job_ids": []}
    assert not c.needs_apply_link(entry) and not c.awaiting_job_page(entry)
