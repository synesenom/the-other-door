"""Unit tests for the pure helpers of the Jobylon feed reader (company widget + ad pages)."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import jobylon

_FIX = Path(__file__).parent / "fixtures" / "jobylon"
_NOW = datetime(2026, 10, 31, tzinfo=timezone.utc)


def _fx(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


def _d(det):
    return None if det is None else (det.platform, det.entry)


# --- the widget list ---

def test_parse_widget_reads_every_job_of_the_list():
    items = jobylon.parse_widget(_fx("widget_2420.html"))
    assert [i["id"] for i in items] == ["393911", "393568", "391589"]
    first = items[0]
    assert first["url"] == "/jobs/393911-lyko-butikschef-till-lyko-marieberg/"
    assert first["title"] == "Butikschef till Lyko Marieberg"
    assert first["company"] == "Lyko"
    assert first["company_id"] == "2420"
    assert first["location"] == "Örebro"


def test_parse_widget_decodes_javascript_escapes():
    items = jobylon.parse_widget(_fx("widget_2420.html"))
    assert items[2]["title"] == "CRM & Loyalty Manager"


def test_parse_widget_is_none_without_the_job_list_and_empty_for_an_empty_one():
    assert jobylon.parse_widget("<html><body>Not found</body></html>") is None
    assert jobylon.parse_widget("<script>JBL.embed_v2['jobs'] = [\n        \n        ];\n</script>") == []


# --- the ad page ---

def test_parse_ad_reads_the_json_ld_and_the_company_id():
    ad = jobylon.parse_ad(_fx("job_391589.html"))
    assert ad["company_id"] == "2420"
    assert ad["title"] == "CRM & Loyalty Manager"
    assert ad["posted_at"] == "2026-10-26T14:58:41+00:00"
    assert ad["location"] == "Stockholm"
    assert ad["description"].startswith("Every message we send")
    assert "<" not in ad["description"] and "&amp;" not in ad["description"]


def test_parse_ad_without_json_ld_still_gives_the_company_id():
    ad = jobylon.parse_ad("<script>pageviewEvent.company_id = 77;</script>")
    assert ad["company_id"] == "77" and ad["description"] == ""


def test_parse_ad_of_a_page_with_nothing_is_none():
    assert jobylon.parse_ad("<html>gone</html>") is None


# --- mapping ---

def test_to_posting_maps_the_list_item_and_the_ad():
    item = jobylon.parse_widget(_fx("widget_2420.html"))[0]
    ad = jobylon.parse_ad(_fx("job_393911.html"))
    p = jobylon._to_posting(item, ad, "", _NOW)
    JobPosting.model_validate(p)
    assert p["id"] == "jobylon.393911" and p["platform_id"] == "393911" and p["source"] == "jobylon"
    assert p["url"] == "https://emp.jobylon.com/jobs/393911-lyko-butikschef-till-lyko-marieberg/"
    assert p["company"] == "Lyko" and p["location"] == "Örebro"
    assert p["posted_at"].startswith("2026-10-30T13:52:36")
    assert p["apply_type"] == "external" and p["apply_url"] == p["url"]
    assert "butikschef" in p["description"]


def test_the_followed_name_wins_over_the_widgets():
    item = jobylon.parse_widget(_fx("widget_2420.html"))[0]
    assert jobylon._to_posting(item, None, "Lyko Group AB", _NOW)["company"] == "Lyko Group AB"


def test_a_posting_without_its_ad_has_no_description_or_date():
    item = jobylon.parse_widget(_fx("widget_2420.html"))[0]
    p = jobylon._to_posting(item, None, "", _NOW)
    assert p["description"] == "" and p["posted_at"] is None


def test_the_location_falls_back_to_the_ad_when_the_list_has_none():
    item = {**jobylon.parse_widget(_fx("widget_2420.html"))[0], "location": ""}
    ad = jobylon.parse_ad(_fx("job_393911.html"))
    assert jobylon._to_posting(item, ad, "", _NOW)["location"] == "Örebro"


# --- entries ---

@pytest.mark.parametrize("entry, company_id", [
    ("2420", "2420"),
    (" 2420 ", "2420"),
    ("https://cdn.jobylon.com/jobs/companies/2420/embed/v2/", "2420"),
    ("cdn.jobylon.com/jobs/companies/2420/embed/", "2420"),
])
def test_company_id_accepts_the_id_or_a_widget_link(entry, company_id):
    assert jobylon._company_id(entry) == company_id


def test_company_id_rejects_anything_else():
    assert jobylon._company_id("lyko") is None


def test_widget_url_asks_for_the_whole_list():
    assert jobylon._widget_url("2420") == "https://cdn.jobylon.com/jobs/companies/2420/embed/v2/"


def test_scrape_missing_key_returns_empty():
    assert jobylon.scrape({}) == []


# --- feed detection (issue #282) ---

def test_detect_url_of_the_widget_names_the_company():
    assert _d(jobylon.detect_url("https://cdn.jobylon.com/jobs/companies/2420/embed/v2/?target=x")) == ("jobylon", "2420")
    assert jobylon.detect_url("https://cdn.jobylon.com/embedder.js") is None


@pytest.mark.parametrize("url", [
    "https://emp.jobylon.com/jobs/393911-lyko-butikschef-till-lyko-marieberg/",
    "https://emp.jobylon.com/jobs/393911-lyko-butikschef/?utm_source=jobbsafari",
    "https://emp.jobylon.com/applications/jobs/393911/create/",
    "https://emp.jobylon.com/jobs/393911/",
])
def test_detect_url_of_an_ad_is_jobylon_but_names_no_company_yet(url):
    det = jobylon.detect_url(url)
    assert det.platform == "jobylon" and det.entry is None and det.refusal == "cant_yet"
    assert "393911" in det.evidence


def test_detect_url_ignores_the_rest_of_jobylon():
    assert jobylon.detect_url("https://www.jobylon.com/") is None
    assert jobylon.detect_url("https://emp.jobylon.com/accounts/login/") is None
    assert jobylon.detect_url("https://emp.jobylon.com/jobs/search/") is None
    assert jobylon.detect_url("https://example.com/jobs/393911-x/") is None


def test_detect_html_reads_the_company_of_an_embed_snippet():
    snippet = "<script>jbl_company_id = 2631; jbl_version = 'v2';</script><script src='https://cdn.jobylon.com/embedder.js'>"
    assert _d(jobylon.detect_html(snippet, "https://careers.acne.example/")) == ("jobylon", "2631")
    quoted = '<script>window.jbl_company_id = "2631"</script><script src="https://cdn.jobylon.com/embedder.js"></script>'
    assert _d(jobylon.detect_html(quoted, "https://x.example/")) == ("jobylon", "2631")
    assert jobylon.detect_html("<p>jbl_company_id = 5</p>", "https://x.example/") is None  # no Jobylon script
    assert jobylon.detect_html("<p>hello</p>", "https://x.example/") is None


def test_there_is_no_json_feed_to_confirm_an_entry_with():
    assert jobylon.feed_url("2420") is None
    assert jobylon.name_probes("lyko") == []


def test_resolve_takes_the_company_from_the_ad_page():
    class Session:
        def __init__(self):
            self.urls = []

        def get(self, url, **kw):
            self.urls.append(url)

            class R:
                text = _fx("job_393911.html")
                url = "https://emp.jobylon.com/jobs/393911-lyko-butikschef-till-lyko-marieberg/"
            return R()

    session = Session()
    det = jobylon.detect_url("https://emp.jobylon.com/applications/jobs/393911/create/")
    out = jobylon.resolve(session, det, "https://emp.jobylon.com/applications/jobs/393911/create/")
    assert _d(out) == ("jobylon", "2420")
    assert session.urls == ["https://emp.jobylon.com/jobs/393911/"]


def test_resolve_keeps_an_unreadable_ad_unfollowable_and_a_named_company_as_it_is():
    class Gone:
        def get(self, url, **kw):
            raise OSError("404")

    det = jobylon.detect_url("https://emp.jobylon.com/jobs/393911-x/")
    assert jobylon.resolve(Gone(), det, "https://emp.jobylon.com/jobs/393911-x/") == det
    named = jobylon.detect_url("https://cdn.jobylon.com/jobs/companies/2420/embed/v2/")
    assert jobylon.resolve(Gone(), named, "x") is named
