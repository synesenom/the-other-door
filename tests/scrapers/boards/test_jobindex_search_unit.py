"""Unit tests for how the Jobindex scraper plans its searches (issue #255).

Pure and offline: keyword -> search phrase, the split planner, the profile area's
sub-areas, and a guard that every URL the planner emits is allowed by the saved
robots.txt.
"""

from pathlib import Path

import pytest

from door.scrapers import robots
from door.scrapers.boards import jobindex
from paths import TESTS_DIR

_FIX = Path(__file__).parent / "fixtures"
_RULES = robots.parse((TESTS_DIR / "scrapers" / "fixtures" / "robots" / "jobindex.txt").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# keyword -> search phrase
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("keyword, phrases", [
    # a data scientist's search_keywords
    ("data scientist", ["data scientist"]),
    ("data science lead", ["data science"]),
    ("head of data science", ["data science"]),
    ("ML lead", ["ml lead"]),
    ("machine learning manager", ["machine learning"]),
    ("data science manager", ["data science"]),
    ("principal data scientist", ["data scientist"]),
    ("applied scientist", ["applied scientist"]),
    # a data scientist's role_targets
    ("Lead Data Scientist", ["data scientist"]),
    ("Head of Data Science", ["data science"]),
    # other professions
    ("Senior Financial Controller", ["financial controller"]),
    ("Head of Finance", ["finance"]),
    ("Registered Nurse", ["registered nurse"]),
    # a field named with "and", "&" or a list (#434): the words are not next to each other in an
    # ad, so each side is its own search ("monitoring evaluation" is in no ad)
    ("monitoring and evaluation", ["monitoring", "evaluation"]),
    ("monitorering og evaluering", ["monitorering", "evaluering"]),
    ("Compensation & Benefits Partner", ["compensation", "benefits partner"]),
    ("Monitoring, Evaluation and Learning", ["monitoring", "evaluation", "learning"]),
    ("Head of Data Science and Analytics", ["data science", "analytics"]),
    ("health and safety advisor", ["health", "safety advisor"]),
    # edge cases
    ("Python", ["python"]),
    ("  data   scientist ", ["data scientist"]),
    ("Director of Machine Learning Engineering", ["learning engineering"]),
    ("senior lead", ["senior lead"]),  # two words: used as is
    ("M&E officer", ["m&e officer"]),
    ("Head of Lead Manager", []),  # nothing left once seniority and stop words go
    ("", []),
])
def test_keyword_phrases(keyword, phrases):
    assert jobindex._keyword_phrases(keyword) == phrases


def test_search_phrases_dedupe_and_skip():
    phrases, skipped = jobindex._search_phrases(
        ["data science lead", "head of data science", "Data Science Manager", "Head of Lead Manager"])
    assert phrases == ["data science"]
    assert skipped == ["Head of Lead Manager"]
    phrases, _ = jobindex._search_phrases(["monitoring and evaluation", "M&E", "evaluation specialist", "evaluation"])
    assert phrases == ["monitoring", "evaluation", "m&e", "evaluation specialist"]


# --------------------------------------------------------------------------- #
# URLs
# --------------------------------------------------------------------------- #

def test_search_url_quotes_a_two_word_phrase():
    assert jobindex._search_url("data scientist", "storkoebenhavn") == \
        "https://www.jobindex.dk/jobsoegning/storkoebenhavn?q=%22data+scientist%22"


def test_search_url_leaves_one_word_unquoted():
    assert jobindex._search_url("python", "") == "https://www.jobindex.dk/jobsoegning?q=python"


def test_search_url_with_a_category():
    assert jobindex._search_url("machine learning", "storkoebenhavn", category="it") == \
        "https://www.jobindex.dk/jobsoegning/it/storkoebenhavn?q=%22machine+learning%22"
    assert jobindex._search_url("machine learning", "", category="it") == \
        "https://www.jobindex.dk/jobsoegning/it?q=%22machine+learning%22"


# --------------------------------------------------------------------------- #
# split planner
# --------------------------------------------------------------------------- #

_ROOT = jobindex._Search("data scientist", "storkoebenhavn", "")
_CATS = ("it", "ledelse")
_SUBS = ["koebenhavn", "frederiksberg"]



def test_categories_favour_no_profession():
    """A full search is split into categories in alphabetical order, "oevrige" (other) last:
    the search budget runs out on the same categories whatever the profile's field."""
    named = [c for c in jobindex._CATEGORIES if c != "oevrige"]
    assert named == sorted(named) and jobindex._CATEGORIES[-1] == "oevrige"

def test_a_page_that_held_everything_is_not_split():
    assert jobindex._split(_ROOT, 20, 20, _CATS, lambda: _SUBS) == []
    assert jobindex._split(_ROOT, 0, 20, _CATS, lambda: _SUBS) == []


def test_a_full_search_is_split_by_category():
    assert jobindex._split(_ROOT, 29, 20, _CATS, lambda: _SUBS) == [
        jobindex._Search("data scientist", "storkoebenhavn", "it"),
        jobindex._Search("data scientist", "storkoebenhavn", "ledelse"),
    ]


def test_a_full_category_is_split_by_sub_area():
    cat = jobindex._Search("data scientist", "storkoebenhavn", "it")
    assert jobindex._split(cat, 34, 20, _CATS, lambda: _SUBS) == [
        jobindex._Search("data scientist", "koebenhavn", "it"),
        jobindex._Search("data scientist", "frederiksberg", "it"),
    ]


def test_the_narrowest_search_is_not_split_further():
    narrow = jobindex._Search("data scientist", "koebenhavn", "it")
    assert jobindex._split(narrow, 34, 20, _CATS, lambda: _SUBS) == []


def test_sub_areas_are_only_looked_up_when_needed():
    def boom():
        raise AssertionError("the area sitemap must not be fetched")
    jobindex._split(_ROOT, 29, 20, _CATS, boom)


def test_nationwide_has_categories_but_no_sub_areas():
    root = jobindex._Search("data scientist", "", "")
    first = jobindex._split(root, 99, 20, _CATS, lambda: [])[0]
    assert first == jobindex._Search("data scientist", "", "it")
    assert jobindex._split(first, 99, 20, _CATS, lambda: []) == []


# --------------------------------------------------------------------------- #
# sub-areas from the site's area sitemap
# --------------------------------------------------------------------------- #

def _sitemap_slugs() -> list[str]:
    return jobindex._area_slugs((_FIX / "jobindex" / "area.gz").read_bytes())


def test_area_slugs_reads_the_gzipped_sitemap():
    slugs = _sitemap_slugs()
    assert len(slugs) > 700
    assert {"storkoebenhavn", "koebenhavn", "frederiksberg", "vallensbaek"} <= set(slugs)


def test_area_slugs_reads_a_plain_sitemap_and_garbage():
    xml = b"<urlset><url><loc>https://www.jobindex.dk/jobsoegning/herlev</loc></url></urlset>"
    assert jobindex._area_slugs(xml) == ["herlev"]
    assert jobindex._area_slugs(b"not xml at all") == []


def test_slug_spells_danish_letters_out():
    assert jobindex._slug("København*") == "koebenhavn"
    assert jobindex._slug("Århus") == "aarhus"
    assert jobindex._slug("kongens lyngby") == "kongens-lyngby"


def test_sub_areas_of_storkoebenhavn_are_its_cities_and_postcodes():
    subs = jobindex._sub_areas("storkoebenhavn", _sitemap_slugs(), "Copenhagen")
    assert "koebenhavn" in subs and "frederiksberg" in subs and "2600-glostrup" in subs
    assert "storkoebenhavn" not in subs
    assert "aarhus" not in subs and "region-midtjylland" not in subs
    assert not any(s[:1].isdigit() and not 1000 <= int(s[:4]) < 3000 for s in subs)
    assert len(subs) == len(set(subs))


def test_other_areas_have_no_sub_areas():
    assert jobindex._sub_areas("region-midtjylland", _sitemap_slugs(), "Aarhus") == []
    assert jobindex._sub_areas("", _sitemap_slugs(), "Denmark") == []


# --------------------------------------------------------------------------- #
# robots.txt guard
# --------------------------------------------------------------------------- #

def _allowed(url: str) -> bool:
    return _RULES.allowed(robots.path_of(url))


def test_every_planned_url_is_allowed_by_robots_txt():
    phrases, _ = jobindex._search_phrases(
        ["Lead Data Scientist", "head of data science", "ML lead", "machine learning manager", "applied scientist",
         "monitoring and evaluation", "Compensation & Benefits Partner", "Monitoring, Evaluation and Learning"])
    subs = jobindex._sub_areas("storkoebenhavn", _sitemap_slugs(), "Copenhagen")
    urls = []
    for area, sub_areas in (("storkoebenhavn", subs), ("", [])):
        for phrase in phrases:
            urls.append(jobindex._search_url(phrase, area))
            for cat in jobindex._CATEGORIES:
                urls.append(jobindex._search_url(phrase, area, category=cat))
                urls.extend(jobindex._search_url(phrase, s, category=cat) for s in sub_areas)
    assert len(urls) > 100
    assert [u for u in urls if not _allowed(u)] == []
    assert not _allowed("https://www.jobindex.dk/jobsoegning/storkoebenhavn?q=head+of+data")  # the guard bites
    assert not _allowed("https://www.jobindex.dk/jobsoegning/it/storkoebenhavn/x?q=a")
    assert _allowed(jobindex._AREA_SITEMAP_URL)


def test_full_categories_take_turns_at_the_sub_area_searches(monkeypatch):
    """When several categories are full, their sub-area searches alternate, so the search
    budget is shared between them instead of going to the categories listed first."""
    monkeypatch.setattr(jobindex, "_CATEGORIES", ("handel", "it", "social"))
    searcher = jobindex._Searcher(None, "storkoebenhavn", "Copenhagen", max_pages=1)
    monkeypatch.setattr(searcher, "sub_areas", lambda: ["koebenhavn", "frederiksberg", "valby"])
    order: list[jobindex._Search] = []

    def fetch(search):
        order.append(search)
        hits = 500 if search.area == "storkoebenhavn" else 30
        return hits, 20, [{"tid": f"{search.area}-{search.category}-{i}"} for i in range(20)]

    monkeypatch.setattr(searcher, "fetch", fetch)
    searcher.collect("nurse")
    subs = [(s.category, s.area) for s in order if s.area != "storkoebenhavn"]
    assert subs[:3] == [("handel", "koebenhavn"), ("it", "koebenhavn"), ("social", "koebenhavn")]
    assert subs[3:6] == [("handel", "frederiksberg"), ("it", "frederiksberg"), ("social", "frederiksberg")]
