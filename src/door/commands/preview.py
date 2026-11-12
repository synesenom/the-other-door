"""A first look while onboarding: a handful of ads of one board, scored against the CV before anything is
saved. The first run still follows; this writes nothing to `jobs/` and works before the profile exists.
"""

import importlib
from datetime import datetime, timedelta, timezone

from door import i18n
from door import scrapers
from door.core import sites
from door.matching import scorer, title_fit

_WINDOW_DAYS = 7


def _board_records(site: str, config: dict, since: datetime | None):
    """A board's records, one by one when it can stream them, so reading stops at the limit."""
    scraper = importlib.import_module(sites.SITES[site].module)
    reader = getattr(scraper, "iter_scrape", None) or scraper.scrape
    return reader(config, known_ids=frozenset(), since=since)


def _on_topic_ads(records, config: dict, limit: int) -> list[dict]:
    terms = title_fit.topic_terms(config)
    ads = []
    for record in records:
        if record.get("seen_only") or not title_fit.on_topic(record.get("title") or "", terms):
            continue
        ads.append(record)
        if len(ads) >= limit:
            break
    return ads


def _preview_core(config: dict, cv_text: str | None, *, limit: int = 5) -> dict:
    """Read the newest ads for the first keyword from the first board of `config["location"]`, keep the on-topic
    titles, score at most `limit` against `cv_text`. Any failure is a `warning`, never an error: a first look must
    not stop onboarding.

    Returns:
        ``{"board", "matches": [{"title", "company", "location", "score", "score_reason", "url"}]}``, best first,
        plus ``"warning"`` when there is nothing to show.
    """
    boards = sites.boards_for_location(config.get("location") or "")
    keywords = config.get("search_keywords") or config.get("role_targets") or []
    board = boards[0] if boards else None
    result = {"board": board, "matches": []}
    if not board:
        return {**result, "warning": "no job board to read for this city"}
    if not (cv_text and keywords):
        return {**result, "warning": "no CV or search term to look with yet"}
    country = i18n.country_for_location(config.get("location") or "")
    reading = {
        **config, "search_keywords": keywords[:1], "max_pages_per_keyword": 1,
        "_mode": "search", "_country": country.code.lower() if country else None,
    }
    since = datetime.now(timezone.utc) - timedelta(days=_WINDOW_DAYS)
    try:
        ads = _on_topic_ads(_board_records(board, reading, since=since), config, limit)
        if not ads:
            return {**result, "warning": f"no ad on {sites.source_name(board) or board} fits yet; the full search looks further"}
        prompt = scorer.build_system_prompt(config, cv_text, scorer.load_rubric_md())
        scores, _failed = scorer.score_postings(ads, system_prompt=prompt)
    except Exception as exc:  # any scraper or scorer failure: a first look is never worth an error
        return {**result, "warning": f"no first look this time: {exc}"}
    finally:
        # The scraper's bookkeeping stays out of the real run's report.
        scrapers.drain_errors(board)
    matches = [
        {**{key: ad.get(key) for key in ("title", "company", "location", "url")},
         "score": scores[ad["id"]]["score"], "score_reason": scores[ad["id"]]["score_reason"]}
        for ad in ads if ad["id"] in scores
    ]
    if not matches:
        return {**result, "warning": "no first look this time: the ads could not be scored"}
    return {**result, "matches": sorted(matches, key=lambda m: m["score"], reverse=True)}
