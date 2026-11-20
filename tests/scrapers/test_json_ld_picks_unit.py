"""Which JobPosting each module picks from a page's JSON-LD (its own rule over the shared reader)."""
import json

from door.scrapers.boards import jobbank, jobindex, jobs_ac_uk, reed
from door.scrapers.feeds import recman


def _page(*nodes) -> str:
    return "".join(f'<script type="application/ld+json">{json.dumps(n)}</script>' for n in nodes)


def _ad(title: str, description: str) -> dict:
    return {"@type": "JobPosting", "title": title, "description": description}


def test_reed_reads_the_first_ad_with_a_description_and_none_when_its_text_is_empty():
    assert reed._parse_description(_page(_ad("A", ""), _ad("B", "<p>Second</p>"))) == "Second"
    assert reed._parse_description(_page(_ad("A", "<p></p>"), _ad("B", "<p>Second</p>"))) is None


def test_jobs_ac_uk_reads_on_past_an_ad_with_empty_text():
    page = _page(_ad("A", "<p></p>"), _ad("B", "<p>Second</p>"))
    assert jobs_ac_uk._parse_detail(page)["description"] == "Second"


def test_recman_picks_the_first_ad_with_a_title():
    page = _page(_ad("", "Untitled"), _ad("Titled", "Body"))
    assert recman._parse_detail(page)["title"] == "Titled"


def test_jobindex_picks_the_first_non_empty_description():
    page = _page(_ad("A", "  "), _ad("B", "<p>Second</p>"))
    assert jobindex._description_from_html(page) == "Second"


def test_jobbank_picks_the_first_ad():
    page = _page(_ad("First", "One"), _ad("Second", "Two"))
    assert jobbank._parse_detail(page)["title"] == "First"
