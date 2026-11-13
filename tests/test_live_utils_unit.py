"""The live tests' verdicts (#19): a site that refused the request was not reached; anything else is a change."""

from datetime import datetime, timedelta, timezone

import pytest

import live_matrix
from live_utils import NOT_REACHED, assert_field_contract, not_reached, not_reached_if_refused, refused


@pytest.mark.parametrize("message", [
    "search error (keyword='x', page=1): 429 Client Error: Too Many Requests for url: https://x",
    "detail error (https://x): 403 Client Error: Forbidden for url: https://x",
    "401 Client Error: Unauthorized for url: https://x",
    "HTTPSConnectionPool(host='x', port=443): Read timed out. (read timeout=30)",
    "HTTPSConnectionPool(host='x', port=443): Max retries exceeded with url: / (Caused by NameResolutionError)",
    "('Connection aborted.', ConnectionResetError(54, 'Connection reset by peer'))",
    "reed: pushback (HTTP 429); stopped for this run",
    "503 Server Error: Service Unavailable for url: https://x",
])
def test_a_refusal_or_an_unreachable_host_is_not_reached(message):
    assert refused([message])


@pytest.mark.parametrize("errors", [
    [],
    ["no search results block on page (keyword='x', page=1)"],
    ["429 Client Error: Too Many Requests", "no search results block on page"],   # a parse failure too: changed
    ["KeyError: 'jobs'"],
])
def test_no_errors_or_a_parse_failure_is_not_a_refusal(errors):
    assert not refused(errors)


