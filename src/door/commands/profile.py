"""`init`: set door up — your sources, what they tell us, one review, then a first run."""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import click

from door import i18n
from door.commands import _prompts
from door.core import companies as companies_mod, discovery_sources, workspace
from door.core import profile_loader
from door.core.profile_loader import ConfigError, load_config, read_config_data
from door.core import sites


# Never copied from profile.example/: config.json is merged and validated by
# the caller; story_bank.md holds made-up stories the tailor would read as the
# candidate's own (it starts absent, and the tailor fills it from real CVs);
# cv.md is the example person's CV, never the candidate's (none is "no CV yet").
_NOT_COPIED = {Path("config.json"), Path("story_bank.md"), Path("companies.json"), Path("cv.md")}


def _copy_missing_example_files(example_dir: Path, profile_dir: Path) -> list[str]:
    """Copy every file from `example_dir` into `profile_dir`, skipping any
    destination path that already exists.

    Never overwrites an existing file (e.g. a user's already-edited
    `cv.md`) — this is what makes re-running `init` on a partially
    populated `profile/` safe. `config.json` is handled separately (via
    `_load_base_config`/the caller's write-after-validation step);
    `story_bank.md` and `cv.md` are example content, so none is copied here.

    Returns the copied paths, relative to `profile_dir`, in sorted order.
    """
    copied = []
    for src in sorted(example_dir.rglob("*")):
        if src.is_dir():
            continue
        rel = src.relative_to(example_dir)
        if rel in _NOT_COPIED:
            continue
        dest = profile_dir / rel
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(str(rel))
    return copied


def _load_base_config(profile_dir: Path, example_dir: Path) -> dict:
    """Return the config dict to seed prompts from.

    Prefers an already-existing `profile/config.json` (so re-running `init`
    keeps previously-entered values as defaults); falls back to
    `profile.example/config.json` for a fresh bootstrap.
    """
    config_path = profile_dir / "config.json"
    if config_path.exists():
        return read_config_data(config_path)
    return json.loads((example_dir / "config.json").read_text())


# The last entry of the location list: type a city that isn't in it.
OTHER_LOCATION = "Other…"


