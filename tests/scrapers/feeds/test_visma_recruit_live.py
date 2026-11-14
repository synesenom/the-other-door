"""Live smoke tests for Visma Recruit (#526, #567), one per mode (#19): Nässjö kommun's customer list and two of its
ads, the employers' sites that link their lists (Nässjö, Skurup), and the look-through routes: an ad link names its
employer, and an employer's own list page (Uppvidinge kommun, Region Västerbotten) is read through Visma's ad JSON.

Opt-in — run with:  ./scripts/run-test.sh --live
"""

from datetime import datetime, timezone

import pytest

from door.scrapers.feeds import visma_recruit
from door.scrapers.http_client import PoliteSession
from live_employers import Careers
from live_utils import assert_contract, assert_detects, assert_listing, probe_sized

_NASSJO = "f636d73d-8356-43c6-99bd-ba01addf1b55"
_SKURUP = Careers("https://www.skurup.se/jobb-och-foretagande/jobb-och-praktik/lediga-jobb-i-kommunen", "Stockholm",
                  "visma_recruit", "e4de127c-0647-4402-83ee-c28fbb4803e8")
_UPPVIDINGE = "https://www.uppvidinge.se/naringsliv-och-arbete/arbetsmarknad/lediga-jobb-i-kommunen.html"
_VASTERBOTTEN = "https://www.regionvasterbotten.se/sok-jobb"
CONFIG = {"visma_recruit_companies": [_NASSJO], "location": "Stockholm"}
NO_PAGE2 = "a customer's list shows every open ad on one page (Nässjö's has no pager; page 2 is an empty table)"


def _session() -> PoliteSession:
    return PoliteSession(min_delay=0.5, max_delay=1.0, timeout=30, max_retries=0)


@pytest.mark.live
def test_visma_recruit_listing_live():
    """Nässjö's list: title and link (`locations=False`: the place is on the ad; `dates=False`: Nässjö's list has no
    published column, only the deadline)."""
    assert_listing("visma_recruit", visma_recruit, CONFIG, locations=False, dates=False)


@pytest.mark.live
def test_visma_recruit_details_live():
    """Two ads' pages (``AssignmentView.aspx``): text, place and date."""
    with probe_sized("visma_recruit", "details"):
        session = _session()
        name, rows = visma_recruit.parse_list(visma_recruit._page(session, _NASSJO, 1))
        assert rows, "visma_recruit [details]: no ads on Nässjö's list"
        now = datetime.now(timezone.utc)
        postings = []
        for row in rows[:2]:
            html = session.get(visma_recruit._VIEW_URL, headers={"Accept": "text/html"},
                               params={"GuidExtSoftware": _NASSJO, "guid": row["guid"].upper(), "locId": row["loc_id"]}).text
            ad = visma_recruit.parse_detail(html)
            assert ad is not None, f"visma_recruit [details]: ad {row['guid']} holds no ad"
            postings.append(visma_recruit._to_posting(row, ad, name, now))
    assert_contract("visma_recruit", postings, "details", config=CONFIG, dates=True)


@pytest.mark.live
def test_visma_recruit_detection_live():
    """The employers' own sites still link their Visma Recruit lists: Nässjö (`live_employers.DETECTION`) and Skurup."""
    assert_detects("visma_recruit")
    assert_detects("visma_recruit", _SKURUP)


@pytest.mark.live
def test_visma_recruit_lookthrough_live():
    """What `follow` reads past an ad link and an employer's own list page:

    - a current ad's public JSON (``GetApplySettings``) still names its employer, and the look-through finds the list
      the employer's website links (an ad of Nässjö's list, so the link is current);
    - Uppvidinge kommun's own page still links its ads by Visma id (``offentligajobb.se`` links), and one of them reads
      through the ad JSON;
    - Region Västerbotten's list page still links its ads by Visma id (``?itemid=``).
    """
    session = _session()
    _, rows = visma_recruit.parse_list(visma_recruit._page(session, _NASSJO, 1))
    assert rows, "visma_recruit [lookthrough]: no ads on Nässjö's list to follow back"
    apply = f"{visma_recruit._APPLY_URL}?guidAssignment={rows[0]['guid']}"
    det = visma_recruit.resolve(session, visma_recruit.detect_url(apply), apply)
    assert det.platform == "visma_recruit" and det.employer, \
        f"visma_recruit [lookthrough]: GetApplySettings no longer names the employer of {apply}"
    assert det.entry == _NASSJO, f"visma_recruit [lookthrough]: {det.employer}'s list not found from its ad: {det.evidence}"

    guids = visma_recruit.parse_page(session.get(_UPPVIDINGE, headers={"Accept": "text/html"}).text, _UPPVIDINGE)["guids"]
    assert guids, f"visma_recruit [lookthrough]: {_UPPVIDINGE} no longer links its ads by Visma id"
    ads = [visma_recruit.parse_settings(visma_recruit._settings(session, g)) for g in guids[:2]]   # (one may have closed)
    assert any(ad and ad["title"] and ad["description"] and ad["organization"] for ad in ads), \
        f"visma_recruit [lookthrough]: the ad JSON of {guids[:2]} no longer reads: {ads}"

    result = visma_recruit.probe({"visma_recruit_companies": [_VASTERBOTTEN]})
    assert result["structure_ok"] is True and result["postings"], \
        f"visma_recruit [lookthrough]: {_VASTERBOTTEN} no longer links its ads by Visma id: {result.get('reason')}"
