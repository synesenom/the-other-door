"""Drafting `profile/cv.md`: turn an existing CV (PDF, DOCX, Markdown or text) and public pages
into a `profile/cv.md` draft.

Local files are read here (pypdfium2 for PDF, the document XML for DOCX); one
`claude -p` call reads the URLs with WebFetch and writes the Markdown in the
structure of profile.example/cv.md. `/onboard`'s CV step (the `draft_cv` tool)
and `init`'s CV step in a shell make the same call; the draft is shown before anything replaces
profile/cv.md.
"""

import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import click

from door import i18n
from door.commands import _common as common
from door.core import claude_cli, workspace

_DEFAULT_MODEL = "sonnet"
_DRAFT_NAME = "cv.draft.md"
_TEXT_SUFFIXES = {".md", ".markdown", ".txt"}

_RULES = (
    "You draft a job seeker's CV as Markdown from the sources you are given: the text of "
    "their files (their most recent CV, a LinkedIn PDF export, notes) and public URLs. "
    + common._WEBFETCH_RULES + "\n\n"
    "Write one CV in the structure of the template you are given (its sections, "
    "`### Role | Company — dates` headings, bullets). The most recent CV is the backbone; "
    "the other sources only add to it — month-level dates, roles it leaves out, years and "
    "venues of publications, named projects, a portfolio link. Use only what the sources say; "
    "never invent content — write `TODO` for anything missing (phone, education dates) "
    "and list those under `todos`. Fill the template's Skills section with the skills the sources "
    "show, also those that appear only in job descriptions; if they show none, leave the section "
    "out: never a `TODO` for skills. Under `provenance`, say what each source besides the "
    "backbone contributed. Answer with the JSON only."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "cv_markdown": {"type": "string"},
        "provenance": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"source": {"type": "string"}, "contributed": {"type": "string"}},
                "required": ["source", "contributed"],
            },
        },
        "todos": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["cv_markdown", "provenance", "todos"],
}

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _extract_text(path: Path) -> str:
    """The text of a PDF (pypdfium2), a DOCX (its paragraphs) or a Markdown/text file.

    Raises:
        FileNotFoundError: no such file.
        ValueError: another file type.
    """
    suffix = path.suffix.lower()
    if suffix not in {".pdf", ".docx", *_TEXT_SUFFIXES}:
        raise ValueError(f"{path}: a CV source must be a PDF, DOCX, Markdown or text file, or a URL")
    if not path.is_file():
        raise FileNotFoundError(f"{path}: no such file")
    if suffix == ".pdf":
        from door.tailoring import pdf_render

        return "\n".join(pdf_render.page_texts(path)).strip()
    if suffix == ".docx":
        with zipfile.ZipFile(path) as zf:
            root = ElementTree.fromstring(zf.read("word/document.xml"))
        paragraphs = ["".join(t.text or "" for t in p.iter(f"{_W}t")) for p in root.iter(f"{_W}p")]
        return "\n".join(p for p in paragraphs if p.strip()).strip()
    return path.read_text(encoding="utf-8").strip()


def _onboarding_cv_text(profile_dir: Path, config: dict) -> str | None:
    """The CV to read: `profile/cv.draft.md` while onboarding, else the profile's CV; `None` when there is
    neither, or the CV is still profile.example/'s. Before Save there is no config, so no `cv_content`."""
    draft = profile_dir / _DRAFT_NAME
    path = draft if draft.is_file() else Path(config.get("cv_content") or profile_dir / "cv.md")
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    example = workspace.PROFILE_EXAMPLE_DIR / "cv.md"
    if not text.strip() or (example.is_file() and text == example.read_text(encoding="utf-8")):
        return None
    return text.strip()


def _without_skills_todos(markdown: str, todos: list[str]) -> tuple[str, list[str]]:
    """A CV need not list its skills, so nothing asks for them: `TODO`s go from its skills sections
    with what the model listed about them, and a section with nothing else left goes too."""
    titles = i18n.cv_section("skills")
    sections: list[list[str]] = [[]]
    for line in markdown.splitlines():
        if line.startswith("## "):
            sections.append([])
        sections[-1].append(line)

    found = False
    kept: list[str] = []
    for section in sections:
        heading = section[0][3:].strip(" *:_").casefold() if section and section[0].startswith("## ") else None
        if heading not in titles or not any("TODO" in line for line in section):
            kept.extend(section)
            continue
        found = True
        body = [left for left in map(_skills_line_without_todo, section[1:]) if left is not None]
        if any(line.strip() for line in body):
            kept.extend([section[0], *body])
    if not found:
        return markdown, todos
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip() + "\n"
    return text, [t for t in todos if not any(title in t.casefold() for title in titles)]