def _split(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _location_default(location: str) -> str:
    """The location list's preselected entry for a saved `location`: its
    city when it is a known one, "Other…" otherwise."""
    for city, _ in i18n.known_cities():
        if city.lower() == (location or "").strip().lower():
            return city
    return OTHER_LOCATION if location else i18n.known_cities()[0][0]


def _language_name(value: str) -> str:
    code = i18n.language_code(value)
    return i18n.languages()[code].name if code else value


def _need_one(kind: str):
    return lambda picked: None if picked else f"Pick at least one {kind} (space to select)."


def _parse_set(ctx, param, values: tuple[str, ...]) -> dict:
    """`--set key=value` → `{key: value}`: JSON when it parses, the string otherwise."""
    other = {}
    for raw in values:
        key, sep, value = raw.partition("=")
        if not sep or not key.strip():
            raise click.BadParameter(f"expected KEY=VALUE, got {raw!r}", ctx=ctx, param=param)
        try:
            other[key.strip()] = json.loads(value)
        except json.JSONDecodeError:
            other[key.strip()] = value
    return other


def _csv(ctx, param, value: str | None) -> list[str] | None:
    return None if value is None else _split(value)


def _profile_fields(
    *,
    name: str | None = None,
    email: str | None = None,
    location: str | None = None,
    languages: list[str] | None = None,
    role_targets: list[str] | None = None,
    search_keywords: list[str] | None = None,
    topic_terms: list[str] | None = None,
    remote: str | None = None,
    min_score: float | None = None,
    exclude_companies: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
    other: dict | None = None,
) -> dict:
    """The given profile fields as the dict `_init_core` merges — what both
    `init`'s flags and the `init_profile` tool build. Omitted ones are absent,
    so only the keys the user named change; `exclude_*` nest under `exclude`."""
    fields = {
        key: value
        for key, value in {
            "name": name,
            "email": email,
            "location": location,
            "languages": languages,
            "role_targets": role_targets,
            "search_keywords": search_keywords,
            "topic_terms": topic_terms,
            "remote": remote,
            "min_score": min_score,
        }.items()
        if value is not None
    }
    exclude = {
        key: value
        for key, value in {"companies": exclude_companies, "keywords": exclude_keywords}.items()
        if value is not None
    }
    if exclude:
        fields["exclude"] = exclude
    fields.update(other or {})
    return fields


def _languages_help() -> str:
    """``--languages`` help naming the supported languages (the ones with a file in ``i18n/lang/``)."""
    return f"Job-ad languages to consider, comma-separated ({i18n.supported_language_names()})."


@click.command()
@click.option("--show", is_flag=True, default=False, help="Print the profile (config, CV outline, which files are still the example) and exit.")
@click.option("--name", default=None, help="Your full name.")
@click.option("--email", default=None, help="Your email.")
@click.option("--location", default=None, help="City/region to search in, e.g. Copenhagen.")
@click.option("--languages", default=None, callback=_csv, help=_languages_help())
@click.option("--role-targets", "role_targets", default=None, callback=_csv, help="Job titles to look for, comma-separated.")
@click.option("--search-keywords", "search_keywords", default=None, callback=_csv, help="Broader search terms, comma-separated (default: the role targets).")
@click.option("--topic-terms", "topic_terms", default=None, callback=_csv, help="Words that make a job title relevant, comma-separated (default: any word of the keywords).")
@click.option("--remote", default=None, help="yes, no or hybrid.")
@click.option("--min-score", "min_score", type=float, default=None, help="Match threshold, 0-1.")
@click.option("--exclude-companies", "exclude_companies", default=None, callback=_csv, help="Companies to skip, comma-separated.")
@click.option("--exclude-keywords", "exclude_keywords", default=None, callback=_csv, help="Keywords that disqualify a posting, comma-separated.")
@click.option(
    "--set", "other", multiple=True, callback=_parse_set, metavar="KEY=VALUE",
    help="Any other profile/config.json key (JSON value, or a plain string); repeatable.",
)
def init(**flags):
    """Set The other door up: give your sources, check what they say, start searching.

    Without flags, a wizard. On a fresh clone it copies profile.example/ into
    profile/ and walks through every step; on an existing profile it asks
    which steps to redo. It asks a question outside the review only for what
    your sources do not say, and writes nothing before you save the review:

    \b
    0. Google Drive: connect it (a browser opens once) so profile/ and jobs/
       follow you across computers. If Drive already holds your data, the
       wizard offers to use it and stops there; otherwise the result of the
       wizard is pushed to Drive at the end.
    1. Your sources: your latest CV (PDF, DOCX, Markdown), a LinkedIn PDF
       export and public pages. A missing `claude` or sign-in interrupts here.
    2. Reading them (a few `claude -p` calls): the CV draft (nothing is
       invented, gaps are TODOs), your name, email, city and job-ad languages,
       job titles that fit your career, and the search terms for them.
    3. One review: every value, editable; which titles to look for; and which
       sites to find employers on, each off unless you tick it. Save writes
       profile/config.json and profile/cv.md (the old one is kept as cv.md.bak).
    4. A first run (search the boards, then score) starts right away.

    With flags, asks nothing: the given fields are merged over the current
    config (or the example one on a fresh clone) and written once they
    validate — the shell form of the `init_profile` tool. `--set KEY=VALUE`
    sets any other key. `--show` only prints what is configured (the
    `show_profile` tool) and writes nothing.
    """
    show = flags.pop("show")
    fields = _profile_fields(**flags)
    if show:
        if fields:
            raise click.UsageError("--show cannot be combined with field options.")
        _print_profile(_show_profile_core())
        return
    if fields:
        _write_fields(fields)
        return

    steps = list(_STEPS)
    existing = (workspace.PROFILE_DIR / "config.json").exists()
    if existing:
        steps = _prompts.checkbox(
            "steps",
            "profile/ already exists. What do you want to (re)do?",
            choices=[(label, key) for key, label in _STEPS.items()],
            default=[],
        )
        if not steps:
            click.echo("Nothing selected: profile/ left unchanged.")
            return

    pulled = "drive" in steps and _drive_step()
    if pulled:
        steps = []  # the data came from Google Drive: nothing left to ask
    if "sources" in steps or "review" in steps:
        answers = _answers_from(read_config_data(workspace.PROFILE_DIR / "config.json") if existing else None)
        if "sources" in steps:
            _read_sources_step(answers)
        _review_step(answers)
    if "run" in steps:
        _first_run_step()
    _drive_push()
    click.echo("Done. From now on, `./door find` fetches and scores what's new; `./door jobs` shows the matches.")


# The wizard's steps, in order: key -> what the "(re)do which?" list shows.
_STEPS = {
    "drive": "Google Drive (keep your data in step across computers)",
    "sources": "Your sources (read your CV and pages again: a new draft, titles and search terms)",
    "review": "Check your answers (your details, titles, search terms, where to find employers)",
    "run": "A first run",
}


def _drive_step() -> bool:
    """Offer to connect Google Drive; True when Drive's data was pulled in and the wizard is done.

    A failure only warns: the wizard goes on without Drive.
    """
    from door.commands import archive as archive_cmd
    from door.core import drive, sync

    if not drive.is_configured():
        click.echo("Google Drive sync is not configured in this build: skipping it.")
        return False
    state = drive.read_state()
    if state and state.get("refresh_token"):
        click.echo(f"Google Drive is already connected as {state.get('account') or 'your account'}.")
        return False
    if not _prompts.confirm(
        "drive", "Keep profile/ and jobs/ in step across your computers through your Google Drive? (a browser opens once)",
        default=True,
    ):
        return False
    try:
        account = archive_cmd._connect_core()["account"]
        click.echo(f"Connected to Google Drive as {account}.")
        meta = drive.remote_meta()
    except drive.DriveError as exc:
        click.echo(f"Google Drive not connected: {exc}", err=True)
        return False
    if meta is None:
        return False
    if (workspace.PROFILE_DIR / "config.json").exists():
        click.echo("Google Drive already holds The other door data; run `./door data sync` to bring the two together.")
        return False
    if not _prompts.confirm("drive_pull", "Your Google Drive already holds The other door data. Use it on this computer?", default=True):
        click.echo("Drive's data was left alone; `./door data sync` brings the two together later.")
        return False
    try:
        result = sync.pull()
    except drive.DriveError as exc:
        click.echo(f"Couldn't get your data from Google Drive: {exc}", err=True)
        return False
    click.echo(f"Imported {result['files']} files from Google Drive.")
    for warning in result["warnings"]:
        click.echo(f"Warning: {warning}", err=True)
    return True


def _drive_push() -> None:
    """At the wizard's end, put what it wrote on Drive (its writes may not take the ledger lock)."""
    from door.commands import archive as archive_cmd
    from door.core import drive
    from door.core.lock import SyncConflict

    if drive.read_state() is None:
        return
    try:
        archive_cmd._sync_core()
    except (drive.DriveError, SyncConflict) as exc:
        click.echo(f"Google Drive sync skipped: {exc}", err=True)


def _write_fields(fields: dict) -> dict:
    """`_init_core` for the CLI: one error line per invalid field, exit 1."""
    try:
        result = _init_core(fields, profile_dir=workspace.PROFILE_DIR, example_dir=workspace.PROFILE_EXAMPLE_DIR)
    except ConfigError as exc:
        for line in exc.lines:
            click.echo(f"Error: invalid profile: {line}", err=True)
        sys.exit(1)
    _echo_written(result)
    return result


def _echo_written(result: dict, *, disclaimers: bool = True) -> None:
    """`_init_core`'s result in words: the keys it dropped, then the file written, then the disclaimer of each
    source it turned on (the wizard's question already showed them: ``disclaimers=False``)."""
    from door.commands import _common as common

    if result["dropped"]:
        click.echo(f"Removed from profile/config.json, as it was not valid: {', '.join(result['dropped'])}", err=True)
    click.echo(f"Wrote {common._display_path(result['config_path'])}.")
    for item in result["disclaimers"] if disclaimers else []:
        click.echo(item["text"])


def _save_cv_core(markdown: str) -> dict:
    """Put `markdown` in place as profile/cv.md (the previous one kept as cv.md.bak) and drop the
    scratch profile/cv.draft.md. The shell twin is `init`'s CV step; the app's wizard calls it
    through the `save_cv` tool once the user has reviewed the text. Empty text is refused."""
    from door.commands import _common as common

    if not isinstance(markdown, str) or not markdown.strip():
        return {"error": "the CV is empty; nothing was written"}
    profile_dir = Path(workspace.PROFILE_DIR)
    profile_dir.mkdir(parents=True, exist_ok=True)
    cv_path = profile_dir / "cv.md"
    backup = common._write_with_backup(cv_path, markdown)
    (profile_dir / "cv.draft.md").unlink(missing_ok=True)
    return {"cv_path": str(cv_path), "backup": str(backup) if backup else None}


def _photo_value(path: Path) -> str:
    """The `photo` key's value for ``path``: relative to the data folder when it lies in it (as the templates'
    are), else whole."""
    try:
        return path.relative_to(workspace.HOME).as_posix()
    except ValueError:
        return str(path)


def _save_photo_core(path: str) -> dict:
    """Keep the picture at ``path`` as the CV photo: `door.core.photo.save` checks it (JPEG or PNG, size) and
    writes the cleaned copy (no EXIF or GPS, scaled to CV size) as profile/photo.jpg, and the `photo` key
    names it. The shell twin is `init`'s photo question; the app and `/onboard` call the `save_photo` tool.
    Nothing changes when the picture is refused.

    Returns:
        ``{"photo_path"}``, or ``{"error": <why it was refused>}``.
    """
    from door.core import photo as photo_mod

    try:
        kept = photo_mod.save(Path(path).expanduser(), workspace.PROFILE_DIR)
    except photo_mod.PhotoError as exc:
        return {"error": str(exc)}
    try:
        _init_core({"photo": _photo_value(kept)}, profile_dir=workspace.PROFILE_DIR, example_dir=workspace.PROFILE_EXAMPLE_DIR)
    except ConfigError as exc:
        kept.unlink(missing_ok=True)
        return {"error": "; ".join(exc.lines)}
    return {"photo_path": str(kept)}


def _remove_photo_core() -> dict:
    """Delete profile/photo.jpg and clear the `photo` key. ``{"removed": bool}`` (False: there was none)."""
    from door.core import photo as photo_mod

    kept = Path(workspace.PROFILE_DIR) / photo_mod.NAME
    existed = kept.is_file()
    kept.unlink(missing_ok=True)
    config_path = Path(workspace.PROFILE_DIR) / "config.json"
    if config_path.is_file() and read_config_data(config_path).get("photo") is not None:
        existed = True
        _init_core({"photo": None}, profile_dir=workspace.PROFILE_DIR, example_dir=workspace.PROFILE_EXAMPLE_DIR)
    return {"removed": existed}


def _answers_from(config: dict | None) -> dict:
    """What the wizard holds until Save: a saved profile's values, or nothing on a fresh home, where
    `fresh` also makes Save clear the example's exclusions."""
    config = config or {}
    keys = ("name", "email", "location", "languages", "role_targets", "search_keywords", "topic_terms", "enrich_sources")
    return {
        **{key: config[key] for key in keys if config.get(key)},
        "remote": config.get("remote") or "hybrid",
        "discovery": {s["key"] for s in discovery_sources.for_location(config.get("location") or "") if config.get(s["key"])},
        "titles": [{"title": t, "reason": "In your profile", "recommended": True} for t in config.get("role_targets") or []],
        "fresh": not config,
        "has_photo": bool(config.get("photo")),
    }


def _sign_in(claude_path: str) -> None:
    """`claude auth login`, on this terminal (a browser opens)."""
    from door.core import claude_cli

    subprocess.run([claude_path, "auth", "login"], env=claude_cli.env(profile_dir=workspace.PROFILE_DIR), check=False)


def _prereq_step() -> None:
    """Interrupt only for a missing `claude` or sign-in. Declining never stops the wizard: what
    reading the sources cannot do without Claude is asked instead."""
    from door.commands import setup as setup_cmd
    from door.core import claude_cli, doctor, installers

    if doctor.check_claude_cli()["status"] != "ok":
        if not _prompts.confirm("claude_install", "The other door reads your CV with Claude Code, which is not installed. Install it now?", default=True):
            return
        setup_cmd._setup_core(install=["claude"], yes=True, interactive=True)
    path = installers.find_claude()
    if not path:
        click.echo("Claude Code is still not installed: I'll ask what it would have read.", err=True)
        return
    login = doctor.check_claude_login(path, env=claude_cli.env(profile_dir=workspace.PROFILE_DIR))
    if login["status"] == "missing" and _prompts.confirm(
        "claude_login", "You are not signed in to Claude (your Pro or Max plan). Sign in now? (a browser opens)", default=True,
    ):
        _sign_in(path)
        login = doctor.check_claude_login(path, env=claude_cli.env(profile_dir=workspace.PROFILE_DIR))
    if login["status"] == "missing":
        click.echo(f"Not signed in to Claude ({login['fix']}): I'll ask what it would have read.", err=True)


def _draft_from_sources(answers: dict) -> None:
    """Ask for the sources and draft the CV; a bad source asks again, nothing given skips the draft."""
    from door.commands import _common as common
    from door.commands import cv as cv_cmd
    from door.core import claude_cli

    checked = False
    while True:
        sources = _split(_prompts.text(
            "cv_sources",
            "Your sources (comma-separated: your latest CV file — PDF, DOCX or Markdown —, "
            "a LinkedIn \"Save to PDF\" export, your website, GitHub, anything else public; empty to skip)",
            default="",
        ))
        if not checked:
            _prereq_step()
            checked = True
        if not sources:
            click.echo("No sources: profile/cv.md left as it is.")
            return
        click.echo("[1/4] Drafting your CV (a minute or two)...")
        try:
            result = cv_cmd._draft_cv_core(sources, profile_dir=workspace.PROFILE_DIR)
            break
        except (ValueError, FileNotFoundError, claude_cli.ClaudeError) as exc:
            click.echo(f"Error: {exc}", err=True)
    answers.update(draft_path=result["draft_path"], provenance=result["provenance"], todos=result["todos"])
    urls = [s for s in sources if common._is_url(s) and not re.match(r"https?://([^/]+\.)?linkedin\.", s, re.IGNORECASE)]
    if urls:
        # Kept so `enrich` (/expand) can read them again later.
        answers["enrich_sources"] = list(dict.fromkeys([*answers.get("enrich_sources", []), *urls]))


def _ask_location(answers: dict, unsupported: str | None = None) -> None:
    """Pick a known city, or type another one under "Other…"."""
    current = answers.get("location") or unsupported or ""
    if unsupported:
        click.echo(f"Your CV says {unsupported}, which The other door doesn't cover yet.")
    city_choices = [(f"{city} ({country})", city) for city, country in i18n.known_cities()]
    location = _prompts.select(
        "location",
        "Which city should the search be around?",
        choices=[*city_choices, (OTHER_LOCATION, OTHER_LOCATION)],
        default=_location_default(current),
    )
    if location == OTHER_LOCATION:
        location = _prompts.text("location_other", "City", default=current)
    answers["location"] = location


def _ask_titles(answers: dict) -> None:
    """No suggestions to pick from: the titles in the user's own words."""
    answers["role_targets"] = _split(_prompts.text(
        "role_targets", "Job titles to look for (comma-separated)", default=", ".join(answers.get("role_targets", [])),
        validate=lambda raw: None if _split(raw) else "Name at least one title.",
    ))
    answers["titles"] = [{"title": t, "reason": "You named this title", "recommended": True} for t in answers["role_targets"]]


def _propose_terms(answers: dict) -> None:
    """The search and title terms for the titles; a failed call leaves the titles themselves as the terms."""
    from door.commands import keywords as keywords_cmd
    from door.core import claude_cli

    try:
        proposal = keywords_cmd._keywords_core(answers["role_targets"], languages=answers["languages"], profile_dir=workspace.PROFILE_DIR)
    except (ValueError, claude_cli.ClaudeError) as exc:
        click.echo(f"Couldn't propose search terms: {exc}. Your titles are searched as they are.", err=True)
        answers.update(search_keywords=list(answers["role_targets"]), topic_terms=[])
        return
    answers.update(search_keywords=proposal["keywords"], topic_terms=proposal.get("topic_terms") or [])


def _read_sources_step(answers: dict) -> None:
    """Everything the sources can tell, then one question per thing they could not."""
    from door.commands import cv as cv_cmd
    from door.commands import titles as titles_cmd

    _draft_from_sources(answers)
    click.echo("[2/4] Reading your details...")
    basics = cv_cmd._infer_basics_core(profile_dir=workspace.PROFILE_DIR)
    if basics.get("warning"):
        click.echo(f"Couldn't read everything: {basics['warning']}", err=True)
    for key in ("name", "email", "location", "languages"):
        answers[key] = answers.get(key) or basics[key]
    answers["remote"] = answers.get("remote") or basics["remote"]
    if not answers.get("name"):
        answers["name"] = _prompts.text("name", "Your name", default="")
    if not answers.get("email"):
        answers["email"] = _prompts.text("email", "Your email", default="")
    if not answers.get("location"):
        _ask_location(answers, basics.get("unsupported_location"))

    click.echo("[3/4] Finding job titles that fit...")
    suggested = titles_cmd._titles_core(answers.get("role_targets"), languages=answers["languages"], profile_dir=workspace.PROFILE_DIR)
    if suggested.get("warning"):
        click.echo(f"No titles suggested: {suggested['warning']}", err=True)
    answers["titles"] = suggested["titles"]
    answers["role_targets"] = [t["title"] for t in suggested["titles"] if t["recommended"]]
    if not answers["role_targets"]:
        _ask_titles(answers)

    click.echo("[4/4] Choosing search terms...")
    _propose_terms(answers)
    _first_look(answers)


def _first_look(answers: dict) -> None:
    """A few scored ads while the wizard finishes: one friendly line when there are none, never a stop."""
    from door.commands import cv as cv_cmd
    from door.commands import preview as preview_cmd

    click.echo("A first look while we finish setting up...")
    config = {key: answers.get(key) for key in ("location", "languages", "role_targets", "search_keywords", "topic_terms", "remote")}
    look = preview_cmd._preview_core(config, cv_cmd._onboarding_cv_text(workspace.PROFILE_DIR, {}))
    for match in look["matches"]:
        click.echo(f"  {match['title']} at {match['company']}: {match['score_reason']}")
    if look.get("warning"):
        click.echo(f"  {look['warning']}")


def _pick_titles(answers: dict) -> None:
    """The titles with their reasons, plus the user's own; a change proposes the search terms again."""
    before = set(answers.get("role_targets", []))
    choices = [(f"{t['title']}: {t['reason']}", t["title"]) for t in answers.get("titles", [])]
    picked = _prompts.checkbox("titles_pick", "Job titles to look for", choices=choices, default=list(answers.get("role_targets", [])))
    added = _split(_prompts.text("titles_add", "Add your own (comma-separated, optional)", default=""))
    chosen = list(dict.fromkeys([*picked, *added]))
    known = {t["title"] for t in answers.get("titles", [])}
    answers["titles"] = [*answers.get("titles", []), *({"title": t, "reason": "You named this title", "recommended": True} for t in chosen if t not in known)]
    answers["role_targets"] = chosen
    if chosen and set(chosen) != before:
        click.echo("Choosing search terms for those titles...")
        _propose_terms(answers)


def _pick_discovery(answers: dict) -> None:
    """Each source serving the city is the user's call, off unless ticked; the question carries each one's
    disclaimer (`door.core.disclaimer`)."""
    sources = discovery_sources.for_location(answers.get("location") or "")
    if not sources:
        return
    answers["discovery"] = set(_prompts.checkbox(
        "discovery_pick",
        "Find employers on these sites too? Each stays off unless you tick it.\n"
        + "\n".join(f"  {s['disclaimer']}" for s in sources),
        choices=[(s["label"], s["key"]) for s in sources],
        default=[s["key"] for s in sources if s["key"] in answers["discovery"]],
    ))


def _photo_problem(value: str) -> str | None:
    """Why the answer to the photo question is not a usable picture (the prompt's check); None when it is one
    or empty (a skip)."""
    from door.core import photo as photo_mod

    value = (value or "").strip()
    return photo_mod.problem(Path(value).expanduser()) if value else None


def _pick_photo(answers: dict) -> None:
    """Ask once for a CV photo, where the city's country has it optional or expected and the profile has none; Enter skips."""
    if i18n.cv_conventions_for_location(answers.get("location") or "").photo == "no" or answers.get("has_photo"):
        return
    answers["photo"] = _prompts.text(
        "photo", "A photo for your CV? Give the path of a JPEG or PNG (Enter to skip; `./door init` asks again, and the app's Profile screen takes one too)",
        default="", validate=_photo_problem,
    ).strip()


def _pick_terms(answers: dict, key: str, label: str) -> None:
    current = answers.get(key, [])
    picked = _prompts.checkbox(f"{key}_pick", label, choices=[(term, term) for term in current], default=current)
    added = _split(_prompts.text(f"{key}_add", "Add your own (comma-separated, optional)", default=""))
    answers[key] = list(dict.fromkeys([*picked, *added]))


def _edit(choice: str, answers: dict) -> None:
    """What the review's pick list does for each value."""
    if choice == "name":
        answers["name"] = _prompts.text("name", "Your name", default=answers.get("name", ""))
    elif choice == "email":
        answers["email"] = _prompts.text("email", "Your email", default=answers.get("email", ""))
    elif choice == "location":
        _ask_location(answers)
        _pick_discovery(answers)
    elif choice == "remote":
        answers["remote"] = _prompts.select(
            "remote", "Remote work", choices=[("Hybrid", "hybrid"), ("Remote", "yes"), ("On site", "no")], default=answers["remote"],
        )
    elif choice == "languages":
        language_names = i18n.supported_language_names().split(", ")
        answers["languages"] = _prompts.checkbox(
            "languages",
            "Job ad languages to consider",
            choices=[(name, name) for name in language_names],
            default=[_language_name(lang) for lang in answers.get("languages") or ["English"]],
            validate=_need_one("language"),
        )
    elif choice == "titles":
        _pick_titles(answers)
    elif choice == "search_keywords":
        _pick_terms(answers, "search_keywords", "Search terms to use")
    elif choice == "topic_terms":
        _pick_terms(answers, "topic_terms", "Words that make a job title relevant to you")
    elif choice == "discovery":
        _pick_discovery(answers)
    elif choice == "photo":
        answers["has_photo"] = False
        _pick_photo(answers)
    elif choice == "cv":
        click.edit(filename=answers["draft_path"])


def _print_review(answers: dict) -> None:
    from door.commands import _common as common

    location = answers.get("location") or ""
    country = i18n.country_for_location(location)
    sources = discovery_sources.for_location(location)
    click.echo("")
    for label, value in (
        ("Name", answers.get("name")),
        ("Email", answers.get("email")),
        ("City", location),
        ("Remote", answers.get("remote")),
        ("Languages", ", ".join(answers.get("languages") or [])),
        ("Titles", ", ".join(answers.get("role_targets") or [])),
        ("Search terms", ", ".join(answers.get("search_keywords") or [])),
        ("Title terms", ", ".join(answers.get("topic_terms") or [])),
        *([("Photo", Path(answers["photo"]).name)] if answers.get("photo") else []),
    ):
        click.echo(f"  {label:<14}{value or ''}")
    if sources:
        picked = [s["label"] for s in sources if s["key"] in answers["discovery"]]
        click.echo(f"  {'Employers on':<14}{', '.join(picked) or 'none'}")
    click.echo(f"  {'Job boards':<14}{', '.join(sites.boards_for_location(location))}{f' (every board in {country.name})' if country else ''}")
    if location and country is None:
        click.echo(
            f"  Note: {location} isn't in a supported country yet, so only the worldwide boards are searched. "
            "To add the country and its job sites, see docs/adding-a-site.md."
        )
    if answers.get("draft_path"):
        click.echo(f"  {'CV draft':<14}{common._display_path(answers['draft_path'])}")
        for item in answers.get("provenance", []):
            click.echo(f"    {item.get('source', '')}: {item.get('contributed', '')}")
        for todo in answers.get("todos", []):
            click.echo(f"    TODO: {todo}")
    click.echo("")


def _save_answers(answers: dict) -> bool:
    """`init_profile` then `save_cv`: every answer, so nothing of the example config survives a fresh home.
    An invalid answer writes nothing and goes back to the review."""
    from door.commands import _common as common

    sources = discovery_sources.for_location(answers.get("location") or "")
    fields = {
        "name": answers.get("name", ""),
        "email": answers.get("email", ""),
        "location": answers.get("location", ""),
        "languages": answers.get("languages") or ["English"],
        "role_targets": answers.get("role_targets", []),
        "search_keywords": answers.get("search_keywords") or answers.get("role_targets", []),
        "topic_terms": answers.get("topic_terms", []),
        "remote": answers["remote"],
        **{s["key"]: s["key"] in answers["discovery"] for s in sources},
    }
    if answers.get("enrich_sources"):
        fields["enrich_sources"] = answers["enrich_sources"]
    if answers["fresh"]:
        fields["exclude"] = {"companies": [], "keywords": []}
    try:
        result = _init_core(fields, profile_dir=workspace.PROFILE_DIR, example_dir=workspace.PROFILE_EXAMPLE_DIR)
    except ConfigError as exc:
        for line in exc.lines:
            click.echo(f"Error: invalid profile: {line}", err=True)
        return False
    _echo_written(result, disclaimers=False)
    if answers.get("draft_path"):
        saved = _save_cv_core(Path(answers["draft_path"]).read_text(encoding="utf-8"))
        if "error" in saved:
            click.echo(f"Error: {saved['error']}", err=True)
            return False
        kept = f" (previous version: {common._display_path(Path(saved['backup']))})" if saved["backup"] else ""
        click.echo(f"Wrote {common._display_path(Path(saved['cv_path']))}{kept}.")
    if answers.get("photo"):
        saved = _save_photo_core(answers["photo"])
        if "error" in saved:
            click.echo(f"Error: {saved['error']}", err=True)
            answers.pop("photo")  # the rest is saved; back at the review the photo can be asked again
            answers["has_photo"] = False
            return False
        click.echo(f"Wrote {common._display_path(Path(saved['photo_path']))}.")
    return True


def _review_step(answers: dict) -> None:
    """One review: pick the titles and the employer sites, see everything, change anything, then Save."""
    _pick_titles(answers)
    _pick_discovery(answers)
    _pick_photo(answers)
    while True:
        _print_review(answers)
        choices = [
            ("Yes: save, and start searching", "save"),
            ("Change your name", "name"),
            ("Change your email", "email"),
            ("Change your city", "location"),
            ("Change remote work", "remote"),
            ("Change the job ad languages", "languages"),
            ("Change the titles", "titles"),
            ("Change the search terms", "search_keywords"),
            ("Change the title terms", "topic_terms"),
            ("Change where to find employers", "discovery"),
            *([("Change the photo", "photo")] if i18n.cv_conventions_for_location(answers.get("location") or "").photo != "no" else []),
            *([("Open the CV draft in my editor", "cv")] if answers.get("draft_path") else []),
        ]
        choice = _prompts.select("review", "Does this look right?", choices=choices, default="save")
        if choice != "save":
            _edit(choice, answers)
        elif _save_answers(answers):
            return


def _first_run_step() -> None:
    """A first `find` (search the boards and score, no discovery or feeds), once profile/cv.md is no
    longer the example."""
    from door.commands import find as find_cmd

    cv_path = workspace.PROFILE_DIR / "cv.md"
    example_cv = workspace.PROFILE_EXAMPLE_DIR / "cv.md"
    if not cv_path.exists() or (example_cv.exists() and cv_path.read_text() == example_cv.read_text()):
        click.echo("No first run: profile/cv.md is still the example. Give your sources (`./door init`), then `./door find`.")
        return
    click.get_current_context().invoke(
        find_cmd.find, skip=["discover", "follow", "collect"], boards=None,
    )


def _init_core(fields: dict, profile_dir: Path | None = None, example_dir: Path | None = None) -> dict:
    """The non-interactive half of `init`: copy, merge, validate, write.

    Copies any missing `example_dir` file into `profile_dir` (never
    overwriting), merges `fields` over the existing config (or the example
    one on a fresh clone), validates against `Profile` and only then writes
    `profile_dir/config.json`. The Click `init` collects `fields` by
    prompting; the `init_profile` tool takes them as arguments. Never prints.

    The existing config's keys that fail validation and are not in `fields`
    are dropped, so an invalid config.json can always be saved over (the
    app's wizard, which opens on one, does not show every key).

    Returns:
        ``{"config_path", "copied": [relative path, ...], "dropped": [key, ...], "disclaimers":
        [{"key", "text"}, ...]}``: one disclaimer for each discovery source this call turns on (it was
        not on before); the caller shows each to the user.

    Raises:
        ConfigError: the merged config fails validation (nothing written).
    """
    from pydantic import ValidationError

    from door.core.profile_loader import Profile, format_validation_error

    if profile_dir is None:
        profile_dir = workspace.PROFILE_DIR
    if example_dir is None:
        example_dir = workspace.PROFILE_EXAMPLE_DIR

    copied = _copy_missing_example_files(example_dir, profile_dir)
    base = _load_base_config(profile_dir, example_dir)
    dropped = sorted(_invalid_keys(base) - fields.keys())
    base = {key: value for key, value in base.items() if key not in dropped}
    merged = {**base, **fields}
    # `exclude` is merged key by key, so setting only `companies` keeps
    # the existing `keywords`.
    if isinstance(fields.get("exclude"), dict) and isinstance(base.get("exclude"), dict):
        merged["exclude"] = {**base["exclude"], **fields["exclude"]}

    try:
        Profile.model_validate(merged)
    except ValidationError as exc:
        raise ConfigError(format_validation_error(exc, "profile/config.json")) from None

    config_path = profile_dir / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(merged, indent=2))
    disclaimers = [
        {"key": s["key"], "text": s["disclaimer"]}
        for s in map(discovery_sources.info, discovery_sources.SOURCES)
        if fields.get(s["key"]) is True and base.get(s["key"]) is not True
    ]
    return {"config_path": str(config_path), "copied": copied, "dropped": dropped, "disclaimers": disclaimers}


