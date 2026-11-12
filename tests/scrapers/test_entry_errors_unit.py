"""A feed entry that fails is recorded under its name, beside the site's error (issue #437)."""

from door.scrapers import drain_entry_errors, drain_errors, record_entry_error, scrape_feeds


def test_an_entry_error_is_an_error_of_the_site_and_of_the_entry():
    drain_errors(), drain_entry_errors("lever")
    record_entry_error("lever", "acme", "error fetching 'acme': 404")
    record_entry_error("lever", "globex", "globex: bot protection; not attempted", blocked=True)

    assert drain_entry_errors("lever") == {
        "acme": {"outcome": "failed", "reason": "error fetching 'acme': 404"},
        "globex": {"outcome": "blocked", "reason": "globex: bot protection; not attempted"},
    }
    assert drain_entry_errors("lever") == {}  # drained
    assert len(drain_errors()["lever"]) == 2


def test_scrape_feeds_names_the_entry_that_raised():
    drain_errors(), drain_entry_errors("lever")

    def fetch(session, entry, scraped_at):
        if entry == "bad":
            raise RuntimeError("boom")
        return [{"platform_id": entry}]

    assert [p["platform_id"] for p in scrape_feeds("lever", ["bad", "good"], fetch)] == ["good"]
    assert list(drain_entry_errors("lever")) == ["bad"]
