"""robots.txt matching (RFC 9309), the rules every door request obeys (issue #226).

Pure: rules are parsed from text, including saved copies of real files under
fixtures/robots/. Python's `urllib.robotparser` is not used because it ignores
`*`/`$` wildcards and lets the first matching rule win, where RFC 9309 (and
every major crawler) lets the longest match win.
"""

from paths import TESTS_DIR

from door.scrapers import robots

_FIX = TESTS_DIR / "scrapers" / "fixtures" / "robots"


def _rules(name: str) -> robots.Rules:
    return robots.parse((_FIX / name).read_text(encoding="utf-8"))


def test_an_empty_file_allows_everything():
    assert robots.parse("").allowed("/anything?x=1")


def test_disallow_is_a_path_prefix():
    rules = robots.parse("User-agent: *\nDisallow: /private\n")
    assert not rules.allowed("/private")
    assert not rules.allowed("/private/page")
    assert rules.allowed("/public")


def test_an_empty_disallow_allows_everything():
    assert robots.parse("User-agent: *\nDisallow:\n").allowed("/x")


def test_the_longest_match_wins_and_allow_wins_a_tie():
    rules = robots.parse("User-agent: *\nAllow: /ApplicationInit.aspx?\nDisallow: /\n")
    assert rules.allowed("/ApplicationInit.aspx?cid=1&ProjectId=2")
    assert not rules.allowed("/other")
    tie = robots.parse("User-agent: *\nDisallow: /a\nAllow: /a\n")
    assert tie.allowed("/a")


def test_star_matches_any_run_of_characters():
    rules = robots.parse("User-agent: *\nDisallow: /jobsoegning*page=\n")
    assert not rules.allowed("/jobsoegning?q=data&page=2")
    assert rules.allowed("/jobsoegning?q=data")


def test_dollar_anchors_the_end():
    rules = robots.parse("User-agent: *\nDisallow: /*.pdf$\n")
    assert not rules.allowed("/cv.pdf")
    assert rules.allowed("/cv.pdf?download=1")


def test_doors_own_group_beats_the_star_group():
    text = "User-agent: *\nDisallow: /\n\nUser-agent: Door\nAllow: /\n"
    assert robots.parse(text).allowed("/x")


def test_groups_for_other_bots_are_ignored():
    text = "User-agent: LinkedInBot\nAllow: /show-job\n\nUser-agent: *\nDisallow: /\n"
    assert not robots.parse(text).allowed("/show-job/1")


def test_consecutive_user_agent_lines_share_a_group():
    text = "User-agent: foo\nUser-agent: *\nDisallow: /x\n"
    assert not robots.parse(text).allowed("/x")


def test_comments_and_unknown_lines_are_ignored():
    text = "# hi\nUser-agent: * # all\nContent-Signal: ai-train=no\nDisallow: /x # no\n"
    assert not robots.parse(text).allowed("/x/y")


def test_crawl_delay_is_read_from_the_matching_group():
    assert robots.parse("User-agent: *\nAllow: /\nCrawl-delay: 1\n").crawl_delay == 1.0
    assert robots.parse("User-agent: *\nAllow: /\n").crawl_delay is None
    assert robots.parse("User-agent: *\nCrawl-delay: soon\n").crawl_delay is None


def test_disallow_all_and_allow_all():
    assert not robots.Rules.disallow_all().allowed("/")
    assert robots.Rules.allow_all().allowed("/")


def test_percent_encoding_is_compared_normalised():
    rules = robots.parse("User-agent: *\nDisallow: /a%3cb\n")
    assert not rules.allowed("/a%3Cb")


def test_a_byte_order_mark_is_ignored():
    assert not robots.parse("﻿User-agent: *\nDisallow: /\n").allowed("/x")


def test_path_of_a_url_keeps_the_query():
    assert robots.path_of("https://x.dk/jobsoegning?q=a+b") == "/jobsoegning?q=a+b"
    assert robots.path_of("https://x.dk") == "/"


# --------------------------------------------------------------------------- #
# The real files the scrapers meet
# --------------------------------------------------------------------------- #

def test_jobindex_allows_a_one_parameter_search_and_the_ad_pages():
    rules = _rules("jobindex.txt")
    assert rules.allowed("/jobsoegning?q=data+scientist")
    assert rules.allowed("/jobannonce/h1673146/")


def test_jobindex_disallows_paging_age_and_area_filters():
    rules = _rules("jobindex.txt")
    assert not rules.allowed("/jobsoegning?q=data&page=2")
    assert not rules.allowed("/jobsoegning?q=data&jobage=7")
    assert not rules.allowed("/jobsoegning?q=data&geoareaid=4")
    assert not rules.allowed("/jobsoegning?q=head+of+data")  # two '+'


def test_hr_manager_allows_only_the_application_page():
    rules = _rules("hr_manager.txt")
    assert rules.allowed("/ApplicationInit.aspx?cid=1&ProjectId=2")
    assert not rules.allowed("/ApplicationInit.aspx?cid=1&SkipAdvertisement=True")
    assert not rules.allowed("/Default.aspx")


def test_workable_allows_its_job_api():
    rules = _rules("workable.txt")
    assert rules.allowed("/api/v1/jobs?query=data&location=Copenhagen")
    assert not rules.allowed("/search?query=data")


def test_sitemap_lines_are_collected_whatever_group_they_sit_in():
    """`Sitemap:` belongs to no group (RFC 9309 §2.2.4); career_sites starts from them."""
    rules = robots.parse("Sitemap: https://x.dk/a.xml\nUser-agent: *\nDisallow: /data/\nsitemap: https://x.dk/jobs.xml\n")
    assert rules.sitemaps == ("https://x.dk/a.xml", "https://x.dk/jobs.xml")
    assert robots.parse("").sitemaps == ()