def _invalid_keys(config: dict) -> set[str]:
    """The top-level keys of `config` that `Profile` refuses: an unknown key, a bad value."""
    from pydantic import ValidationError

    from door.core.profile_loader import Profile

    try:
        Profile.model_validate(config)
    except ValidationError as exc:
        return {str(err["loc"][0]) for err in exc.errors() if err["loc"] and str(err["loc"][0]) in config}
    return set()


_DEFAULT_FILES = {"cv_content": "cv.md", "cv_template": "cv.template.tex", "cover_letter_template": "cover-letter.template.tex"}


def _parse_cv(text: str) -> dict:
    """The outline of a CV in Markdown: the first `# ` line as `headline`, each `## ` section with its
    `###` roles and its bullet count (role bullets included)."""
    headline = None
    sections: list[dict] = []
    for line in text.splitlines():
        if re.match(r"#\s+", line):
            headline = headline or line.lstrip("#").strip()
        elif re.match(r"##\s+", line):
            sections.append({"title": line.lstrip("#").strip(), "roles": [], "bullets": 0})
        elif re.match(r"###\s+", line):
            if sections:
                sections[-1]["roles"].append(line.lstrip("#").strip())
        elif re.match(r"\s*[-*]\s+", line) and sections:
            sections[-1]["bullets"] += 1
    return {"headline": headline, "sections": sections}


