"""How fresh a posting must be for `scrape` to keep it.

By default `scrape` keeps only postings published since that site's last
successful scrape, so an occasional manual run picks up exactly what is new.
The watermark lives in `jobs/scrape_state.json` (`{site: {"last_success":
iso}}`, plus `"pushback_at"` while a site that refused door rests). The cutoff overlaps the watermark by a day, because many boards
only give a publish date, not a time. It never reaches back further than
`max_age_days` (default 30), so a site's first scrape, or one after a long
break, keeps at most that window.

A posting with no `posted_at` is always kept; the cross-run history
(`jobs/history.json`) still stops it being written twice.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from door.core import utils

_STATE_FILE = "scrape_state.json"
_OVERLAP = timedelta(days=1)


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def load_scrape_state(jobs_dir: Path) -> dict:
    """`jobs/scrape_state.json`, or {} if missing/unreadable."""
    try:
        data = json.loads((Path(jobs_dir) / _STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record_scrape(jobs_dir: Path, site: str, started_at: datetime) -> None:
    """Advance `site`'s watermark to `started_at` (atomic write); clears a pushback."""
    state = load_scrape_state(jobs_dir)
    state[site] = {"last_success": started_at.isoformat()}
    utils.write_json_atomic(Path(jobs_dir) / _STATE_FILE, state)


def record_pushback(jobs_dir: Path, site: str, at: datetime) -> None:
    """Stamp `site`'s `pushback_at` (it refused door), keeping its watermark."""
    state = load_scrape_state(jobs_dir)
    state[site] = {**(state.get(site) or {}), "pushback_at": at.isoformat()}
    utils.write_json_atomic(Path(jobs_dir) / _STATE_FILE, state)


def resting_until(site: str, cooldown_hours: int, state: dict, now: datetime) -> datetime | None:
    """When `site` may be asked again after its last pushback; None when it is not resting."""
    if not cooldown_hours:
        return None
    at = _parse_dt((state.get(site) or {}).get("pushback_at"))
    if at is None:
        return None
    until = at + timedelta(hours=cooldown_hours)
    return until if now < until else None


def site_cutoff(
    site: str,
    state: dict,
    max_age_days: int | None,
    now: datetime,
) -> datetime | None:
    """The oldest `posted_at` `scrape` keeps for `site`; None keeps everything.

    The site's watermark, minus a day, capped at `max_age_days`.
    """
    last = _parse_dt((state.get(site) or {}).get("last_success"))
    cap = now - timedelta(days=max_age_days) if max_age_days is not None else None
    if last is None:
        return cap
    return max(last - _OVERLAP, cap) if cap is not None else last - _OVERLAP


def days_back(since: datetime | None, now: datetime) -> int | None:
    """`since` as whole days before `now`, rounded up (at least 1) — for
    boards whose search takes a "posted in the last N days" filter."""
    if since is None:
        return None
    return max(1, math.ceil((now - since) / timedelta(days=1)))


def is_stale(posting: dict, cutoff: datetime | None) -> bool:
    """Published before `cutoff`. Undated postings are never stale."""
    if cutoff is None:
        return False
    posted = _parse_dt(posting.get("posted_at"))
    return posted is not None and posted < cutoff
