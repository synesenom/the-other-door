"""Unit tests for the Networx helpers: the client id, the result rows, the advert page and the feed detection.

The fixtures are real logged-out answers (trimmed, their text rewritten): Havant & South Downs College's search
(client id 3509) and its adverts, and an advert of Wates's (client id 1491), whose page uses another template."""

from datetime import datetime, timezone

import pytest

from door.core import ats_detect
from door.scrapers.feeds import networx
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "networx"


def _fx(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


# --- entries ---

@pytest.mark.parametrize("entry,cid", [
    ("3509", "3509"),
    (" 1491 ", "1491"),
    ("https://www.networxrecruitment.com/Jobs/Advert/3382599?cid=1491", "1491"),
    ("https://www.networxrecruitment.com/Jobs/Advert/3382599?cid=1491&js=0&rsid=0", "1491"),
    ("www.networxrecruitment.com/Jobs/Advert/4361924?cid=3509&s=True&t=Bank-Lecturer", "3509"),
    ("https://www.networxrecruitment.com/Website/Search?SelectedEmployers=3509", "3509"),
    ("https://current-vacancies.com/jobs/advert/4210730?cid=1616", "1616"),
])
def test_an_entry_is_a_client_id_or_a_link_that_carries_it(entry, cid):
    assert networx._cid(entry) == cid


@pytest.mark.parametrize("entry", [
    "", "acme", "12a", "https://www.networxrecruitment.com/", "https://www.networxrecruitment.com/Jobs/Advert/3382599",
    "https://www.networxrecruitment.com/Jobs/Advert/3382599?js=1491", "https://example.com/Jobs/Advert/1?cid=1491",
])
def test_an_entry_without_a_client_id_names_no_employer(entry):
    assert networx._cid(entry) is None


def test_the_search_that_lists_one_clients_adverts():
    assert networx.search_url("3509") == "https://www.networxrecruitment.com/Website/Search?SelectedEmployers=3509"
    assert networx.feed_url("3509") is None


# --- the search page ---

def test_parse_search_gives_the_rows_the_page_count_and_what_a_next_page_needs():
    search = networx.parse_search(_fx("search_3509_page1.html"))

    assert search["pages"] == 2
    assert search["token"] == "REPLACED-TOKEN"
    assert search["form"]["SelectedEmployers"] == "3509" and search["form"]["ResultsPage"] == "1"
    assert search["form"]["maxSalary"] == "999999999" and search["form"]["txtKeyword"] == ""
    assert [r["id"] for r in search["rows"]] == ["4368134", "4361924", "4359336"]
    first = search["rows"][0]
    assert first["cid"] == "3509" and first["title"] == "Bank Lecturer (Adult Learning)"
    assert first["location"] == "Havant"
    assert first["salary"] == "£29.03ph - £37.92ph (dependant on experience)"
    assert first["reference"] == "NTX1249543"
    assert first["employer"] == "Havant & South Downs College"
    assert first["teaser"].startswith("Contract Type: Bank / Hourly Paid") and "<" not in first["teaser"]
    assert not first["teaser"].endswith("...")


def test_the_sponsored_adverts_of_other_clients_are_not_rows():
    ids = {r["id"] for r in networx.parse_search(_fx("search_3509_page1.html"))["rows"]}

    assert "4343489" not in ids   # a sponsored advert of RSK Group (client 1877) the page carries


def test_a_search_without_adverts_is_valid_and_empty():
    search = networx.parse_search(_fx("search_1491_empty.html"))

    assert search["rows"] == [] and search["pages"] == 0


def test_a_page_that_is_no_search_result_is_refused():
    for text in ("", "<html><h1>Error</h1></html>"):
        with pytest.raises(ValueError):
            networx.parse_search(text)


def test_parse_more_reads_the_html_a_next_page_answers_in_json():
    pages, rows = networx.parse_more(_fx("more_3509_page2.json"))

    assert pages == 2
    assert [r["id"] for r in rows] == ["4359336", "4359362", "4359422"]
    assert rows[1]["title"] == "EHCP Coordinator" and rows[1]["location"] == "Alton"


def test_parse_more_refuses_what_is_not_the_json_answer():
    for text in ("", "<html>Error</html>", "[]", '{"x": 1}'):
        with pytest.raises(ValueError):
            networx.parse_more(text)


# --- the advert page ---

def test_parse_ad_reads_the_text_blocks_and_the_json_ld_the_site_writes_unclosed():
    ad = networx.parse_ad(_fx("ad_4361924.html"))

    assert ad["posted_at"] == datetime(2026, 10, 27, tzinfo=timezone.utc)
    assert ad["organization"] == "Havant & South Downs College"
    assert ad["description"].startswith("The Vacancy\nContract Type: Bank / Hourly Paid\nAbout the Role\nWe are looking for committed Bank Lecturers")
    assert "About Us\nWould you like to work with us?" in ad["description"]
    assert "<" not in ad["description"] and "[@" not in ad["description"]


def test_an_advert_of_another_template_has_no_json_ld_but_its_text():
    ad = networx.parse_ad(_fx("ad_3382599_wates.html"))

    assert ad["posted_at"] is None and ad["organization"] == ""
    assert ad["description"].startswith("The Vacancy\nTo train as a roofer")
    assert "Work for Wates\nWates is a family-owned" in ad["description"]


def test_a_page_with_neither_text_nor_markup_has_no_ad():
    assert networx.parse_ad("<html><body><h1>Error</h1></body></html>") is None
    assert networx.parse_ad("") is None


def test_the_unclosed_json_ld_is_read_and_another_broken_one_is_not():
    assert networx._load_ld('{"datePosted": "2026-10-27", "hiringOrganization": {"name": "A"}') == {
        "datePosted": "2026-10-27", "hiringOrganization": {"name": "A"}}
    assert networx._load_ld('{"datePosted": ') is None
    assert networx._load_ld('{"a": 1}') == {"a": 1}


def test_the_posting_is_built_from_a_row_and_its_ad():
    row = networx.parse_search(_fx("search_3509_page1.html"))["rows"][1]
    ad = networx.parse_ad(_fx("ad_4361924.html"))
    now = datetime(2026, 11, 4, tzinfo=timezone.utc)

    posting = networx._to_posting(row, ad, "", now)

    assert posting["id"] == "networx.4361924" and posting["platform_id"] == "4361924"
    assert posting["title"] == "Bank Lecturer" and posting["location"] == "Alton"
    assert posting["company"] == "Havant & South Downs College"
    assert posting["url"] == "https://www.networxrecruitment.com/Jobs/Advert/4361924?cid=3509"
    assert posting["apply_url"] == posting["url"] and posting["source"] == "networx"
    assert posting["posted_at"].startswith("2026-10-27")
    assert posting["description"].startswith("Salary: £29.03ph - £37.92ph (dependant on experience)\n\nThe Vacancy")
    assert networx._to_posting(row, ad, "HSDC", now)["company"] == "HSDC"


def test_without_the_ad_the_posting_carries_the_rows_teaser_and_employer():
    row = networx.parse_search(_fx("search_3509_page1.html"))["rows"][0]

    posting = networx._to_posting(row, None, "", datetime(2026, 11, 4, tzinfo=timezone.utc))

    assert posting["company"] == "Havant & South Downs College" and posting["posted_at"] is None
    assert "We are recruiting Bank Lecturers" in posting["description"]


# --- feed detection ---

def test_an_advert_link_names_its_client():
    det = networx.detect_url("https://www.networxrecruitment.com/Jobs/Advert/3382599?cid=1491&js=0&rsid=0")

    assert (det.platform, det.entry) == ("networx", "1491")
    assert det.config_key == "networx_companies"
    assert networx.detect_url("https://current-vacancies.com/jobs/advert/4210730?cid=1616").entry == "1616"


@pytest.mark.parametrize("url", [
    "https://www.networxrecruitment.com/", "https://www.networxrecruitment.com/Jobs/Advert/3382599",
    "https://www.networxrecruitment.com/Jobs/Advert/3382599?js=1491", "https://example.com/Jobs/Advert/1?cid=1491",
    "https://www.networxrecruitment.com/PrivacyPolicy",
])
def test_a_link_that_names_no_client_is_no_detection(url):
    assert networx.detect_url(url) is None


def test_the_shared_hosts_are_no_employers_site():
    assert networx.is_shared_host("www.networxrecruitment.com") and networx.is_shared_host("current-vacancies.com")
    assert not networx.is_shared_host("careers.wates.co.uk")
    assert ats_detect.is_shared_ats_host("https://www.networxrecruitment.com/")


def test_the_dispatcher_finds_networx_before_the_generic_career_site_reader():
    """The advert pages carry JobPosting JSON-LD, which `career_sites` takes for the employer's own site
    (the shared host, with every client's adverts)."""
    page = _fx("ad_4361924.html") + '<a href="https://www.networxrecruitment.com/Jobs/Advert/4361924?cid=3509&s=True">Apply</a>'

    det = ats_detect.from_html(page, "https://www.hsdc.ac.uk/jobs")
    assert (det.platform, det.entry) == ("networx", "3509")
    assert ats_detect.from_url("https://www.networxrecruitment.com/Jobs/Advert/3382599?cid=1491").platform == "networx"
    assert {"networxrecruitment.com", "current-vacancies.com"} <= set(ats_detect.platform_domains())
