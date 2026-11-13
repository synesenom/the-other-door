"""Every live test that scrapes postings checks the field contract (#19): `live_utils.assert_field_contract`.

A source scan: a `test_*_live.py` of a board or a feed that calls `scrape(` or `probe(` must also call
`assert_field_contract`, unless it is listed in `DETECTION_ONLY` (it reads no postings, or probes a structure).
"""

import re

from door.core import sites
from live_matrix import FIELD_EXCEPTIONS
from paths import TESTS_DIR

_SCRAPERS = TESTS_DIR / "scrapers"
_READS_POSTINGS = re.compile(r"\.(?:scrape|probe)\(")

# Live tests with no postings to check, and why.
DETECTION_ONLY = {
    "test_jobaffinity_live.py": "detects an employer behind an apply form",
    "test_ponty_live.py": "detects an employer behind an apply form",
    "test_phenom_live.py": "looks through a front end to a Workday site",
}


def _live_tests():
    return sorted(p for folder in ("boards", "feeds") for p in (_SCRAPERS / folder).glob("test_*_live.py"))


def test_every_live_test_that_reads_postings_checks_the_field_contract():
    missing = [p.name for p in _live_tests()
               if _READS_POSTINGS.search(p.read_text(encoding="utf-8"))
               and "assert_field_contract(" not in p.read_text(encoding="utf-8")
               and p.name not in DETECTION_ONLY]
    assert missing == []


def test_the_detection_only_list_names_files_that_exist_and_read_no_postings():
    names = {p.name for p in _live_tests()}
    assert set(DETECTION_ONLY) <= names
    for name in DETECTION_ONLY:
        assert "assert_field_contract(" not in (next(p for p in _live_tests() if p.name == name)).read_text(encoding="utf-8")


def test_every_field_exception_names_a_known_site():
    assert set(FIELD_EXCEPTIONS) <= set(sites.SITES)
