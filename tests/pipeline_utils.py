"""Helpers for the pipeline step tests (tests/pipeline/): postings and fake scrapers."""

import re


def posting(n=1, company="Acme", source="jobindex", **overrides) -> dict:
    p = {
        "id": f"{source}-{re.sub('[^a-z0-9]+', '-', company.lower())}-{n}", "title": "Data Scientist", "company": company,
        "location": "Copenhagen", "url": f"https://www.jobindex.dk/jobannonce/{n}",
        "description": "We are looking for a data scientist who will join our team and work with Python.",
        "source": source, "scraped_at": "2026-06-13T00:00:00Z", "platform_id": f"{source}-{company}-{n}",
    }
    p.update(overrides)
    return p


def fake_scraper(monkeypatch, site, scrape_fn):
    """Replace one site's `scrape` (and drop its streaming `iter_scrape`)."""
    import importlib

    from door.core.sites import SITES

    module = importlib.import_module(SITES[site].module)
    monkeypatch.setattr(module, "scrape", scrape_fn)
    monkeypatch.delattr(module, "iter_scrape", raising=False)
