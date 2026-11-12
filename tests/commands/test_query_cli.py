"""`jobs query` / the `query_jobs` tool: filters and counts over the postings and the ledger, read only (#339)."""

import json

from click.testing import CliRunner

from cli_utils import result_text, write_list_posting
from door.cli import cli
from door.commands import query as query_cmd
import door.core.tracker as tracker_mod


def _seed(jobs_dir):
    write_list_posting(jobs_dir, "2026-09-03", "jobindex", "jobindex.1", title="Data Analyst", company="Acme", score=0.9, language="da", scraped_at="2026-09-03T08:00:00+00:00", posted_at="2026-09-02T00:00:00+00:00")
    write_list_posting(jobs_dir, "2026-09-20", "teamtailor", "teamtailor.2", title="BI Developer", company="Globex", score=0.7, language="en", scraped_at="2026-09-20T08:00:00+00:00")
    write_list_posting(jobs_dir, "2026-10-05", "jobindex", "jobindex.3", title="Data Engineer", company="Acme", score=0.4, language="en", scraped_at="2026-10-05T08:00:00+00:00")
    write_list_posting(jobs_dir, "2026-10-06", "jobindex", "jobindex.4", title="Unscored", company="Initech", scraped_at="2026-10-06T08:00:00+00:00")
    tracker = tracker_mod.ApplicationTracker(jobs_dir / "applications.json")
    tracker.set_status("jobindex.1", "applied")
    tracker.set_status("jobindex.1", "interview:screening")
    tracker.set_status("teamtailor.2", "applied")
    tracker.save()
    out = jobs_dir / "output" / "jobindex.1"
    out.mkdir(parents=True)
    (out / "cv.pdf").write_text("x")
    (out / "cover_letter.pdf").write_text("x")


def test_everything_with_counts_by_site_company_status_and_month(cli_env):
    _seed(cli_env.jobs_dir)
    r = query_cmd._query_core(jobs_dir=cli_env.jobs_dir)
    assert r["count"] == 4
    assert r["by_site"] == {"jobindex": 3, "teamtailor": 1}
    assert r["by_company"] == {"Acme": 2, "Globex": 1, "Initech": 1}
    assert r["by_status"] == {"interview:screening": 1, "applied": 1, "unapplied": 2}
    assert r["by_month"] == {"2026-09": 2, "2026-10": 2}
    assert r["average_score"] == round((0.9 + 0.7 + 0.4) / 3, 2)
    # the best first, as words plus the id a caller passes on
    assert [row["title"] for row in r["rows"]] == ["Data Analyst", "BI Developer", "Data Engineer", "Unscored"]
    assert set(r["rows"][0]) == {"id", "title", "company", "score", "status", "site", "scraped_at", "posted_at"}
    assert "description" not in json.dumps(r)


def test_each_filter(cli_env):
    _seed(cli_env.jobs_dir)
    q = lambda **kw: query_cmd._query_core(jobs_dir=cli_env.jobs_dir, **kw)["count"]  # noqa: E731
    assert q(since="2026-10-01") == 2
    assert q(until="2026-09-30") == 2
    assert q(site="teamtailor") == 1
    assert q(company="acme") == 2
    assert q(status="applied") == 1
    assert q(status="interview") == 1  # any round
    assert q(status="unapplied") == 2
    assert q(min_score=0.65) == 2
    assert q(max_score=0.5) == 1
    assert q(language="da") == 1
    assert q(has_materials=True) == 1
    assert q(has_materials=False) == 3


def test_an_empty_result_and_the_row_limit(cli_env):
    _seed(cli_env.jobs_dir)
    r = query_cmd._query_core(jobs_dir=cli_env.jobs_dir, company="nobody")
    assert r["count"] == 0 and r["rows"] == [] and r["average_score"] is None
    assert len(query_cmd._query_core(jobs_dir=cli_env.jobs_dir, limit=2)["rows"]) == 2


def test_a_bad_date_is_refused(cli_env):
    import pytest

    with pytest.raises(ValueError):
        query_cmd._query_core(jobs_dir=cli_env.jobs_dir, since="last tuesday")


def test_it_writes_nothing(cli_env):
    _seed(cli_env.jobs_dir)
    before = sorted(p.relative_to(cli_env.jobs_dir) for p in cli_env.jobs_dir.rglob("*"))
    query_cmd._query_core(jobs_dir=cli_env.jobs_dir)
    assert sorted(p.relative_to(cli_env.jobs_dir) for p in cli_env.jobs_dir.rglob("*")) == before


def test_jobs_query_prints_the_count_and_the_rows_in_words(cli_env):
    _seed(cli_env.jobs_dir)
    result = CliRunner().invoke(cli, ["jobs", "query", "--company", "acme", "--since", "2026-09-01"])
    assert result.exit_code == 0, result_text(result)
    text = result_text(result)
    assert "2 postings" in text
    assert "Data Analyst" in text and "Acme" in text
    assert "jobindex.1" not in text
