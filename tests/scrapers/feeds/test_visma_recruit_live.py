"""Live smoke test for Visma Recruit's customer job lists (#526, #567).

Opt-in — run with:  ./scripts/run-test.sh --live

A municipality that publishes its Visma Recruit list on its own site (Nässjö kommun, Skurups kommun) is followed
through that list; an ad link alone still names only the employer.
"""

import pytest

from door.core.models import JobPosting
from door.scrapers.feeds import visma_recruit
from door.scrapers.http_client import PoliteSession
from live_utils import assert_detects

_APPLY = "https://recruit.visma.com/spa/public/apply?guidAssignment=2b368797-8e2c-4527-bc80-7cc9ac2d9c39"
_NASSJO = "f636d73d-8356-43c6-99bd-ba01addf1b55"
_SKURUP = "e4de127c-0647-4402-83ee-c28fbb4803e8"


@pytest.mark.live
def test_visma_recruit_live_a_customers_list_returns_valid_postings():
    postings = visma_recruit.scrape({"visma_recruit_companies": [_NASSJO]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]


@pytest.mark.live
def test_visma_recruit_live_the_employers_site_still_links_its_list():
    session = PoliteSession(min_delay=1, max_delay=2, timeout=30, max_retries=1)
    for site, guid in (("https://www.nassjo.se/", _NASSJO),
                       ("https://www.skurup.se/jobb-och-foretagande/jobb-och-praktik/lediga-jobb-i-kommunen", _SKURUP)):
        det = visma_recruit.detect_html(session.get(site).text, site)
        assert det is not None and det.entry == guid, f"{site} no longer links its Visma Recruit list"


@pytest.mark.live
def test_visma_recruit_live_an_ad_link_is_looked_through_for_the_employer():
    """The ad's public JSON still names the employer, so `follow` has a name to try (the look-through, #526)."""
    session = PoliteSession(min_delay=1, max_delay=2, timeout=30, max_retries=1)
    det = visma_recruit.resolve(session, visma_recruit.detect_url(_APPLY), _APPLY)
    assert det.platform == "visma_recruit" and det.employer, "GetApplySettings no longer names the employer"


@pytest.mark.live
def test_visma_recruit_live_an_employers_own_ad_list_is_read_through_the_ad_json():
    """Uppvidinge kommun lists its ads with offentligajobb.se links on its own page (the second route, #567)."""
    page = "https://www.uppvidinge.se/naringsliv-och-arbete/arbetsmarknad/lediga-jobb-i-kommunen.html"
    postings = visma_recruit.scrape({"visma_recruit_companies": [page]})
    assert postings
    for p in postings:
        JobPosting.model_validate(p)
        assert p["title"] and p["company"] and p["url"] and p["description"]


@pytest.mark.live
def test_visma_recruit_live_region_vasterbottens_list_page_still_links_its_ads_by_visma_id():
    result = visma_recruit.probe({"visma_recruit_companies": ["https://www.regionvasterbotten.se/sok-jobb"]})
    assert result["structure_ok"] is True and result["postings"], result.get("reason")


@pytest.mark.live
def test_visma_recruit_detection_live():
    """A real employer's careers page still shows visma_recruit and its feed (`live_employers.DETECTION`, #19)."""
    assert_detects("visma_recruit")
