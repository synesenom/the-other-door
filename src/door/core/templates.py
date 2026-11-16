"""Where the HTML templates are read from (#56, #146).

`cv.template.html` and `cover-letter.template.html` (and the `fonts/` they load) ship with the code in `profile.example/`,
so a release that changes the building blocks never breaks a profile that holds an older copy. A user who wants their own
styling keeps a file of that name in `profile/` (or names one in `config.json`); it wins. A file that is not `.html`
(an old LaTeX template) is never read: a browser cannot print it.

A template's folder may hold `template.json` (#188, `manifest`): what the style lends the page beyond the HTML (the fonts
and icons it serves, its own page limit, a side column). Without one the template prints as it always did.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from door import i18n
from door.core import workspace

# The config key of each template and the file it defaults to.
FILES = {"cv_template": "cv.template.html", "cover_letter_template": "cover-letter.template.html"}


def resolve(key: str, config: dict | None = None, profile_dir: Path | None = None, example_dir: Path | None = None) -> Path:
    """The template for ``key`` (``cv_template`` or ``cover_letter_template``), as an absolute path.

    The file `config` names (relative paths from the data folder) when it is there; else the file of that name the user
    put in `profile/`; else the code's own in `profile.example/`.
    """
    name = FILES[key]
    named = (config or {}).get(key)
    if named and str(named).lower().endswith(".html"):
        path = Path(named)
        path = path if path.is_absolute() else workspace.HOME / path
        if path.is_file():
            return path
    own = Path(profile_dir if profile_dir is not None else workspace.PROFILE_DIR) / name
    if own.is_file():
        return own
    return Path(example_dir if example_dir is not None else workspace.PROFILE_EXAMPLE_DIR) / name


MANIFEST_FILE = "template.json"
ICON_KINDS = ("phone", "email", "web", "location", "linkedin", "github", "date")
# The section kinds a column can hold: the CV sections `i18n` names, and the two more a CV commonly has.
SECTION_KINDS = (*i18n.CvSections.model_fields, "languages", "interests")


def _bare_name(name: str, suffix: str) -> str:
    """`name` when it is a file name ending in `suffix`, in the folder beside the template and not a path."""
    if not name or any(c in name for c in "/\\") or name.startswith(".") or not name.lower().endswith(suffix):
        raise ValueError(f"{name!r}: expected a plain file name ending in {suffix}")
    return name


class Columns(BaseModel):
    """The sections placed in the narrow side column; the rest stay in the main one."""

    model_config = ConfigDict(extra="forbid")
    side: list[str] = []

    @field_validator("side")
    @classmethod
    def _kinds(cls, v: list[str]) -> list[str]:
        for kind in v:
            if kind not in SECTION_KINDS:
                raise ValueError(f"{kind!r} is not a section kind ({', '.join(SECTION_KINDS)})")
        return v


class Manifest(BaseModel):
    """`template.json`: ``fonts`` (TrueType files in `fonts/` beside it), ``icons`` (kind to an SVG in `icons/`),
    ``max_pages`` (the template's own limit, 1 to 3) and ``columns`` (absent: one column)."""

    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    fonts: list[str] = []
    icons: dict[str, str] = {}
    max_pages: int | None = Field(default=None, ge=1, le=3)
    columns: Columns | None = None
    exists: bool = Field(default=False, exclude=True)

    @field_validator("fonts")
    @classmethod
    def _fonts(cls, v: list[str]) -> list[str]:
        return [_bare_name(name, ".ttf") for name in v]

    @field_validator("icons")
    @classmethod
    def _icons(cls, v: dict[str, str]) -> dict[str, str]:
        for kind, name in v.items():
            if kind not in ICON_KINDS:
                raise ValueError(f"{kind!r} is not an icon kind ({', '.join(ICON_KINDS)})")
            _bare_name(name, ".svg")
        return v


def manifest(template_path: Path) -> Manifest:
    """The manifest of the folder `template_path` is in; the defaults (``exists`` False) when it has none.

    Raises:
        ValueError: `template.json` is not valid JSON, or names a field, font, icon or section it may not.
    """
    path = Path(template_path).parent / MANIFEST_FILE
    if not path.is_file():
        return Manifest()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"{MANIFEST_FILE}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{MANIFEST_FILE}: expected an object")
    if "exists" in data:
        raise ValueError(f"{MANIFEST_FILE}: unknown field 'exists'")
    try:
        return Manifest(**data, exists=True)
    except ValueError as exc:
        raise ValueError(f"{MANIFEST_FILE}: {exc}") from exc
