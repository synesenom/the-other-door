"""Unit tests for the ReachMee helpers (issue #527): entries, the customer script, the job list, an ad page,
and the detection of a ReachMee link."""

from datetime import datetime, timezone

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import reachmee
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "reachmee"
_NOW = datetime(2026, 10, 31, tzinfo=timezone.utc)


def _fx(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


# --- entries ---

@pytest.mark.parametrize("entry, expected", [
    ("I003/354/5", ("web103.reachmee.com", "I003", "354", "5")),
    (" i003/354/12 ", ("web103.reachmee.com", "I003", "354", "12")),
    ("web104.reachmee.com/I005/77/2", ("web104.reachmee.com", "I005", "77", "2")),
    ("https://web103.reachmee.com/ext/I003/354/main?site=5&validator=abc&lang=SE", ("web103.reachmee.com", "I003", "354", "5")),
    ("I003/354", None),
    ("oru", None),
    ("", None),
])
def test_entry_parts(entry, expected):
    assert reachmee._entry_parts(entry) == expected


# --- the customer script ---

def test_the_customer_script_gives_the_validator_and_the_default_language():
    assert reachmee._parse_customer_js(_fx("customerjs_sv.js")) == {"validator": "5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a", "lang": "SE"}
    assert reachmee._parse_customer_js(_fx("customerjs_en.js"))["lang"] == "UK"


@pytest.mark.parametrize("text", ["", "<html>404</html>", "var validator = '';"])
def test_a_customer_script_without_a_validator_is_none(text):
    assert reachmee._parse_customer_js(text) is None


# --- the job list ---

def test_the_list_gives_the_employer_and_one_row_per_ad():
    name, rows = reachmee._parse_list(_fx("list_sv.html"))

    assert name == "Örebro universitet"
    assert [r["job_id"] for r in rows] == ["12975", "12970"]
    assert rows[0]["title"] == "Tentamensadministratör till Studentavdelningen"
    assert rows[0]["url"] == ("https://web103.reachmee.com/ext/I003/354/job?site=5&lang=SE"
                              "&validator=5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a&job_id=12975")


def test_the_english_list_reads_the_same_way():
    name, rows = reachmee._parse_list(_fx("list_en.html"))

    assert name == "Örebro universitet"
    assert [r["title"] for r in rows] == ["Postdoctoral researcher in Vaccine Development", "Research Assistant in Biomedicine"]


def test_an_empty_list_has_a_name_and_no_rows():
    name, rows = reachmee._parse_list(_fx("list_empty.html"))

    assert (name, rows) == ("Arbetsgivarverket", [])


def test_a_page_that_is_no_list_has_no_rows():
    assert reachmee._parse_list("<html><title>404 Page Not Found</title></html>") == ("", [])
    assert not reachmee._has_list("<html><title>404 Page Not Found</title></html>")
    assert reachmee._has_list(_fx("list_empty.html")) and reachmee._has_list(_fx("list_sv.html"))


def test_a_location_column_is_kept_when_the_list_has_one():
    html = ("<html><title>Acme | Jobb</title><div id='mainjoblist'><table id='jobsTable'><thead><tr><th>Jobb</th><th>Ort</th></tr></thead><tbody>"
            "<tr><td><a href='https://web103.reachmee.com/ext/I1/2/job?site=1&job_id=9'>Chef</a></td><td>Malmö</td></tr>"
            "</tbody></table></div></html>")

    _, rows = reachmee._parse_list(html)

    assert rows[0]["location"] == "Malmö"


# --- an ad page ---

def test_the_swedish_ad_gives_title_place_reference_and_text():
    job = reachmee._parse_job(_fx("job_sv_12975.html"))

    assert job["title"] == "Tentamensadministratör till Studentavdelningen"
    assert job["location"] == "Örebro"
    assert job["reference"] == "ORU 2.1.2-06458/2026"
    assert job["description"].startswith("Vid Universitetet skapar vi framtiden")
    assert "Kvalifikationer" in job["description"] and "<" not in job["description"]


def test_the_english_ad_gives_its_own_text():
    job = reachmee._parse_job(_fx("job_en_12971.html"))

    assert job["title"] == "Research Assistant in Biomedicine"
    assert job["location"] == "Orebro"
    assert job["description"].startswith("We are looking for a research assistant")


def test_a_page_without_an_ad_is_empty():
    assert reachmee._parse_job("<html><body>nothing</body></html>") == {}


# --- mapping ---

def test_a_posting_carries_the_tenant_in_its_id_and_the_ad_link():
    _, rows = reachmee._parse_list(_fx("list_sv.html"))
    job = reachmee._parse_job(_fx("job_sv_12975.html"))

    posting = reachmee._to_posting(rows[0], job, "Örebro universitet", ("web103.reachmee.com", "I003", "354", "5"), _NOW)

    JobPosting.model_validate(posting)
    assert posting["platform_id"] == "i003-354-12975"
    assert posting["id"] == "reachmee.i003-354-12975"
    assert posting["company"] == "Örebro universitet" and posting["location"] == "Örebro"
    assert posting["url"] == posting["apply_url"] == rows[0]["url"]
    assert posting["source"] == "reachmee" and posting["posted_at"] is None


def test_the_list_row_stands_in_for_what_the_ad_page_lacks():
    row = {"job_id": "9", "title": "Chef", "url": "https://web103.reachmee.com/ext/I1/2/job?site=1&job_id=9", "location": "Malmö"}

    posting = reachmee._to_posting(row, {}, "Acme", ("web103.reachmee.com", "I001", "2", "1"), _NOW)

    assert posting["title"] == "Chef" and posting["location"] == "Malmö"


# --- detection ---

@pytest.mark.parametrize("url, entry", [
    ("https://web103.reachmee.com/ext/I003/354/main?site=5&validator=abc&lang=SE&rmpage=job&rmjob=12986", "I003/354/5"),
    ("https://web103.reachmee.com/ext/I003/354/job?site=12&lang=UK&validator=abc&job_id=12985", "I003/354/12"),
    ("https://web103.reachmee.com/customerjs/I021-1746-6.js", "I021/1746/6"),
    ("https://web104.reachmee.com/ext/I005/77/main?site=2&validator=x", "web104.reachmee.com/I005/77/2"),
])
def test_a_reachmee_link_names_the_publishing_site(url, entry):
    det = reachmee.detect_url(url)

    assert det.platform == "reachmee" and det.entry == entry and det.refusal is None


@pytest.mark.parametrize("url", [
    "https://web103.reachmee.com/ext/I003/354/main?validator=abc",
    "https://site106.reachmee.com/Public/rssfeed/external.ashx?id=5&InstallationID=I003&CustomerName=oru&lang=SE",
    "https://login.reachmee.com/",
])
def test_a_reachmee_link_that_names_no_site_is_known_but_not_followed_yet(url):
    det = reachmee.detect_url(url)

    assert det.platform == "reachmee" and det.entry is None and det.refusal == "cant_yet"


@pytest.mark.parametrize("url", ["https://www.reachmee.com/", "https://example.invalid/x", "https://oru.se/jobs", ""])
def test_other_links_are_not_reachmee(url):
    assert reachmee.detect_url(url) is None


def test_a_page_that_loads_the_customer_script_is_a_reachmee_career_page():
    html = '<script src="https://web103.reachmee.com/customerjs/I003-354-5.js"></script>'

    det = reachmee.detect_html(html, "https://www.oru.se/jobba-hos-oss/lediga-jobb/")

    assert det.platform == "reachmee" and det.entry == "I003/354/5"


def test_a_page_with_the_reachmee_frame_is_one_too():
    html = '<iframe src="https://web103.reachmee.com/ext/I003/354/main?site=12&amp;validator=abc&amp;lang=UK"></iframe>'

    assert reachmee.detect_html(html, "https://www.oru.se/english/").entry == "I003/354/12"


def test_a_page_without_reachmee_is_not_detected():
    assert reachmee.detect_html("<html>careers</html>", "https://acme.example/") is None


def test_the_link_shape_is_proof_enough():
    assert reachmee.feed_url("I003/354/5") is None


def test_two_customers_with_the_same_ad_number_get_different_ids():
    row = {"job_id": "77", "title": "Chef", "url": "https://web103.reachmee.com/ext/I003/1/job?site=1&job_id=77"}

    a = reachmee._to_posting(row, {}, "A", ("web103.reachmee.com", "I003", "1", "1"), _NOW)
    b = reachmee._to_posting(row, {}, "B", ("web103.reachmee.com", "I003", "2", "1"), _NOW)

    assert a["id"] != b["id"] and a["id"].startswith("reachmee.")


def test_the_page_that_names_the_employer_is_the_list_not_the_ad():
    ad = "https://web103.reachmee.com/ext/I003/354/job?site=5&lang=SE&validator=abc&job_id=12975"

    assert reachmee.name_page("I003/354/5", ad) == "https://web103.reachmee.com/ext/I003/354/main?site=5&validator=abc&lang=SE"
    embed = "https://web103.reachmee.com/customerjs/I003-354-5.js"
    assert reachmee.name_page("I003/354/5", embed) == embed
