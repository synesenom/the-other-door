"""HR-ON (issue #282): a platform door recognises but does not follow, so it has no `Site`.

Only the detection half of the feed contract (`door.scrapers.sdk`); `LINK_PLATFORMS` is empty when a
link to it on a page must not decide which platform the page is on."""

from door.scrapers.sdk import Detection, parts, unfollowable

# The platform's own domains: a host on one is a customer's, never the employer's name (#436).
PLATFORM_DOMAINS = ("hr-on.com",)

LINK_PLATFORMS: tuple[str, ...] = ()
_REASON = "HR-ON: its job lists load by script from a private API and its robots.txt disallows everything; not followed"


def detect_url(url: str) -> Detection | None:
    """An HR-ON link: its own host, or any page whose ``hr=show-job`` parameter opens an HR-ON ad."""
    host, _path, query = parts(url.strip())
    if host.endswith("hr-on.com") or (query.get("hr") or "").lower().startswith("show-job"):
        return unfollowable("hr_on", host, _REASON)
    return None


def detect_html(html: str, url: str) -> Detection | None:
    """A page that embeds the HR-ON frame."""
    if "recruit.hr-on.com/frame-api" in html:
        return unfollowable("hr_on", f"{url} embeds the HR-ON frame", _REASON)
    return None
