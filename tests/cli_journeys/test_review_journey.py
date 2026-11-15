"""`find`, `jobs show`, `jobs prepare` and `jobs status`, the real process on a populated world (#33)."""

import pytest

from cli_world import build_world

AD = "vestvind-senior-ds-forecasting"   # scored well above min_score, not yet prepared
WORDS = "vestvind"


@pytest.fixture(scope="module")
def world():
    return build_world("mette")


def test_find_runs_the_five_steps(world):
    code, out, err = world.door("find")
    assert code == 0, f"{out}\n{err}"
    for step in ("search", "discover", "follow", "collect", "match"):
        assert step in out, out
    records = sorted((world.home / "jobs" / "runs").glob("2*.json"))
    assert records
    assert "match" in world.read(f"jobs/runs/{records[-1].name}")
    assert (world.home / "jobs" / "runs" / "latest.log").read_text(encoding="utf-8").strip()


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
    assert (world.home / "jobs" / "output" / job / "sent").is_dir()
