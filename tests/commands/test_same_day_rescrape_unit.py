"""A second scrape on the same day must not touch postings already scored.

`scrape` re-runs prefilter/prescreen over the whole `jobs/<today>/` directory.
Before this fix, a posting `match` had scored in the morning was fed to
prescreen again by an afternoon scrape and, if it fell outside the new top
`prescreen_top_n`, rewritten to `score=0.0` — silently dropping a real match
from `list`.
"""

import json

from door.matching.prefilter import prefilter
from door.matching.prescreen import prescreen

CONFIG = {
    "role_targets": ["data scientist"],
    "location": "Copenhagen",
    "remote": "hybrid",
    "exclude": {"keywords": ["unpaid"], "companies": []},
    "prescreen_top_n": 1,
    "prescreen_min": 0.0,
}


def _write(path, **data):
    path.parent.mkdir(parents=True, exist_ok=True)
    base = {"id": path.stem, "title": "Data Scientist", "company": "Acme", "location": "Copenhagen",
            "description": "python", "description_condensed": "python", "source": "jobindex"}
    base.update(data)
    path.write_text(json.dumps(base))
    return path


def test_prefilter_skips_postings_that_already_have_a_score(tmp_path):
    day = tmp_path / "2026-09-25"
    scored = _write(day / "jobindex" / "jobindex-acme-scored.json", score=0.82, score_reason="strong match",
                    description="unpaid mention in an old posting")
    fresh = _write(day / "jobindex" / "jobindex-acme-fresh.json")

    surviving = prefilter(day, CONFIG)

    assert surviving == [fresh]
    data = json.loads(scored.read_text())
    assert data["score"] == 0.82 and data["score_reason"] == "strong match"  # not re-excluded


def test_prescreen_never_overwrites_a_real_score(tmp_path):
    day = tmp_path / "2026-09-25"
    scored = _write(day / "jobindex" / "jobindex-acme-scored.json", title="Barista", score=0.82, score_reason="strong match")
    fresh_a = _write(day / "jobindex" / "jobindex-acme-a.json", title="Data Scientist")
    fresh_b = _write(day / "jobindex" / "jobindex-acme-b.json", title="Cook")

    kept = prescreen([scored, fresh_a, fresh_b], CONFIG, {"python"})

    assert kept == [fresh_a]
    assert json.loads(scored.read_text())["score"] == 0.82
    assert json.loads(fresh_b.read_text())["score"] == 0.0  # fresh postings are still cut as before


def test_second_same_day_scrape_keeps_the_morning_score(tmp_path):
    """The whole flow: morning posting scored, afternoon scrape adds better-looking ones."""
    day = tmp_path / "2026-09-25"
    morning = _write(day / "jobindex" / "jobindex-acme-morning.json", title="Analyst", score=0.9, score_reason="great")
    _write(day / "jobindex" / "jobindex-acme-new1.json", title="Data Scientist")
    _write(day / "jobindex" / "jobindex-acme-new2.json", title="Senior Data Scientist")

    surviving = prefilter(day, CONFIG)
    prescreen(surviving, CONFIG, {"python"})

    assert json.loads(morning.read_text())["score"] == 0.9
