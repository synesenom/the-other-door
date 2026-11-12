"""Employer feeds: one module per applicant-tracking platform (or careers-site kind) whose per-employer job
feeds `collect` reads for the followed employers of `profile/companies.json`, in `door.core.ats_detect.PRECEDENCE`
order. Each also detects its own feed (`detect_url`, `feed_url`, …: the feed contract in `door.scrapers.sdk`); the
platforms door recognises but does not follow (`hr_on`, `oracle_hcm`, `phenom`, `ponty`, `jobaffinity`, `icims`, `welcometothejungle`) have only that half."""