def _file_state(path: Path, example: Path) -> dict:
    """`{path, exists, is_example}`: `is_example` when the bytes equal the same-named file of profile.example/."""
    try:
        exists = path.is_file()
        is_example = exists and example.is_file() and path.read_bytes() == example.read_bytes()
    except OSError:
        exists, is_example = path.exists(), False
    return {"path": str(path), "exists": exists, "is_example": bool(is_example)}


def _profile_field_specs() -> list[dict]:
    """Every `Profile` key in order, for a form: its type (string, path, choice, boolean, integer, number,
    list, exclude), whether it is required or may be null, its default, its bounds and its choices,
    read from the model so a form never copies them."""
    schema = profile_loader.Profile.model_json_schema()
    required = set(schema.get("required", []))
    specs = []
    for key, prop in schema["properties"].items():
        options = prop.get("anyOf", [prop])
        nullable = any(o.get("type") == "null" for o in options)
        value = next((o for o in options if o.get("type") != "null"), prop)
        if "$ref" in value:
            kind = "exclude"
        elif "enum" in value:
            kind = "choice"
        elif value.get("format") == "path":
            kind = "path"
        else:
            kind = {"array": "list"}.get(value.get("type"), value.get("type", "string"))
        spec = {"key": key, "type": kind, "required": key in required, "nullable": nullable}
        if key not in required:
            spec["default"] = prop.get("default")
        for bound, name in (("minimum", "min"), ("maximum", "max")):
            if bound in value:
                spec[name] = value[bound]
        if "enum" in value:
            spec["choices"] = list(value["enum"])
        specs.append(spec)
    return specs


