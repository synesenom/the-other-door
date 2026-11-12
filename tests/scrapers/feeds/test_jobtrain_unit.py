"""Unit tests for the Jobtrain helpers: entries, the job cards, the ad's JSON-LD and the feed detection.

The fixtures are real logged-out answers (trimmed, their text rewritten): the Leigh Academies Trust list on the
shared host ``www.jobtrain.co.uk/<tenant>`` and Crisis's list on its own host ``jobs.crisis.org.uk``."""

from datetime import datetime, timezone

import pytest

from door.core import ats_detect
from door.scrapers.feeds import jobtrain
from paths import TESTS_DIR

_FX = TESTS_DIR / "scrapers" / "feeds" / "fixtures" / "jobtrain"


def _fx(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


# --- entries ---

@pytest.mark.parametrize("entry,base,label", [
    ("leighacademiestrust", "https://www.jobtrain.co.uk/leighacademiestrust", "leighacademiestrust"),
    (" LeighAcademiesTrust ", "https://www.jobtrain.co.uk/leighacademiestrust", "leighacademiestrust"),
    ("https://www.jobtrain.co.uk/leighacademiestrust/Job/JobDetail?JobId=9610", "https://www.jobtrain.co.uk/leighacademiestrust", "leighacademiestrust"),
    ("www.jobtrain.co.uk/leighacademiestrust", "https://www.jobtrain.co.uk/leighacademiestrust", "leighacademiestrust"),
    ("jobs.crisis.org.uk", "https://jobs.crisis.org.uk", "jobs.crisis.org.uk"),
    ("https://jobs.crisis.org.uk/Home/Job", "https://jobs.crisis.org.uk", "jobs.crisis.org.uk"),
])
def test_an_entry_is_a_tenant_slug_a_link_on_the_shared_host_or_a_custom_host(entry, base, label):
    assert jobtrain._target(entry) == (base, label)


@pytest.mark.parametrize("entry", ["", "  ", "https://www.jobtrain.co.uk/", "www.jobtrain.co.uk", "jobtrain.co.uk",
                                   "jobs-crisis.jobtrain.co.uk", "bad slug", "https://www.jobtrain.co.uk/Content/x.css"])
def test_an_entry_that_names_no_tenant_has_no_target(entry):
    assert jobtrain._target(entry) is None


def test_there_is_no_feed_check_and_the_alive_check_is_the_first_card_page():
    assert jobtrain.feed_url("leighacademiestrust") is None
    assert jobtrain.alive_url("leighacademiestrust") == "https://www.jobtrain.co.uk/leighacademiestrust/Home/_JobCard?Skip=0"
    assert jobtrain.alive_url("jobs.crisis.org.uk") == "https://jobs.crisis.org.uk/Home/_JobCard?Skip=0"
    assert jobtrain.alive_url("") is None


# --- the job cards ---

def test_parse_cards_gives_the_total_and_each_card():
    total, cards = jobtrain.parse_cards(_fx("lat_cards_1.html"))

    assert total == 4
    assert [c["id"] for c in cards] == ["9610", "9609", "9600"]
    first = cards[0]
    assert first["title"] == "Exams Officer"
    assert first["location"] == "Leigh Academy Milestone"
    assert first["reference"] == "009580"


def test_parse_cards_of_a_custom_host_list():
    total, cards = jobtrain.parse_cards(_fx("crisis_cards.html"))

    assert total == 2
    assert [(c["id"], c["title"], c["location"]) for c in cards] == [
        ("11924", "Data Insight Analyst", "London"), ("11906", "Prospect Research Manager", "London")]


def test_a_list_without_a_total_is_not_a_job_list():
    for text in ("", "<html><h1>Not found</h1></html>", "<input type='hidden' id='other' value='3'>"):
        with pytest.raises(ValueError):
            jobtrain.parse_cards(text)


def test_a_list_with_a_total_of_none_is_valid_and_empty():
    assert jobtrain.parse_cards('<input type="hidden" id="totalCurrentRecords" value="0">'
                                '<input type="hidden" id="totalMatchRecords" value="0">') == (0, [])


# --- the ad ---

def test_parse_ad_reads_the_json_ld_the_site_writes_with_an_escaped_plus():
    ad = jobtrain.parse_ad(_fx("lat_9610.html"))

    assert ad["posted_at"] == datetime(2026, 11, 3, tzinfo=timezone.utc)
    assert ad["organization"] == "LeighAcademiesTrust"
    assert ad["location"] == "Hartley, Kent, GB"
    assert ad["description"].startswith("Competitive salary with progression opportunities")
    assert "Leigh Academy Milestone is recruiting an Exams Officer" in ad["description"]
    assert "<" not in ad["description"] and "\\u" not in ad["description"]


def test_an_empty_region_is_left_out_of_the_location():
    assert jobtrain.parse_ad(_fx("lat_9600.html"))["location"] == "Rochester, GB"


def test_the_custom_host_ad_has_the_same_shape():
    ad = jobtrain.parse_ad(_fx("crisis_11924.html"))

    assert ad["organization"] == "Crisis" and ad["location"] == "London, England, GB"
    assert ad["posted_at"] == datetime(2026, 11, 2, tzinfo=timezone.utc)


def test_a_page_without_a_job_posting_has_no_ad():
    assert jobtrain.parse_ad("<html><body>Job not found</body></html>") is None
    assert jobtrain.parse_ad('<script type="application/ld+json">{"@type": "Organization"}</script>') is None
    assert jobtrain.parse_ad('<script type="application/ld+json">{broken</script>') is None


def test_the_posting_is_built_from_a_card_and_its_ad():
    _total, cards = jobtrain.parse_cards(_fx("lat_cards_1.html"))
    ad = jobtrain.parse_ad(_fx("lat_9610.html"))
    now = datetime(2026, 11, 4, tzinfo=timezone.utc)

    posting = jobtrain._to_posting(cards[0], ad, "https://www.jobtrain.co.uk/leighacademiestrust", "leighacademiestrust",
                                   "Leigh Academies Trust", now)

    assert posting["id"] == "jobtrain.leighacademiestrust-9610"
    assert posting["platform_id"] == "leighacademiestrust-9610"
    assert posting["title"] == "Exams Officer" and posting["company"] == "Leigh Academies Trust"
    assert posting["url"] == "https://www.jobtrain.co.uk/leighacademiestrust/Job/JobDetail?JobId=9610"
    assert posting["apply_url"] == posting["url"] and posting["source"] == "jobtrain"
    assert posting["location"] == "Hartley, Kent, GB"
    assert posting["posted_at"].startswith("2026-11-03")


def test_without_a_name_the_company_is_the_ads_organisation_then_the_tenant():
    _total, cards = jobtrain.parse_cards(_fx("crisis_cards.html"))
    ad = jobtrain.parse_ad(_fx("crisis_11924.html"))
    now = datetime(2026, 11, 4, tzinfo=timezone.utc)

    assert jobtrain._to_posting(cards[0], ad, "https://jobs.crisis.org.uk", "jobs.crisis.org.uk", "", now)["company"] == "Crisis"
    assert jobtrain._to_posting(cards[0], None, "https://jobs.crisis.org.uk", "jobs.crisis.org.uk", "", now)["company"] == "jobs.crisis.org.uk"
    assert jobtrain._to_posting(cards[0], None, "https://jobs.crisis.org.uk", "jobs.crisis.org.uk", "", now)["location"] == "London"


# --- feed detection ---

def test_a_link_on_the_shared_host_names_its_tenant():
    det = jobtrain.detect_url("https://www.jobtrain.co.uk/leighacademiestrust/Job/JobDetail?JobId=8691")

    assert (det.platform, det.entry) == ("jobtrain", "leighacademiestrust")
    assert det.config_key == "jobtrain_companies"


@pytest.mark.parametrize("url", [
    "https://www.jobtrain.co.uk/", "https://jobtrain.co.uk/privacy-policy/", "https://www.jobtrain.co.uk/dist/styles/app.css",
    "https://example.com/jobtrain.co.uk/x", "https://notjobtrain.co.uk/acme/Home/Job",
])
def test_a_link_that_names_no_tenant_is_no_detection(url):
    assert jobtrain.detect_url(url) is None


def test_a_career_host_that_is_a_cname_for_a_jobtrain_host_is_the_entry():
    det = jobtrain.detect_cname("jobs.crisis.org.uk", "jobs-crisis.jobtrain.co.uk", "jobs.crisis.org.uk is a CNAME for jobs-crisis.jobtrain.co.uk")

    assert (det.platform, det.entry) == ("jobtrain", "jobs.crisis.org.uk")
    assert jobtrain.detect_cname("careers.acme.com", "www.jobtrain.co.uk", "x") is None
    assert jobtrain.detect_cname("careers.acme.com", "acme.example.com", "x") is None


def test_a_page_of_the_shared_host_names_its_tenant_and_a_custom_host_page_names_itself():
    shared = jobtrain.detect_html(_fx("lat_home.html"), "https://www.jobtrain.co.uk/leighacademiestrust/Home/Job")
    custom = jobtrain.detect_html(_fx("crisis_home.html"), "https://jobs.crisis.org.uk/Home/Job")

    assert (shared.platform, shared.entry) == ("jobtrain", "leighacademiestrust")
    assert (custom.platform, custom.entry) == ("jobtrain", "jobs.crisis.org.uk")


def test_a_page_that_is_not_jobtrains_is_no_detection():
    assert jobtrain.detect_html("<html><body>Careers</body></html>", "https://acme.com/careers") is None


# --- the dispatcher: Jobtrain before the generic JSON-LD reader ---

def test_the_dispatcher_prefers_jobtrain_to_the_generic_career_site_reader():
    """career_sites takes any page with JobPosting markup for the employer's own site, which for these pages is the
    shared host (every other tenant's ads on it)."""
    det = ats_detect.from_html(_fx("lat_9610.html") + _fx("lat_home.html"), "https://www.jobtrain.co.uk/leighacademiestrust/Job/JobDetail?JobId=9610")

    assert (det.platform, det.entry) == ("jobtrain", "leighacademiestrust")
    assert ats_detect.from_url("https://www.jobtrain.co.uk/leighacademiestrust/Job/JobDetail?JobId=9610").platform == "jobtrain"
    assert ats_detect.from_cname("jobs.crisis.org.uk", "jobs-crisis.jobtrain.co.uk").entry == "jobs.crisis.org.uk"
    assert "jobtrain.co.uk" in ats_detect.platform_domains()


def test_the_shared_host_without_a_tenant_is_no_employers_site():
    assert jobtrain.is_shared_host("www.jobtrain.co.uk") and jobtrain.is_shared_host("jobtrain.co.uk")
    assert not jobtrain.is_shared_host("jobs.crisis.org.uk")
    assert ats_detect.is_shared_ats_host("https://www.jobtrain.co.uk/")
