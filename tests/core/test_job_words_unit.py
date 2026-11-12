"""`_common.job_words`: the shortest words that name a posting uniquely."""

from cli_utils import write_list_posting
from door.commands import _common as common
from door.core.selection import resolve_job_ref


def _post(jobs_dir, job_id, company, title, score=0.9):
    write_list_posting(jobs_dir, "2026-07-01", "jobindex", job_id, score=score, company=company, title=title)
    return {"id": job_id, "company": company, "title": title}


def test_company_word_is_enough_when_unique(tmp_path):
    posting = _post(tmp_path, "jobindex.a1", "Trustpilot A/S", "Data Scientist")
    _post(tmp_path, "jobindex.a2", "Novo Nordisk", "Data Scientist")
    words = common.job_words(posting, tmp_path)
    assert words == "trustpilot"
    assert resolve_job_ref(words, tmp_path) == "jobindex.a1"


def test_two_jobs_at_one_company_need_a_title_word_quoted(tmp_path):
    first = _post(tmp_path, "jobindex.b1", "Acme", "Data Scientist")
    second = _post(tmp_path, "jobindex.b2", "Acme", "Backend Engineer")
    for posting in (first, second):
        words = common.job_words(posting, tmp_path)
        assert " " in words and words.startswith("'") and words.endswith("'")
        assert resolve_job_ref(words.strip("'"), tmp_path) == posting["id"]


def test_falls_back_to_the_id_when_words_cannot_tell_them_apart(tmp_path):
    first = _post(tmp_path, "jobindex.c1", "Acme", "Data Scientist")
    _post(tmp_path, "jobindex.c2", "Acme", "Data Scientist")
    assert common.job_words(first, tmp_path) == "jobindex.c1"


def test_job_label_falls_back_to_the_id_without_a_posting(tmp_path):
    assert common._job_label("nope.1", tmp_path) == "nope.1"
