"""Reading a run record, `jobs/runs/<timestamp>.json`.

A record has one block per step that ran (``search``, ``discover``, ``follow``, ``collect``,
``match``; None or absent for a step that did not), written by `door.commands.find`.
"""

from __future__ import annotations


def site_entries(record: dict) -> list[dict]:
    """The per-site outcomes of a run: the boards of ``search`` then the platforms of ``collect``."""
    blocks = [record.get(name) or {} for name in ("search", "collect")]
    return [e for block in blocks for e in block.get("sites") or []]


def postings_scraped(record: dict) -> int:
    """How many postings the run's sites wrote (outcome ``ok`` only)."""
    return sum(e.get("count", 0) or 0 for e in site_entries(record) if e.get("outcome") == "ok")


def scored(record: dict) -> int:
    return (record.get("match") or {}).get("scored", 0)
