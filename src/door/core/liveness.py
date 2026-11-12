#!/usr/bin/env python3
"""Liveness verification for scraped job postings.

Provides a lightweight HTTP-based check that classifies each new posting as
'live', 'expired', or 'indeterminate' before it reaches the matcher.

Classification rules
--------------------
- 404 / 410           → expired
- 2xx with an expiry phrase in the body  → expired
- other 2xx           → live
- 403 / 5xx / network error → indeterminate  (kept, never dropped)

Usage::

    from liveness import verify_liveness
    live_paths = verify_liveness(candidate_paths, config)
"""

import json
from pathlib import Path

import requests.exceptions

from door.core import progress
from door.scrapers.http_client import PoliteSession

# Phrases that, when found in the (lowercased) response body of a 200-family
# response, indicate the posting has been removed from the board.
_DEFAULT_EXPIRY_PHRASES: list[str] = [
    "no longer available",
    "position has been filled",
    "job has been filled",
    "this job is no longer",
    "vacancy has been filled",
]


def classify_response(status_code: int, body: str, config: dict) -> str:
    """Classify an HTTP response as 'live', 'expired', or 'indeterminate'.

    Parameters
    ----------
    status_code:
        The HTTP status code of the response.
    body:
        The response body text.
    config:
        Profile config dict.  ``config.get("liveness_expiry_phrases", [])``
        is prepended to the default expiry-phrase list.

    Returns
    -------
    str
        One of ``"live"``, ``"expired"``, or ``"indeterminate"``.
    """
    # Hard 404/410 → definitively expired.
    if status_code in (404, 410):
        return "expired"

    # 403 → login-walled board; do not classify as expired.
    if status_code == 403:
        return "indeterminate"

    # 5xx → server-side error; keep the posting.
    if status_code >= 500:
        return "indeterminate"

    # 2xx — check for in-page expiry signals.
    if 200 <= status_code < 300:
        custom_phrases: list[str] = config.get("liveness_expiry_phrases", [])
        all_phrases = custom_phrases + _DEFAULT_EXPIRY_PHRASES
        body_lower = body.lower()
        if any(phrase.lower() in body_lower for phrase in all_phrases):
            return "expired"
        return "live"

    # Any other status (1xx, 3xx, etc.) → indeterminate.
    return "indeterminate"


def _check_one(
    session: PoliteSession,
    path: Path,
    data: dict,
    config: dict,
) -> str:
    """Check liveness of a single posting and return the classification.

    The caller is responsible for writing the result back to *path*.

    Parameters
    ----------
    session:
        Shared ``PoliteSession`` instance (robots cache shared across calls).
    path:
        Path to the posting JSON file (used only for logging).
    data:
        Deserialized posting dict.
    config:
        Profile config dict.
    """
    url = data.get("url", "")
    if not url:
        return "indeterminate"

    try:
        resp = session.get(url)
        return classify_response(resp.status_code, resp.text, config)
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        body = exc.response.text if exc.response is not None else ""
        return classify_response(status, body, config)
    except Exception:
        return "indeterminate"


def verify_liveness(paths: list[Path], config: dict) -> list[Path]:
    """Verify liveness of a list of posting JSON paths.

    Only the paths in *paths* are checked — callers are expected to pass
    only newly-scraped postings so the request volume stays bounded.

    For each posting:
    - Performs a jittered GET (via ``PoliteSession``, which reads robots.txt
      first; a page it disallows stays ``indeterminate``).
    - Writes ``liveness_status`` back into the posting JSON.
    - If the posting is 'expired', also sets ``score=0.0`` and
      ``score_reason="expired"`` and excludes the path from the return value.
    - For 'live' and 'indeterminate', the path is included in the return value.

    Parameters
    ----------
    paths:
        List of ``Path`` objects pointing to posting JSON files to check.
    config:
        Profile config dict (forwarded to ``classify_response``).

    Returns
    -------
    list[Path]
        Subset of *paths* that are NOT expired (live + indeterminate).
    """
    if not paths:
        return []

    session = PoliteSession(min_delay=1.0, max_delay=2.5)
    surviving: list[Path] = []

    for i, path in enumerate(paths, 1):
        try:
            data = json.loads(path.read_text())
        except Exception:
            surviving.append(path)
            progress.report("liveness: unreadable", i, len(paths), stage="liveness")
            continue

        status = _check_one(session, path, data, config)
        data["liveness_status"] = status

        if status == "expired":
            data["score"] = 0.0
            data["score_reason"] = "expired"
            path.write_text(json.dumps(data, indent=2, default=str))
            progress.report("liveness: expired", i, len(paths), stage="liveness")
        else:
            path.write_text(json.dumps(data, indent=2, default=str))
            progress.report(f"liveness: {status}", i, len(paths), stage="liveness")
            surviving.append(path)

    return surviving