def _skills_line_without_todo(line: str) -> str | None:
    """*line* with its `TODO` taken out, or None when only a label or a bullet is left of it."""
    if "TODO" not in line:
        return line
    left = re.sub(r"[,;]?\s*TODO\b[^,;]*", "", line).rstrip()
    return left if re.sub(r"^[\s*_-]*", "", left) and not left.rstrip("*_ ").endswith(":") else None


def _draft_cv_core(
    sources: list[str],
    *,
    write: bool = False,
    model: str | None = None,
    profile_dir: Path | None = None,
    timeout_s: float = 900,
) -> dict:
    """Draft `profile/cv.draft.md` from `sources` (file paths and URLs); with
    `write`, replace `profile/cv.md` with it instead (keeping `cv.md.bak`).

    Works before profile/config.json exists (`/onboard` drafts first): the
    profile's fields, when there are any, only seed the header.

    Returns:
        ``{"draft_path" | "cv_path" + "backup", "written", "sources":
        [{"source", "kind", "chars"?}], "provenance", "todos"}``.

    Raises:
        ValueError: no sources, or a file of another type.
        FileNotFoundError: a source file is missing.
        ConfigError: an invalid profile/config.json.
        claude_cli.ClaudeError: the `claude -p` call failed or answered
            something else.
    """
    if profile_dir is None:
        profile_dir = workspace.PROFILE_DIR
    sources = [s.strip() for s in sources or [] if s and s.strip()]
    if not sources:
        raise ValueError("no source to draft from: give a CV file (PDF, DOCX, Markdown) or a URL")
    config = common._load_config_or_defaults(profile_dir)

    described = []
    parts = []
    urls = []
    for source in sources:
        if common._is_url(source):
            described.append({"source": source, "kind": "url"})
            urls.append(source)
        else:
            text = _extract_text(Path(source))
            described.append({"source": source, "kind": "file", "chars": len(text)})
            parts.append(f"Source file {source}:\n<<<\n{text}\n>>>")

    template = workspace.PROFILE_EXAMPLE_DIR / "cv.md"
    header = {k: config.get(k) for k in ("name", "email", "location", "role_targets") if config.get(k)}
    prompt = (
        f"Template (profile.example/cv.md):\n<<<\n{template.read_text(encoding='utf-8')}\n>>>\n\n"
        + (f"Profile fields: {json.dumps(header)}\n\n" if header else "")
        + "\n\n".join(parts)
        + ("\n\nPages to read:\n" + "\n".join(urls) + "\n" if urls else "\n")
    )
    answer = claude_cli.ask(
        _RULES, prompt, model=model or _DEFAULT_MODEL, feature="draft_cv", schema=_SCHEMA, allowed_tools=("WebFetch",),
        timeout_s=timeout_s, profile_dir=profile_dir,
    )
    markdown = answer.get("cv_markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        raise claude_cli.ClaudeError("claude's answer has no `cv_markdown`")
    markdown = markdown.strip() + "\n"
    provenance = [p for p in answer.get("provenance") or [] if isinstance(p, dict)]
    todos = [str(t) for t in answer.get("todos") or []]
    markdown, todos = _without_skills_todos(markdown, todos)

    profile_dir.mkdir(parents=True, exist_ok=True)
    draft_path = profile_dir / _DRAFT_NAME
    result = {"written": write, "sources": described, "provenance": provenance, "todos": todos, "markdown": markdown}
    if write:
        cv_path = profile_dir / "cv.md"
        backup = common._write_with_backup(cv_path, markdown)
        if draft_path.exists():
            draft_path.unlink()
        result.update(cv_path=str(cv_path), backup=str(backup) if backup else None)
    else:
        draft_path.write_text(markdown, encoding="utf-8")
        result["draft_path"] = str(draft_path)
    return result


_BASICS_MODEL = "haiku"
_DEFAULT_REMOTE = "hybrid"
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_LOCATION_RE = re.compile(r"^\W*location\W+(.+)$", re.IGNORECASE)
# A level at which someone works in a language; a language at any other level stays out of `languages`.
_WORKING_LEVELS = {"native", "fluent", "working"}

_BASICS_RULES = (
    "You read a job seeker's CV and fill in what it says about them. `name`: their full name. `email`: their "
    "email address. `city`: the city they live in, from the contact details, else the city of their current "
    "job; null when the CV does not say. Never guess any of these: null when it is not there. `languages`: "
    "every spoken language the CV names, each with its `level`: `native`, `fluent` (or professional or "
    "business), `working`, `conversational` or `basic`. Answer with the JSON only."
)

_BASICS_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": ["string", "null"]},
        "email": {"type": ["string", "null"]},
        "city": {"type": ["string", "null"]},
        "languages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"language": {"type": "string"}, "level": {"type": "string"}},
                "required": ["language", "level"],
            },
        },
    },
    "required": ["name", "email", "city", "languages"],
}


