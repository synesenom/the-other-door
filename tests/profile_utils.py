"""Shared helper for tests that need a schema-valid `profile/config.json`.

Not a test module itself (no `test_` prefix). Since issue #137 every command
validates `config.json` against `door.core.profile_loader.Profile` before
doing anything, so fixtures can no longer seed a three-key config: they call
`write_config(profile_dir, {...})`, which fills in the required keys (and
creates the template files the schema checks exist) underneath the
test-specific overrides.
"""

from __future__ import annotations

import json
from pathlib import Path


def base_config(profile_dir: Path) -> dict:
    """The required `Profile` keys, with template files created under `profile_dir`."""
    profile_dir = Path(profile_dir)
    tpl_dir = profile_dir / "_templates"
    tpl_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for key, name in (
        ("cv_template", "cv.template.tex"),
        ("cv_content", "cv.md"),
        ("cover_letter_template", "cover-letter.template.tex"),
    ):
        p = tpl_dir / name
        if not p.exists():
            p.write_text("x")
        paths[key] = str(p)
    return {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "location": "Copenhagen",
        **paths,
        "role_targets": ["data scientist"],
        "remote": "hybrid",
        # `find`'s LinkedIn step is off unless a test asks for it (tests/pipeline/test_discover_unit.py).
        "linkedin_discovery": False,
        "profession_discovery": False,
        "hellowork_discovery": False,
        "jobbsafari_discovery": False,
    }


def write_config(profile_dir: Path, overrides: dict | None = None) -> Path:
    """Write a valid `profile_dir/config.json` (required keys + `overrides`)."""
    profile_dir = Path(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    config = {**base_config(profile_dir), **(overrides or {})}
    path = profile_dir / "config.json"
    path.write_text(json.dumps(config))
    return path