def _discovery_choices(sources: list[dict]) -> list[dict]:
    return [{k: s[k] for k in ("key", "label", "verdict", "terms_url", "terms_summary", "disclaimer")} for s in sources]


def _profile_options(location: str | None = None) -> dict:
    """What the profile form can offer, live from `i18n` and the site registry: the known cities
    (with their country and the boards `search` reads there), the supported job-ad languages and the
    boards that work anywhere, and every offered board's name in words."""
    countries = {c.name: c.code.lower() for c in i18n.countries().values()}
    cities = [
        {"name": name, "country": country, "boards": sites.boards_for_country(countries.get(country)),
         "discovery": _discovery_choices(discovery_sources.for_location(name)),
         # How a CV is written in the city's country: the photo question is asked only where it is optional or expected.
         "cv": i18n.cv_conventions_for_location(name).model_dump()}
        for name, country in i18n.known_cities()
        if location is None or name.casefold() == location.strip().casefold()
    ]
    codes = sorted(i18n.languages(), key=lambda c: (c != "en", c))
    worldwide = sites.boards_for_country(None)
    offered = {b for c in cities for b in c["boards"]} | set(worldwide)
    return {
        "cities": cities,
        "languages": [i18n.languages()[c].name for c in codes],
        "worldwide_boards": worldwide,
        # The discovery sources onboarding asks about for a city in no known country.
        "worldwide_discovery": _discovery_choices(discovery_sources.for_location("")),
        # Each board in words ("The Hub"), the name the posting pane uses ("via The Hub").
        "board_names": {b: sites.source_name(b) or b for b in sorted(offered)},
        # Every config key with its type, default and bounds (the Profile screen's form).
        "fields": _profile_field_specs(),
    }


