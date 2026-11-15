"""`find`, `jobs show`, `jobs prepare` and `jobs status`, the real process on a populated world (#33)."""

import pytest

from cli_world import build_world

AD = "vestvind-senior-ds-forecasting"   # scored well above min_score, not yet prepared
WORDS = "vestvind"


@pytest.fixture(scope="module")
def world():
    return build_world("mette")


def test_find_runs_the_five_steps(world):
    runs = world.home / "jobs" / "runs"
    log = runs / "latest.log"
    before = set(runs.glob("2*.json"))
    log_before = len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0
    code, out, err = world.door("find")
    assert code == 0, f"{out}\n{err}"
    for n, step in enumerate(("search", "discover", "follow", "collect", "match"), 1):
        assert f"[{n}/5] {step}" in out, out
    new = set(runs.glob("2*.json")) - before
    assert len(new) == 1
    record = world.read(f"jobs/runs/{new.pop().name}")
    assert record["match"] is not None
    assert record["search"] is not None
    assert len(log.read_text(encoding="utf-8").splitlines()) == log_before + 1


def test_jobs_show_names_the_posting(world):
    code, out, err = world.door("jobs", "show", WORDS)
    assert code == 0, f"{out}\n{err}"
    assert world.jobs[AD]["title"] in out
    assert "Vestvind" in out


def test_jobs_prepare_writes_the_materials(world):
    job = world.jobs[AD]["id"]
    code, out, err = world.door("jobs", "prepare", WORDS)
    assert code == 0, f"{out}\n{err}"
    folder = world.home / "jobs" / "output" / job
    for name in ("cv.pdf", "cover_letter.pdf", "facts.json"):
        assert (folder / name).exists(), (name, out)
    assert "tailor" in world.claude_kinds()
    assert f"jobs/output/{job}/cv.pdf" in out.replace("\\", "/")


def test_jobs_status_records_applied(world):
    job = world.jobs[AD]["id"]
    code, out, err = world.door("jobs", "status", WORDS, "applied")
    assert code == 0, f"{out}\n{err}"
    entry = world.read("jobs/applications.json")[job]
    assert entry["status"] == "applied"
    assert entry["history"][-1]["status"] == "applied"
    sent = world.home / "jobs" / "output" / job / "sent"
    assert (sent / "cv.pdf").exists() and (sent / "cover_letter.pdf").exists()
    assert all(len(h) == 64 for h in entry["materials"].values()) and "cv.pdf" in entry["materials"]
