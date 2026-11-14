"""`wall_page`: a page sent instead of the listing (a captcha, a bot challenge, a login or a consent page) is a
refusal, never "no results" (#19). Read only on a page that listed nothing, so a page with a consent script and
results is never asked; still, no real zero-hit answer may look like a wall."""

import pytest

from door.scrapers import wall_page
from door.scrapers import sdk
from live_matrix import ZERO_HIT_FIXTURES
from paths import TESTS_DIR


@pytest.mark.parametrize("html", [
    "<html><head><title>Just a moment...</title></head><body><div id='cf-chl-widget'></div></body></html>",
    "<html><title>Attention Required! | Cloudflare</title><body>Sorry, you have been blocked</body></html>",
    "<html><body><div class='g-recaptcha' data-sitekey='x'></div></body></html>",
    "<html><body><div class='h-captcha'></div></body></html>",
    "<html><body><script src='https://ct.captcha-delivery.com/c.js'></script></body></html>",
    "<html><head><title>Access Denied</title></head><body>Reference #18.abc</body></html>",
    "<html><body><form action='/login'><input type='password' name='session_password'></form></body></html>",
    "<html><head><title>Before you continue</title></head><body><form action='https://consent.example.com/save'>"
    "</form></body></html>",
    "<html><head><title>Cookie consent</title></head><body>Accept all</body></html>",
    "<html><head><title> The URL you requested has been blocked </title></head><body>ID: 123</body></html>",
    "<html><head><title>Request Rejected</title></head><body>Your support ID is: 1</body></html>",
])
def test_a_challenge_captcha_login_or_consent_page_is_a_wall(html):
    assert wall_page(html)


@pytest.mark.parametrize("html", [
    "",
    "<html><head><title>Jobs - no results</title></head><body><p>0 jobs found</p></body></html>",
    # a consent manager's script on an ordinary page is not a wall
    "<html><head><title>Search</title><script src='https://cdn.cookielaw.org/otSDKStub.js'></script>"
    "<script>window.didomiConfig={}</script></head><body>Nothing matched</body></html>",
    '{"hits": [], "total": 0}',
])
def test_an_ordinary_page_is_not_a_wall(html):
    assert wall_page(html) is None


@pytest.mark.parametrize("path", sorted({*ZERO_HIT_FIXTURES.values(), "discovery/fixtures/jobbsafari/search_empty.html"}))
def test_no_saved_zero_hit_answer_is_a_wall(path):
    assert wall_page((TESTS_DIR / "scrapers" / path).read_text(encoding="utf-8")) is None


def test_the_sdk_offers_it():
    assert sdk.wall_page is wall_page