def _photo_state(config: dict | None) -> dict:
    """``{"exists": False}``, or ``{"exists": True, "path"}`` of the photo the config names."""
    path = (config or {}).get("photo")
    if path and Path(path).is_file():
        return {"exists": True, "path": str(path)}
    return {"exists": False}


def _show_profile_core(profile_dir: Path | None = None, example_dir: Path | None = None, location: str | None = None) -> dict:
    """What is configured, for a settings screen: the validated config (or the error lines), the CV with its
    outline, the templates and story bank, each marked `is_example` when still profile.example/'s file.
    Read-only; an invalid or missing config is a result (`config` None, `errors`), never an exception.
    With *location*, `options.cities` holds only that city (by name, any case; none for a city it does not know):
    every city is tens of kilobytes, too much for a conversation that asks about one."""
    profile_dir = Path(profile_dir or workspace.PROFILE_DIR)
    example_dir = Path(example_dir or workspace.PROFILE_EXAMPLE_DIR)
    config, errors = None, []
    try:
        config = load_config(profile_dir / "config.json")
    except FileNotFoundError:
        errors = [f"{profile_dir / 'config.json'} not found"]
    except ConfigError as exc:
        errors = list(exc.lines)

    def locate(key: str) -> Path:
        return Path(config[key]) if config and config.get(key) else profile_dir / _DEFAULT_FILES[key]

    cv_path = locate("cv_content")
    cv = _file_state(cv_path, example_dir / cv_path.name)
    text = None
    if cv["exists"]:
        try:
            text = cv_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = None
    cv.update(text=text, **_parse_cv(text or ""))
    templates = {}
    for name, key in (("cv", "cv_template"), ("cover_letter", "cover_letter_template")):
        path = locate(key)
        templates[name] = _file_state(path, example_dir / path.name)
    return {
        "path": str(profile_dir),
        "options": _profile_options(location),
        "config": config,
        "errors": errors,
        "cv": cv,
        "templates": templates,
        "story_bank": _file_state(profile_dir / "story_bank.md", example_dir / "story_bank.md"),
        "enrich_sources": list((config or {}).get("enrich_sources") or []),
        "photo": _photo_state(config),
        # The discovery sources serving the profile's city that were never chosen, so do not run.
        "discovery_unchosen": _discovery_choices(discovery_sources.unchosen(config)) if config else [],
    }


