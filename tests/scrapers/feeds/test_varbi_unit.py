"""Unit tests for Varbi's pure helpers (issue #525)."""

import pytest

from door.scrapers.feeds import varbi
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "varbi"


def _read(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("entry, tenant", [
    ("ki", "ki"),
    (" KTH ", "kth"),
    ("ki.varbi.com", "ki"),
    ("https://uu.varbi.com/se/what:job/jobID:1/", "uu"),
])
def test_tenant_accepts_a_slug_or_a_link(entry, tenant):
    assert varbi._tenant(entry) == tenant


@pytest.mark.parametrize("url, entry", [
    ("https://ki.varbi.com/en/what:job/jobID:985204/", "ki"),
    ("https://uu.varbi.com/", "uu"),
    ("http://kth.varbi.com/se/what:job/jobID:984227/?lang=en", "kth"),
])
def test_detect_url_names_the_tenant(url, entry):
    det = varbi.detect_url(url)
    assert (det.platform, det.entry) == ("varbi", entry)
    assert det.config_key == "varbi_tenants"


@pytest.mark.parametrize("url", [
    "https://www.varbi.com/se/", "https://web.varbi.com/", "https://profile.varbi.com/login/",
    "https://cdn.varbi.com/134/a.jpg", "https://varbi.com/", "https://ki.example.com/", "https://x.y.varbi.com/",
    "https://ki.recruitee.com/",
])
def test_detect_url_ignores_what_is_no_tenant(url):
    assert varbi.detect_url(url) is None


def test_the_feed_is_confirmed_by_the_host_not_by_a_json_list():
    assert varbi.feed_url("ki") is None


def test_alive_url_is_the_rss_feed():
    assert varbi.alive_url("ki") == "https://ki.varbi.com/what:rssfeed/"
    assert varbi.alive_url("https://KI.varbi.com/se/") == "https://ki.varbi.com/what:rssfeed/"


def test_the_employer_is_named_by_the_board_page_not_an_ad_page():
    assert varbi.name_page("ki", "https://ki.varbi.com/en/what:job/jobID:985204/") == "https://ki.varbi.com/"


def test_job_id_is_read_from_the_ad_link():
    assert varbi._job_id("https://ki.varbi.com/en/what:job/jobID:985204/") == "985204"
    assert varbi._job_id("https://ki.varbi.com/what:job/jobID:381177/?lang=en") == "381177"
    assert varbi._job_id("https://ki.varbi.com/se/") == ""


def test_the_feed_is_read_into_a_name_and_its_ads():
    name, items = varbi.parse_feed(_read("ki_rss.xml"))

    assert name == "Karolinska Institutet (KI)"
    assert [i["id"] for i in items] == ["985313", "981455", "985204"]
    first = items[0]
    assert first["title"] == "Postdoctoral Research Associate in Immuno-oncology and Autoimmunology"
    assert first["url"] == "https://ki.varbi.com/en/what:job/jobID:985313/"
    assert first["posted_at"].isoformat() == "2026-10-29T00:00:00+01:00"
    assert first["description"].startswith("Do you want to contribute to improving human health?")
    assert "Who are you?" in first["description"]


def test_a_feed_that_is_not_rss_is_an_error():
    with pytest.raises(ValueError):
        varbi.parse_feed("<html><body>Error 404, Page not found.</body></html>")
    with pytest.raises(ValueError):
        varbi.parse_feed("not xml at all <")


def test_a_feed_without_ads_is_empty_not_an_error():
    name, items = varbi.parse_feed('<rss version="2.0"><channel><title>New jobs at Acme</title></channel></rss>')
    assert (name, items) == ("Acme", [])


@pytest.mark.parametrize("title, name", [
    ("New jobs at KTH Royal Institute of Technology", "KTH Royal Institute of Technology"),
    ("Nya lediga jobb hos Uppsala universitet", "Uppsala universitet"),
    ("Something else", "Something else"),
    ("", ""),
])
def test_the_channel_title_names_the_employer(title, name):
    assert varbi._channel_name(title) == name


def test_the_list_gives_place_department_and_deadline_by_job_id():
    rows = varbi.parse_list(_read("ki_list.html"))

    assert set(rows) == {"985313", "981455", "985204"}
    assert rows["985313"] == {"location": "Solna", "department": "Karolinska Institutet (KI), Institutionen för onkologi-patologi",
                              "deadline": "2026-11-19"}
    assert rows["981455"]["department"].endswith("IT & Systemutveckling")


def test_a_page_without_the_list_has_no_rows():
    assert varbi.parse_list("<html><body>nothing</body></html>") == {}


def test_a_posting_takes_the_ads_text_and_the_lists_place():
    from datetime import datetime, timezone

    _, items = varbi.parse_feed(_read("kth_rss.xml"))
    rows = varbi.parse_list(_read("kth_list.html"))
    now = datetime(2026, 10, 31, tzinfo=timezone.utc)

    posting = varbi._to_posting(items[0], "kth", now, "KTH", rows.get(items[0]["id"]))

    assert posting["id"] == "varbi.kth-varbi-com-984227"
    assert posting["platform_id"] == "kth.varbi.com-984227"
    assert posting["company"] == "KTH" and posting["location"] == "Stockholm"
    assert posting["source"] == "varbi" and posting["apply_type"] == "external"
    assert posting["url"] == posting["apply_url"] == "https://kth.varbi.com/en/what:job/jobID:984227/"
    assert posting["description"].startswith("Arbetsuppgifter")


def test_a_posting_without_a_list_row_has_no_place():
    from datetime import datetime, timezone

    _, items = varbi.parse_feed(_read("kth_rss.xml"))
    posting = varbi._to_posting(items[0], "kth", datetime(2026, 10, 31, tzinfo=timezone.utc), "KTH", None)
    assert posting["location"] == ""
