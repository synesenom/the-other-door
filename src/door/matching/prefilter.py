"""Hard pre-filter for job postings (issue #15).

Drops obviously-incompatible postings in pure Python (no LLM) before the
matcher agent runs, cutting token cost and noise.

Exclusion rules applied in order:
  1. Company is in config["exclude"]["companies"] (case-insensitive).
  2. Title contains a keyword from config["exclude"]["keywords"] as a whole
     word (case-insensitive; a trailing "*" matches a prefix). Only the title:
     a lead role's description may mention the students or interns it leads.
     A keyword that is a false friend in the ad's language (Danish "intern" =
     internal, see ``src/door/i18n/lang/``) is not applied to that ad.
  3. Location is clearly incompatible with the profile location/remote setting
     (kept when ambiguous: empty location, a remote/hybrid word in any language
     in the location string, profile remote is "yes" or "hybrid", or the
     location names the profile city, by any of its names in
     ``src/door/i18n/country/``, or a town of its commute area, or no known
     place at all).

Dropped postings have ``score=0.0`` and ``score_reason="excluded"`` written
back to disk; surviving postings are returned as a list of Path objects and
are not modified.
"""

from __future__ import annotations

import json
from pathlib import Path

from door import i18n

_REMOTE_RE = i18n.compile_words(i18n.marker_words("remote"))


def _is_location_compatible(posting_location: str, config: dict) -> bool:
    """Return True if the posting location is compatible with the profile.

    Keeps (returns True) when:
    - Location string is empty — ambiguous, keep.
    - Location string contains a remote/hybrid word in any language ("remote",
      "hjemmearbejde", ...) — ambiguous, keep.
    - Profile remote setting is "yes" or "hybrid" — candidate is open to remote/hybrid,
      so any location is potentially fine.
    - Profile location city appears in the posting location (case-insensitive),
      by its own spelling or any of its names in ``src/door/i18n/country/`` — match.

    - The posting location names a town of the profile city's commute area
      (the country file's ``[commute]``) — match.
    - The posting location names no known place (a city, a commute town or a
      country in ``src/door/i18n/``): a workplace or a building, ambiguous.

    Drops (returns False) only when all of the following hold:
    - Posting location is non-empty.
    - Does not contain "remote" or "hybrid".
    - Profile remote is "no" (or not set).
    - Neither the profile city nor its commute area is found in the posting location.
    - The posting location names a known place outside them.
    """
    loc = posting_location.strip()

    # Ambiguous: no location data
    if not loc:
        return True

    loc_lower = loc.lower()

    # Ambiguous: posting mentions remote or hybrid work arrangement
    if _REMOTE_RE.search(loc):
        return True

    # Profile is open to remote or hybrid — keep all locations
    profile_remote = config.get("remote", "no").lower()
    if profile_remote in ("yes", "hybrid"):
        return True

    # Check if the profile city appears in the posting location
    profile_city = config.get("location", "").strip().lower()
    if profile_city and profile_city in loc_lower:
        return True
    city_names = i18n.city_names(profile_city)
    if city_names and i18n.compile_words(city_names).search(loc):
        return True

    # The city's commute area (the country file's [commute]) — match
    commute = i18n.commute_names(profile_city)
    if commute and i18n.compile_words(commute).search(loc):
        return True

    # A location naming no known place at all (a workplace, a building) is
    # ambiguous — keep. Only a known place outside the commute area is a mismatch.
    return not i18n.compile_words(i18n.place_names()).search(loc)


def prefilter(candidates_dir: Path, config: dict) -> list[Path]:
    """Filter scraped job postings, returning paths to surviving candidates.

    Parameters
    ----------
    candidates_dir:
        Directory containing site subdirectories with ``<job_id>.json`` files
        (e.g. ``jobs/postings/2026-06-14/``).  Searched recursively for ``*.json``.
    config:
        Raw profile config dict (from ``profile/config.json``).

    Returns
    -------
    list[Path]
        Paths to postings that passed all filters.  Dropped postings are
        rewritten in-place with ``score=0.0`` and ``score_reason="excluded"``.
    """
    candidates_dir = Path(candidates_dir)

    exclude = config.get("exclude", {})
    excluded_companies: list[str] = [c.lower() for c in exclude.get("companies", [])]
    excluded_keywords: list[str] = [k.lower() for k in exclude.get("keywords", [])]

    surviving: list[Path] = []

    for json_path in sorted(candidates_dir.rglob("*.json")):
        try:
            data = json.loads(json_path.read_text())
        except (json.JSONDecodeError, OSError):
            # Unreadable/invalid JSON — skip silently
            continue

        # An ad the user added by hand (`add`, #166) was chosen on
        # purpose: never exclude it, and it is not a new scrape candidate.
        if data.get("source") == "manual":
            continue

        # Already decided — scored by `match`, or cut by an earlier pass today.
        # A second scrape the same day re-walks this directory; re-filtering
        # (or re-prescreening) these would overwrite a real score.
        if data.get("score") is not None:
            continue

        drop_reason: str | None = None

        # Rule 1: excluded company
        company = data.get("company", "").lower()
        if company in excluded_companies:
            drop_reason = "excluded"

        # Rule 2: excluded keyword in the title (the whole ad tells its language)
        if drop_reason is None and excluded_keywords:
            title = data.get("title", "")
            keywords = excluded_keywords
            false_friends = i18n.false_friends(i18n.detect_language(title + " " + data.get("description", "")))
            if false_friends:
                keywords = [kw for kw in keywords if kw not in false_friends]
            if i18n.compile_words(keywords).search(title):
                drop_reason = "excluded"

        # Rule 3: incompatible location
        if drop_reason is None:
            posting_location = data.get("location", "")
            if not _is_location_compatible(posting_location, config):
                drop_reason = "excluded"

        if drop_reason is not None:
            # Write exclusion markers back to disk
            data["score"] = 0.0
            data["score_reason"] = drop_reason
            try:
                json_path.write_text(json.dumps(data, indent=2, default=str))
            except OSError:
                pass  # best-effort write
        else:
            surviving.append(json_path)

    return surviving
