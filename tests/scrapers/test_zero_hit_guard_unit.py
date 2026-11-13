"""Every board reads a zero-hit answer as a quiet day (#19): each has a saved real one and a scrape test on it.

The scrape tests run the whole path on the fixture (`drain_answered(site)` True, no errors, no postings); this
guard keeps a new board from skipping that: it must be in `ZERO_HIT_FIXTURES` (or `NO_ZERO_HIT` with a reason),
the fixture must exist, and the board's scrape test must read it and check `drain_answered`.
"""

from door.core import sites
from live_matrix import NO_ZERO_HIT, ZERO_HIT_FIXTURES
from paths import TESTS_DIR

_SCRAPERS = TESTS_DIR / "scrapers"


def _boards() -> set[str]:
    return {name for name, site in sites.SITES.items() if site.board}


def test_every_board_has_a_zero_hit_fixture_or_a_reason():
    assert _boards() - set(ZERO_HIT_FIXTURES) - set(NO_ZERO_HIT) == set()
    assert set(ZERO_HIT_FIXTURES) | set(NO_ZERO_HIT) <= _boards()
    assert not set(ZERO_HIT_FIXTURES) & set(NO_ZERO_HIT)


def test_every_zero_hit_fixture_exists_and_is_not_empty():
    for site, path in ZERO_HIT_FIXTURES.items():
        assert (_SCRAPERS / path).stat().st_size > 0, f"{site}: {path}"


def test_every_board_scrape_test_reads_its_zero_hit_fixture_and_checks_the_answer():
    for site, path in ZERO_HIT_FIXTURES.items():
        tests = list(_SCRAPERS.rglob(f"test_{site}_scrape.py"))
        assert len(tests) == 1, site
        text = tests[0].read_text(encoding="utf-8")
        assert path.rsplit("/", 1)[1] in text, f"{site}: its scrape test never serves {path}"
        assert "drain_answered" in text, f"{site}: its scrape test never checks drain_answered"