def _print_profile(result: dict) -> None:
    from door.commands import _common as common

    click.echo(f"Profile: {common._display_path(result['path'])}")
    if result["errors"]:
        click.echo("config.json is not valid:")
        for line in result["errors"]:
            click.echo(f"  {line}")
    else:
        config = result["config"]
        for key in ("name", "email", "location", "languages", "role_targets", "search_keywords", "remote", "min_score"):
            if config.get(key) not in (None, "", []):
                value = ", ".join(map(str, config[key])) if isinstance(config[key], list) else config[key]
                click.echo(f"  {key:<16}{value}")
        if result["enrich_sources"]:
            click.echo(f"  {'enrich_sources':<16}{', '.join(result['enrich_sources'])}")

    def line(label: str, state: dict) -> None:
        mark = "missing" if not state["exists"] else ("still the example" if state["is_example"] else "yours")
        click.echo(f"  {label:<16}{common._display_path(state['path'])} ({mark})")

    click.echo("Files:")
    cv = result["cv"]
    line("CV", cv)
    if cv["headline"]:
        click.echo(f"    {cv['headline']}")
    for section in cv["sections"]:
        roles = f", {len(section['roles'])} roles" if section["roles"] else ""
        click.echo(f"    {section['title']} ({section['bullets']} bullets{roles})")
    line("CV template", result["templates"]["cv"])
    line("Cover letter", result["templates"]["cover_letter"])
    line("Story bank", result["story_bank"])
