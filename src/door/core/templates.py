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
import re
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
# The section kinds a column can hold: the CV sections `i18n` names.
SECTION_KINDS = tuple(i18n.CvSections.model_fields)


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


def manifest(template_path: Path) -> Manifest | None:
    """The manifest of the folder `template_path` is in; None when it has none.

    Raises:
        ValueError: `template.json` is not valid JSON, or names a field, font, icon or section it may not.
    """
    path = Path(template_path).parent / MANIFEST_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"{MANIFEST_FILE}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{MANIFEST_FILE}: expected an object")
    try:
        return Manifest(**data)
    except ValueError as exc:
        raise ValueError(f"{MANIFEST_FILE}: {exc}") from exc


def _fonts_dir() -> Path:
    """The folder the templates' `/fonts/...` is served from: the profile's own when it holds TrueType files, else the
    code's. (Chromium writes a CFF `.otf` font into a PDF as nameless text.)"""
    own = workspace.PROFILE_DIR / "fonts"
    if own.is_dir() and any(own.glob("*.ttf")):
        return own
    return workspace.PROFILE_EXAMPLE_DIR / "fonts"


def _named(folder: Path, names) -> list[Path]:
    """The files `names` in `folder`.

    Raises:
        ValueError: one of them is not there.
    """
    files = [folder / name for name in names]
    for file in files:
        if not file.is_file():
            raise ValueError(f"{MANIFEST_FILE} names {folder.name}/{file.name}, which is not in {folder}")
    return files


def assets(template_path: Path) -> dict[str, list[Path]]:
    """What the print serves beside the page: the fonts a `template.json` names (#188), from the `fonts/` beside the
    template, else the TrueType files `_fonts_dir` finds; and the icons it names, from the `icons/` beside it.

    Raises:
        ValueError: the manifest is invalid, or names a file that is not there.
    """
    found = manifest(template_path)
    folder = Path(template_path).parent
    if found and found.fonts:
        served = {"fonts": _named(folder / "fonts", found.fonts)}
    else:
        served = {"fonts": sorted(_fonts_dir().glob("*.ttf"))}
    if found and found.icons:
        served["icons"] = _named(folder / "icons", found.icons.values())
    return served


_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_PAGE_MARGIN = re.compile(r"@page\b[^{]*\{[^}]*?\bmargin\s*:\s*([^;}]+)", re.I)
_POINTS = {"cm": 72 / 2.54, "mm": 72 / 25.4, "pt": 1.0, "in": 72.0, "px": 0.75}
_LENGTH = re.compile(r"^(-?\d*\.?\d+)(cm|mm|pt|in|px)?$")


def page_margins(template_html: str) -> tuple[float, float, float, float]:
    """The ``@page { margin }`` of `template_html` in points as (top, right, bottom, left), CSS shorthand of 1 to 4
    values in cm, mm, pt, in or px (a bare 0 too). Zeros (the page box) when there is no such rule or any value is
    not one of these (auto, rem, var(...))."""
    match = _PAGE_MARGIN.search(_COMMENT.sub("", template_html))
    if not match:
        return (0.0, 0.0, 0.0, 0.0)
    values: list[float] = []
    for part in match.group(1).split():
        length = _LENGTH.match(part.strip())
        if not length or (length.group(2) is None and float(length.group(1)) != 0):
            return (0.0, 0.0, 0.0, 0.0)
        values.append(float(length.group(1)) * _POINTS.get(length.group(2) or "pt", 1.0))
    if not 1 <= len(values) <= 4:
        return (0.0, 0.0, 0.0, 0.0)
    top, right, bottom, left = {1: lambda v: (v[0],) * 4, 2: lambda v: (v[0], v[1], v[0], v[1]),
                                3: lambda v: (v[0], v[1], v[2], v[1]), 4: lambda v: tuple(v)}[len(values)](values)
    return (top, right, bottom, left)
