#!/usr/bin/env python3
"""Profile loader — reads and validates profile/config.json.

`Profile` declares every key the pipeline reads from the config (issue
#137) and forbids unknown ones, so a typo such as ``min_sore`` or
``greenhouse_board`` fails at load time with the key named instead of being
silently ignored at scrape time. `load_config` is the entrypoint the CLI and
MCP cores use: validate once, then hand callers the plain dict they have
always received.
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, ValidationInfo, field_validator, model_validator

from door import i18n
from door.core import photo as photo_mod, workspace

_PROJECT_ROOT = workspace.REPO_ROOT   # where `profile.example/` ships; relative profile paths resolve from `workspace.HOME`


class ConfigError(Exception):
    """`profile/config.json` is malformed or fails validation.

    Deliberately not a `ValueError`: commands already catch `ValueError`
    for their own argument errors, and a config problem must reach the CLI
    group's single renderer instead of being reported as one of those.

    `lines` holds one human-readable line per problem, each prefixed with
    the config path and the dotted key (``<path>: exclude.companies —
    Input should be a valid list``); ``str(exc)`` joins them with newlines.
    """

    def __init__(self, lines: list[str]):
        self.lines = list(lines)
        super().__init__("\n".join(self.lines))


class ExcludeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    companies: list[str] = []
    keywords: list[str] = []


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    email: str
    location: str
    # You need the employer to sponsor a visa or work permit: ads that say they will not, or that
    # require an existing permit, score 0 (matching/scorer.apply_result).
    needs_work_permit: bool = False
    # The LaTeX templates: None = the code's own (`door.core.templates`); a path names the user's own.
    cv_template: Path | None = None
    cv_content: Path
    cover_letter_template: Path | None = None
    # The candidate's CV photo (a JPEG or PNG, kept by `save_photo` as profile/photo.jpg); `compile` puts it in the CV
    # where the country's conventions allow one. None = no photo.
    photo: Path | None = None
    role_targets: list[str]
    search_keywords: list[str] = []
    # The words and phrases that make a job title relevant, in every ad language (proposed with the
    # keywords); [] = any content word of the keywords (`door.matching.title_fit.topic_terms`).
    topic_terms: list[str] = []
    # Free text, in the user's own words and any language: what matters to them in an employer or a job
    # (sector, company size, travel, ...) and what they rule out. Kept as written; the scorer's prompt carries it
    # (`matching.scorer`). "" = none.
    preferences: str = ""
    remote: Literal["yes", "no", "hybrid"]
    # `discover` asks LinkedIn which employers hire for the keywords, `follow` then finds
    # their own job feeds (door.pipeline). Off until the user turns it on: its terms forbid
    # automated access, so onboarding asks (`discovery_sources.for_location`).
    linkedin_discovery: bool = False
    # The same for profession.hu, a Hungarian board read only for the employers it lists (door.scrapers.discovery.profession).
    profession_discovery: bool = False
    # The same for HelloWork, a French board read only for the employers it lists (door.scrapers.discovery.hellowork).
    hellowork_discovery: bool = False
    # The same for Jobbsafari (Sweden), read only for the employers and their apply links (door.scrapers.discovery.jobbsafari).
    jobbsafari_discovery: bool = False
    exclude: ExcludeConfig = ExcludeConfig()
    min_score: float = 0.65
    # Job-ad languages to consider, by name or code; [] = English.
    languages: list[str] = []
    enrich_sources: list[str] = []
    # The `claude` config directory (its login = the plan `claude -p` uses),
    # e.g. "~/.claude-personal"; None = whatever the environment says.
    claude_config_dir: str | None = None

    # History / liveness / dedup (src/door/commands/scrape.py, core/liveness.py,
    # matching/dedup.py).
    recheck_after_days: int | None = Field(default=None, ge=0)
    # How many sites, and hosts within a per-company feed, a step works on at once
    # (issue #254); 1 = one request at a time. `None` = 8. Each host stays paced.
    scrape_workers: int | None = Field(default=None, ge=1)
    verify_liveness: bool = False
    liveness_expiry_phrases: list[str] = []
    dedup_source_priority: list[str] = []
    dedup_similarity_threshold: float = Field(default=1.0, ge=0.0, le=1.0)

    # Scrape limits (scrapers/boards/jobindex.py, `scrape`).
    max_postings_per_site: int | None = Field(default=None, ge=1)
    max_pages_per_keyword: int | None = Field(default=None, ge=1)

    # Offline pre-match pass and `match` (matching/condense.py,
    # matching/prescreen.py, matching/scorer.py). `None` = the module default.
    condense_max_chars: int | None = Field(default=None, ge=1)
    prescreen_top_n: int | None = Field(default=None, ge=1)
    prescreen_min: float | None = Field(default=None, ge=0.0, le=1.0)

    # Language pass (matching/language.py): translate non-English titles into
    # `title_en` with one `claude -p` call per 50 titles. `None` = Haiku.
    translate_titles: bool = True
    translate_model: str | None = None

    # Review session (issue #146): `list` hides postings older than this many
    # days (posted_at, else scraped_at); null disables. `revise` model.
    max_age_days: int | None = Field(default=30, ge=1)
    follow_ai_fallback: bool = True
    # A followed employer none of whose collected postings was on topic (or scored >= min_score) for
    # this many days becomes dormant and is no longer collected; 0 = never. See door.pipeline.collect.
    retire_after_days: int = Field(default=90, ge=0)
    revise_model: str | None = None

    @field_validator("role_targets")
    @classmethod
    def _non_empty_roles(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("role_targets must contain at least one entry")
        return v

    @field_validator("languages")
    @classmethod
    def _supported_languages(cls, v: list[str]) -> list[str]:
        # The ad languages to consider (`scrape` drops the rest); the
        # candidate's own language skills and levels belong in the CV.
        supported = i18n.supported_language_names()
        for entry in v:
            if i18n.language_code(entry) is None:
                raise ValueError(
                    f"{entry!r} is not a supported job-ad language (supported: {supported}); "
                    "put language levels in your CV"
                )
        return v

    @field_validator("min_score")
    @classmethod
    def _score_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("min_score must be between 0.0 and 1.0")
        return v

    @model_validator(mode="after")
    def _resolve_paths(self) -> "Profile":
        for field in ("cv_template", "cv_content", "cover_letter_template", "photo"):
            p: Path | None = getattr(self, field)
            if p is not None and not p.is_absolute():
                resolved = (workspace.HOME / p).resolve()
                object.__setattr__(self, field, resolved)
        return self

    @model_validator(mode="after")
    def _paths_exist(self, info: ValidationInfo) -> "Profile":
        # `load_config(check_paths=False)` skips this: the batch commands never
        # read the templates, so a missing one must not stop a `find`.
        # The CV is not checked: no CV is "no CV yet" (`init` never copies the example's),
        # and the commands that read it say so themselves.
        if info.context and info.context.get("check_paths") is False:
            return self
        for field in ("cv_template", "cover_letter_template"):
            p: Path | None = getattr(self, field)
            if p is not None and not p.exists():
                raise ValueError(f"{field} not found: {p}")
        if self.photo is not None:
            why = photo_mod.problem(self.photo)
            if why:
                raise ValueError(why)
        return self


def read_config_data(config_path: Path) -> dict:
    """The raw JSON of `config_path`.

    Raises:
        ConfigError: the file is not valid JSON.
    """
    config_path = Path(config_path)
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError([f"{config_path}: invalid JSON — {exc}"]) from None


def load_profile(config_path: Path | None = None) -> Profile:
    if config_path is None:
        config_path = workspace.PROFILE_DIR / "config.json"
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"Profile config not found: {config_path}\n"
            "Copy profile.example/ to profile/ and fill in your details."
        )
    return Profile.model_validate(read_config_data(config_path))


def format_validation_error(exc: ValidationError, config_path: Path | str) -> list[str]:
    """One ``<path>: <dotted.key> — <message>`` line per pydantic error."""
    lines = []
    for err in exc.errors():
        key = ".".join(str(part) for part in err["loc"])
        msg = err["msg"].removeprefix("Value error, ")
        lines.append(f"{config_path}: {key} — {msg}" if key else f"{config_path}: {msg}")
    return lines


def load_config(config_path: Path, check_paths: bool = False) -> dict:
    """Validate ``config_path`` against `Profile`; return it as a plain dict.

    Keys, types and ranges are always checked. Whether the template/CV files
    exist is only checked with ``check_paths=True`` (`doctor`'s profile check):
    ``find``/``list`` never read them.

    The dict contains only the keys the file actually sets (normalised by
    the schema — e.g. template paths resolved to absolute paths), so callers
    keep their ``config.get(key, default)`` fallbacks and scrapers keep
    receiving the ``scrape(config: dict)`` shape they always have.

    Raises:
        FileNotFoundError: ``config_path`` does not exist.
        ConfigError: the file is not valid JSON or fails validation.
    """
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"profile/config.json not found: {config_path}")
    data = read_config_data(config_path)
    try:
        profile = Profile.model_validate(data, context={"check_paths": check_paths})
    except ValidationError as exc:
        raise ConfigError(format_validation_error(exc, config_path)) from None
    return profile.model_dump(mode="json", exclude_unset=True)
