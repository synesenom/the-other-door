"""Unit tests for Emply's pure helpers (issue #437)."""

import pytest

from door.scrapers.feeds import emply


@pytest.mark.parametrize("entry, tenant", [
    ("dca", "dca"),
    (" DCA ", "dca"),
    ("dca.career.emply.com", "dca"),
    ("https://rodekors.career.emply.com/da/karriere", "rodekors"),
])
def test_tenant_accepts_a_slug_or_a_career_link(entry, tenant):
    assert emply._tenant(entry) == tenant


@pytest.mark.parametrize("url, entry", [
    ("https://dca.career.emply.com/en/national-positions", "dca"),
    ("https://rodekors.career.emply.com/da/ad/x/abc123", "rodekors"),
])
def test_detect_url_names_the_tenant(url, entry):
    det = emply.detect_url(url)
    assert (det.platform, det.entry) == ("emply", entry)


@pytest.mark.parametrize("url", [
    "https://career.emply.com/x", "https://www.emply.com/", "https://emply.com/", "https://dca.example.com/",
    "https://dca.recruitee.com/",
])
def test_detect_url_ignores_what_is_no_tenant(url):
    assert emply.detect_url(url) is None


def test_feed_url_is_none_because_the_feed_is_a_post():
    assert emply.feed_url("dca") is None


def test_ad_url_is_language_title_and_short_id():
    vacancy = {"shortId": "06mqt4", "titleAsUrl": "intern-x", "translations": [{"languageKey": "en-GB"}]}
    assert emply._ad_url("dca", vacancy) == "https://dca.career.emply.com/en/ad/intern-x/06mqt4"
    assert emply._ad_url("dca", {**vacancy, "translations": [{"languageKey": "da-DK"}]}).startswith(
        "https://dca.career.emply.com/da/ad/")
    assert emply._ad_url("dca", {**vacancy, "translations": []}).startswith("https://dca.career.emply.com/en/ad/")


def test_request_body_pages_by_offset_and_takes_every_section():
    body = emply._request_body(50, "da-DK")
    assert body["offset"] == 50 and body["sectionId"] is None and body["filters"] == []
    assert body["langCode"] == "da-DK"


# --- Aarhus University: the Emply vacancy list embedded in its own page (#431) ---

from datetime import date  # noqa: E402

from paths import TESTS_DIR  # noqa: E402

_AU_PAGE = "https://international.au.dk/about/profile/vacant-positions/"


def _au_html() -> str:
    return (TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "emply" / "au_vacancies.html").read_text(encoding="utf-8")


def test_the_embedded_vacancies_are_read_from_the_page_script():
    found = emply.embedded_vacancies(_au_html())
    assert [v["id"] for v in found] == [45307, 44944, 45619, 99999]
    assert emply.embedded_vacancies("<p>nothing</p>") == []
    assert emply.embedded_vacancies("DYCON.EmplyData.x.vacancies = [oops") == []


def test_detect_html_follows_a_page_that_embeds_the_list():
    det = emply.detect_html(_au_html(), _AU_PAGE)
    assert (det.platform, det.entry) == ("emply", _AU_PAGE)
    assert emply.detect_html("<p>nothing</p>", _AU_PAGE) is None
    assert emply.detect_html("DYCON.EmplyData.x.vacancies = []", _AU_PAGE) is None


@pytest.mark.parametrize("entry, page", [("dca", False), ("dca.career.emply.com", False),
                                         ("https://rodekors.career.emply.com/da/karriere", False),
                                         (_AU_PAGE, True)])
def test_a_page_entry_is_a_link_off_emplys_hosts(entry, page):
    assert emply._is_page(entry) is page


@pytest.mark.parametrize("title, faculty, expected", [
    ("Postdoc in Ultrafast Dynamics", "Department of Physics and Astronomy",
     "Postdoc in Ultrafast Dynamics – Department of Physics and Astronomy"),
    ("Assistant Professor at the Department of Physics and Astronomy", "Department of Physics and Astronomy",
     "Assistant Professor at the Department of Physics and Astronomy"),
    ("Technician", "Department of Agroecology - Plant Pathology, Forsøgsvej 1", "Technician – Department of Agroecology"),
    ("Technician", "", "Technician"),
])
def test_the_department_is_added_to_the_title_unless_it_is_there(title, faculty, expected):
    assert emply._embedded_title(title, faculty) == expected


def test_an_embedded_vacancy_becomes_a_posting_and_one_past_its_deadline_is_dropped():
    from datetime import datetime, timezone

    vacancies = emply.embedded_vacancies(_au_html())
    now = datetime(2026, 10, 31, tzinfo=timezone.utc)
    postings = [emply._embedded_posting(v, _AU_PAGE, "Aarhus University", now) for v in vacancies
                if emply._open(v, date(2026, 10, 31))]
    assert [p["platform_id"][-5:] for p in postings] == ["45307", "44944", "45619"]
    first = postings[0]
    assert first["title"] == "Postdoc in Probing Nanoscale Heterogeneity in Ultrafast Phase Transitions – Department of Physics and Astronomy"
    assert first["company"] == "Aarhus University" and first["location"] == "Aarhus C"
    assert first["url"] == "https://international.au.dk/about/profile/vacant-positions/job/postdoc-in-probing-nanoscale-heterogeneity-in-ultrafast-phase-transitions"
    assert first["posted_at"].startswith("2026-")
    assert first["id"] == "emply.international-au-dk-45307" and first["source"] == "emply"


def test_the_ad_text_is_the_vacancy_block_of_the_job_page():
    html = (TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "emply" / "au_job.html").read_text(encoding="utf-8")
    text = emply._embedded_description(html)
    assert text.startswith("The group studies how matter") and "Python" in text and "PhD in physics" in text
    assert "kontakt@example.com" not in text and "Deadline" not in text
    assert emply._embedded_description("<p>no block</p>") == ""