def test_a_refused_site_is_skipped_as_not_reached_everywhere(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    with pytest.raises(pytest.skip.Exception) as skipped:
        not_reached_if_refused("reed", ["403 Client Error: Forbidden for url: https://x"])
    assert str(skipped.value).startswith(f"{NOT_REACHED} reed: ")


def test_a_known_refusal_is_not_reached_whatever_its_wording():
    with pytest.raises(pytest.skip.Exception) as skipped:
        not_reached("wikidata", "Wikidata did not answer")
    assert str(skipped.value) == f"{NOT_REACHED} wikidata: Wikidata did not answer"


def test_a_site_that_answered_badly_is_left_to_fail():
    assert not_reached_if_refused("reed", ["no search results block on page"]) is None
    assert not_reached_if_refused("reed", []) is None


# --- the field contract (#19) ---

def _ad(i: int = 0, **over) -> dict:
    ad = {
        "id": f"jobindex.{i}", "title": f"Data engineer {i}", "company": f"Firma {i}", "location": "Copenhagen",
        "url": f"https://example.org/job/{i}", "source": "jobindex", "scraped_at": datetime.now(timezone.utc),
        "posted_at": datetime.now(timezone.utc) - timedelta(days=2),
        "description": f"Position {i}: we build pipelines for the {i}th team and need someone who writes SQL, "
                       f"reads code and talks to people about what they need next quarter. " * 2,
    }
    ad.update(over)
    return ad


def _ads(n: int = 10, **over) -> list[dict]:
    return [_ad(i, **over) for i in range(n)]


def _fails(postings, rule, site="jobindex", **kw):
    with pytest.raises(AssertionError) as err:
        assert_field_contract(site, postings, **kw)
    message = str(err.value)
    assert message.startswith(f"{site} ({kw.get('mode', 'search')}): rule '{rule}' held for"), message
    return message


CPH = {"location": "Copenhagen"}


def test_clean_postings_meet_the_contract():
    assert_field_contract("jobindex", _ads(), CPH)


def test_no_postings_fail():
    with pytest.raises(AssertionError, match=r"jobindex \(search\): rule 'no postings'"):
        assert_field_contract("jobindex", [])


@pytest.mark.parametrize("rule, field, bad", [
    ("title", "title", " "), ("url", "url", ""), ("url", "url", "ftp://x"),
])
def test_title_and_url_must_all_be_there(rule, field, bad):
    ads = _ads()
    ads[3][field] = bad
    assert f"{field}=" in _fails(ads, rule)


def test_a_bad_field_under_the_threshold_passes_and_over_it_fails():
    ads = _ads()
    ads[0]["company"] = ""
    assert_field_contract("thehub", ads, CPH)                      # 9/10 = 90%
    ads[1]["company"] = ""
    message = _fails(ads, "company", site="thehub", config=CPH)    # 8/10
    assert "8/10" in message and "needs 90%" in message


def test_a_site_exception_loosens_a_rule(monkeypatch):
    ads = _ads()
    for ad in ads[:2]:
        ad["company"] = ""
    _fails(ads, "company", config=CPH)
    monkeypatch.setitem(live_matrix.FIELD_EXCEPTIONS, "jobindex", {"company_share": 0.8})
    assert_field_contract("jobindex", ads, CPH)


def test_the_message_has_up_to_three_examples():
    ads = _ads()
    for ad in ads[:5]:
        ad["company"] = ""
    message = _fails(ads, "company", config=CPH)
    assert message.count("(company=") == 3


def test_fewer_than_three_postings_must_all_pass():
    ads = _ads(2)
    ads[0]["company"] = ""
    _fails(ads, "company", config=CPH)
    assert_field_contract("jobindex", _ads(2), CPH)


def test_a_board_whose_company_is_its_own_name_fails_a_feed_may_carry_it():
    ads = _ads(company="Jobindex")
    _fails(ads, "company", config=CPH)
    assert_field_contract("greenhouse", [dict(a, id=f"greenhouse.{i}", source="greenhouse", company="Greenhouse")
                                         for i, a in enumerate(ads)], mode="collect")


def test_the_label_of_the_site_counts_as_its_own_name():
    _fails(_ads(company="NHS Jobs"), "company", site="nhs_jobs", config={"location": "London"})


def test_a_foreign_location_fails_a_country_board_and_remote_or_empty_is_fine():
    config = {"location": "Copenhagen"}
    assert_field_contract("jobindex", _ads(location="Remote"), config)
    assert_field_contract("jobindex", _ads(location=""), config)
    assert "location=" in _fails(_ads(location="Paris, France"), "location", config=config)


def test_no_location_rule_without_a_profile_location_in_collect_mode_or_by_exception():
    foreign = _ads(location="Paris, France")
    assert_field_contract("jobindex", foreign)
    assert_field_contract("jobindex", foreign, CPH, mode="collect")
    assert_field_contract("euraxess", [dict(a, source="euraxess") for a in foreign], {"location": "Copenhagen, Denmark"})


def test_a_site_without_countries_has_no_location_rule():
    assert_field_contract("reliefweb", _ads(location="Paris, France"), CPH)


@pytest.mark.parametrize("posted", [
    datetime.now(timezone.utc) + timedelta(days=5),
    datetime.now(timezone.utc) - timedelta(days=400),
    datetime.now() + timedelta(days=5),
])
def test_an_implausible_date_fails_naive_or_aware(posted):
    assert "posted_at=" in _fails(_ads(posted_at=posted), "posted_at", config=CPH)


def test_naive_and_aware_dates_both_work_and_a_missing_one_is_fine():
    assert_field_contract("jobindex", _ads(posted_at=datetime.now() - timedelta(days=3)), CPH)
    assert_field_contract("jobindex", _ads(posted_at=None), CPH)
    assert_field_contract("jobindex", _ads(posted_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat()), CPH)


def test_a_feed_keeps_a_long_open_job_a_board_does_not():
    old = datetime.now(timezone.utc) - timedelta(days=400)
    _fails(_ads(posted_at=old), "posted_at", config=CPH)
    assert_field_contract("greenhouse", _ads(posted_at=old), mode="collect")
    assert_field_contract("jobindex", _ads(posted_at=datetime.now(timezone.utc) - timedelta(days=120)), CPH)


def test_a_planned_date_is_fine_where_the_site_says_so():
    ahead = datetime.now(timezone.utc) + timedelta(days=10)
    _fails(_ads(posted_at=ahead), "posted_at", site="reed", config={"location": "London"})
    assert_field_contract("kozigallas", [dict(a, source="kozigallas") for a in _ads(posted_at=ahead)], {"location": "Budapest"})


def test_a_short_or_missing_description_fails_unless_the_site_is_excused(monkeypatch):
    assert "description=" in _fails(_ads(description="Apply now."), "description", config=CPH)
    assert "description=" in _fails(_ads(description=""), "description", config=CPH)
    monkeypatch.setitem(live_matrix.FIELD_EXCEPTIONS, "greenhouse", {"description_share": 0})
    assert_field_contract("greenhouse", _ads(description=""), mode="collect")
    monkeypatch.setitem(live_matrix.FIELD_EXCEPTIONS, "jobindex", {"description_min": 40})
    short = [_ad(i, description=f"Short ad number {i} about data work for us") for i in range(10)]
    assert_field_contract("jobindex", short, CPH)


@pytest.mark.parametrize("text", [
    "Please enable JavaScript and accept all cookies to continue. " * 3,
    "Access denied. " * 15,
])
def test_a_wall_page_is_not_a_description(text):
    assert "description=" in _fails(_ads(description=text), "boilerplate", config=CPH)


def test_a_description_that_copies_the_title_or_company_fails():
    long_title = [dict(a, title="Senior data engineer for the platform team " * 3, company="Firma") for a in _ads()]
    for ad in long_title:
        ad["description"] = ad["title"]
    _fails(long_title, "boilerplate", config=CPH)
    built = [dict(a, title="Senior data engineer for the platform team " * 2, company=f"Firma {i}") for i, a in enumerate(_ads())]
    for ad in built:
        ad["description"] = f"{ad['title']} / {ad['company']}"
    _fails(built, "boilerplate", config=CPH)


def test_the_same_whole_text_under_many_titles_fails():
    common = "Our company is a leading provider of solutions for the modern workplace and we are growing fast. " * 3
    assert "description=" in _fails([_ad(i, description=common) for i in range(10)], "boilerplate", config=CPH)
    assert_field_contract("jobindex", [_ad(0, description=common), _ad(1, description=common)] + _ads(8)[2:], CPH)  # two alike is not


def test_a_shared_about_us_or_one_job_in_several_places_is_not_boilerplate():
    common = "Our company is a leading provider of solutions for the modern workplace and we are growing fast. " * 3
    assert_field_contract("greenhouse", [_ad(i, description=common + f"Role {i}: what you will do.") for i in range(10)], mode="collect")
    same_job = [dict(_ad(i, description=common), title="Account Director") for i in range(10)]
    assert_field_contract("pinpoint", same_job, mode="collect")


def test_an_invalid_posting_fails_the_model():
    ads = _ads()
    del ads[2]["scraped_at"]
    with pytest.raises(Exception):
        assert_field_contract("jobindex", ads, CPH)


def test_only_the_sample_is_read():
    ads = _ads(12)
    ads[11]["title"] = ""
    assert_field_contract("jobindex", ads, CPH, sample=10)


def test_exceptions_name_known_sites():
    from door.core import sites

    assert set(live_matrix.FIELD_EXCEPTIONS) <= set(sites.SITES)


# --- discovery sources (#19): a refusal is not reached, an answer must yield employers --------------------------

from live_utils import assert_discovery  # noqa: E402


def _result(**kw):
    base = {"employers": [{"company": "Acme A/S", "titles": ["Data Scientist"], "links": ["https://acme.example/jobs/1"]}],
            "requests": 1, "pushback": False, "stopped": None, "outcome": "ok"}
    return base | kw


def test_a_discovery_refusal_is_not_reached():
    with pytest.raises(pytest.skip.Exception) as skipped:
        assert_discovery("hellowork", _result(employers=[], pushback=True, outcome="refused",
                                              stopped="a consent page instead of the results"), [])
    assert str(skipped.value).startswith(f"{NOT_REACHED} hellowork: a consent page")


def test_a_discovery_answer_with_employers_passes():
    assert_discovery("hellowork", _result(), [], link_prefix="https://acme.example/")


@pytest.mark.parametrize("result, message", [
    (_result(employers=[]), "no employers"),
    (_result(outcome="error", stopped="HTTP 500"), "HTTP 500"),
    (_result(employers=[{"company": "", "titles": ["x"], "links": []}]), "name"),
    (_result(employers=[{"company": "Acme", "titles": [], "links": []}]), "title"),
    (_result(employers=[{"company": "Acme", "titles": ["x"], "links": ["javascript:void(0)"]}]), "link"),
])
def test_a_discovery_answer_that_no_longer_parses_is_a_change_naming_the_source_and_mode(result, message):
    with pytest.raises(AssertionError) as failed:
        assert_discovery("jobbsafari", result, [], link_prefix="http")
    assert str(failed.value).startswith("jobbsafari [employers]:") and message in str(failed.value)


# --- feed detection (#19): a careers page still shows its platform ------------------------------------------------

import live_utils  # noqa: E402
from live_employers import Careers  # noqa: E402
from live_utils import assert_detects  # noqa: E402

_ROW = Careers("https://acme.example/careers", "Copenhagen", "teamtailor", "acme")


def _resolved(monkeypatch, **found):
    from door.commands import companies

    result = {"input": _ROW.page, "platform": None, "entry": None, "evidence": "", "notes": []} | found
    monkeypatch.setattr(companies, "_resolve_core", lambda inputs, location="": {"results": [result]})


def test_a_page_that_still_shows_its_platform_passes(monkeypatch):
    _resolved(monkeypatch, platform="teamtailor", entry="acme", evidence="links to it")
    assert_detects("teamtailor", _ROW)


@pytest.mark.parametrize("found, message", [
    ({}, "found no feed"),
    ({"platform": "lever", "entry": "acme"}, "lever"),
    ({"platform": "teamtailor", "entry": "other"}, "other"),
])
def test_a_page_that_no_longer_shows_its_platform_is_a_change_naming_it_and_the_mode(monkeypatch, found, message):
    _resolved(monkeypatch, **found)
    monkeypatch.setattr(live_utils, "_page_refusal", lambda url: None)
    with pytest.raises(AssertionError) as failed:
        assert_detects("teamtailor", _ROW)
    assert str(failed.value).startswith("teamtailor [detection]:") and message in str(failed.value)


def test_a_page_that_refused_is_not_reached(monkeypatch):
    _resolved(monkeypatch)
    monkeypatch.setattr(live_utils, "_page_refusal", lambda url: "403 Client Error: Forbidden")
    with pytest.raises(pytest.skip.Exception) as skipped:
        assert_detects("teamtailor", _ROW)
    assert str(skipped.value).startswith(f"{NOT_REACHED} teamtailor: 403")


def test_a_host_the_other_door_must_not_read_is_never_fetched_to_tell_a_refusal(monkeypatch):
    """iCIMS's and Welcome to the Jungle's terms bar automated reading: their detection is the URL's alone."""
    _resolved(monkeypatch)
    monkeypatch.setattr(live_utils, "_page_refusal", lambda url: pytest.fail(f"fetched {url}"))
    with pytest.raises(AssertionError) as failed:
        assert_detects("icims", Careers("https://careers-sisk.icims.com/jobs/search?ss=1", "London", "icims", None))
    assert str(failed.value).startswith("icims [detection]:")