def _usable(value) -> str | None:
    """`value` as text, or `None` when it is empty or still a `TODO` of the draft."""
    text = " ".join(str(value or "").split())
    return text if text and "TODO" not in text else None


def _header_name(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("# "):
            return _usable(line[2:])
    return None


def _header_location(text: str) -> str | None:
    """What the CV's `**Location:** …` part says (the template's header keeps its parts on one line, split by `|`)."""
    for part in re.split(r"[|\n]", text):
        match = _LOCATION_RE.match(part.strip())
        if match:
            return _usable(match.group(1).strip(" *"))
    return None


def _needs_the_model(text: str, name, email, location) -> bool:
    """Parsing leaves something to read: a basic it did not find, or a language besides English to judge."""
    if not (name and email and location):
        return True
    others = [word for code, pack in i18n.languages().items() if code != "en" for word in pack.names]
    return bool(i18n.compile_words(others).search(text))


def _working_languages(answered) -> list[str]:
    """English, plus each supported language the model reads at a working level, by its file's name."""
    packs = i18n.languages()
    codes = ["en"]
    for item in answered if isinstance(answered, list) else []:
        code = i18n.language_code(str(item.get("language") or "")) if isinstance(item, dict) else None
        if code and code not in codes and str(item.get("level") or "").lower() in _WORKING_LEVELS:
            codes.append(code)
    return [packs[c].name for c in codes]


def _infer_basics_core(
    markdown: str | None = None,
    *,
    model: str | None = None,
    profile_dir: Path | None = None,
    timeout_s: float = 120,
) -> dict:
    """Read the profile basics from the CV: `markdown`, else the draft or the CV on disk. The header is parsed; one
    `claude -p` call reads only what parsing leaves (a missing basic, a language besides English). Works before the
    profile exists, and a failed call never stops a flow: what it would have read is `missing`.

    Returns:
        ``{"name", "email", "location", "languages", "remote", "missing"}`` (`None` for what was not found;
        `missing` lists the keys to ask about, and is the only reason to ask), plus ``"unsupported_location"`` (a
        place outside the covered countries: ask) and ``"warning"`` (the model call failed).

    Raises:
        ConfigError: an invalid profile/config.json.
    """
    if profile_dir is None:
        profile_dir = workspace.PROFILE_DIR
    text = (markdown or "").strip() or _onboarding_cv_text(profile_dir, common._load_config_or_defaults(profile_dir))
    result = {"name": None, "email": None, "location": None, "languages": ["English"], "remote": _DEFAULT_REMOTE, "missing": []}
    if not text:
        return {**result, "missing": ["name", "email", "location"]}

    name = _header_name(text)
    found_email = _EMAIL_RE.search(text)
    email = found_email.group(0) if found_email else None
    place = _header_location(text)
    location = i18n.known_city(place) if place else None
    # A place naming a known country but no known city says too little to search; another place is one The other door does not cover.
    unsupported = place if place and not location and not i18n.country_for_location(place) else None

    if _needs_the_model(text, name, email, location or unsupported):
        try:
            answer = claude_cli.ask(
                _BASICS_RULES, f"CV:\n<<<\n{text}\n>>>\n", model=model or _BASICS_MODEL, feature="infer_basics", schema=_BASICS_SCHEMA,
                timeout_s=timeout_s, profile_dir=profile_dir,
            )
        except claude_cli.ClaudeError as exc:
            result["warning"] = str(exc)
        else:
            # What the model names must be in the CV: a name or an address is never made up.
            read_name, read_email = _usable(answer.get("name")), _usable(answer.get("email"))
            name = name or (read_name if read_name and read_name.lower() in text.lower() else None)
            email = email or (read_email if read_email and read_email in text and _EMAIL_RE.fullmatch(read_email) else None)
            city = _usable(answer.get("city"))
            if city and not (location or unsupported):
                location = i18n.known_city(city)
                unsupported = city if not location and not i18n.country_for_location(city) else None
            result["languages"] = _working_languages(answer.get("languages"))

    result.update(name=name, email=email, location=location)
    if unsupported:
        result["unsupported_location"] = unsupported
    result["missing"] = [key for key in ("name", "email", "location") if not result[key]]
    return result


@click.group("cv")
def cv_group():
    """Your CV over time: `cv enrich` adds what your public pages show, `cv gaps` plans what to learn, `cv titles` suggests titles to look for, `cv stories` keeps the story bank the tailor draws on."""
