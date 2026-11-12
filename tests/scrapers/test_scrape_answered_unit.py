"""`record_answered` / `drain_answered`: a scraper's signal that it read a recognised results page with no hits."""

from door.scrapers import drain_answered, record_answered


def test_answered_drains_once_per_site():
    drain_answered("x")
    drain_answered("y")
    record_answered("x")
    assert drain_answered("y") is False
    assert drain_answered("x") is True
    assert drain_answered("x") is False
