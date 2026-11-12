#!/usr/bin/env python3
"""Shared data model for job postings."""

import re
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel


class JobPosting(BaseModel):
    id: str
    title: str
    company: str
    location: str
    url: str
    description: str
    description_condensed: str | None = None
    source: str
    scraped_at: datetime
    platform_id: str | None = None
    posted_at: datetime | None = None
    score: float | None = None
    score_reason: str | None = None
    prescreen_score: float | None = None
    scored_by: str | None = None
    scored_at: str | None = None
    matching_skills: list[str] = []
    missing_skills: list[str] = []
    liveness_status: str | None = None
    duplicate_of: str | None = None
    apply_type: Literal["easy_apply", "external", "unknown"] | None = None
    apply_url: str | None = None
    employer: str | None = None  # the companies.json entry this posting belongs to, when known
    integrity: dict | None = None  # {"verdict": "clean"|"suspicious", "findings": [{kind, excerpt}]}, see matching/integrity.py


def normalize_platform_id(raw: str) -> str:
    """A platform id as it appears in a job id: lowercase, ``[a-z0-9_-]`` only.

    Every other run of characters becomes one ``-``; leading and trailing ``-``
    are stripped. Scrapers and ``scripts/migrate_job_ids.py`` share this one rule.
    """
    return re.sub(r"[^a-z0-9_-]+", "-", str(raw).lower()).strip("-")


def tenant_platform_id(url: str, raw: str) -> str:
    """Fold the host of *url* into a per-tenant platform id: ``<host>-<raw>``.

    For platforms whose ids repeat across tenants (SuccessFactors, Teamtailor,
    Pinpoint). Idempotent when *raw* already starts with ``<host>-``; a URL
    with no host returns *raw* unchanged.
    """
    host = (urlparse(url or "").netloc or "").lower()
    raw = str(raw)
    if not host or raw.lower().startswith(f"{host}-"):
        return raw
    return f"{host}-{raw}"


def make_job_id(site: str, platform_id: str) -> str:
    """The job id: ``<site>.<platform_id>`` (the platform id normalised)."""
    return f"{site}.{normalize_platform_id(platform_id)}"


def load_posting(path: Path) -> JobPosting:
    return JobPosting.model_validate_json(Path(path).read_text())


def save_posting(posting: JobPosting, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(posting.model_dump_json(indent=2))
