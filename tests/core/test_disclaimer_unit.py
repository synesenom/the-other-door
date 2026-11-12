"""The one disclaimer shown whenever an unsure source is turned on (#569)."""

from door.core import disclaimer


def test_the_text_names_the_site_what_its_terms_say_and_links_them():
    text = disclaimer.text("Example Jobs", "its terms ban scraping", "https://example.com/terms")
    assert "Example Jobs" in text
    assert "its terms ban scraping" in text
    assert "https://example.com/terms" in text
    assert "LEGAL_DISCLAIMER.md" in text


def test_the_text_makes_it_the_users_decision_at_their_own_risk_and_holds_no_markup():
    text = disclaimer.text("Example Jobs", "no terms found", "https://example.com/terms")
    assert "your own risk" in text and "your decision" in text
    assert "<" not in text and "**" not in text


def test_the_text_is_the_same_for_the_same_input():
    args = ("A", "b", "https://c.example")
    assert disclaimer.text(*args) == disclaimer.text(*args)
