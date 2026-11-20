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
from door.core import claude_cli, cv_read, cv_sections, migrations, profile_loader, utils, workspace
from door.render import pdf_draft

_DRAFT_NAME = "cv.draft.md"
_TEXT_SUFFIXES = {".md", ".markdown", ".txt"}


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
        "skills_headings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["cv_markdown", "provenance", "todos", "skills_headings"],
}

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _extract_text(path: Path) -> str:
    """The text of a PDF (`pdf_draft`: icon glyphs left out, level dots said, #266, #313), a DOCX (its paragraphs, symbol-font runs left out, #297) or a Markdown/text file.

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
        return pdf_draft.draft_text(path)
    if suffix == ".docx":
        return _docx_text(path)
    return _decode_text_file(path.read_bytes()).strip()


def _docx_text(path: Path) -> str:
    """A DOCX's paragraphs, leaving out its icons, which read back as a stray "(" or "*" (#297): a run of only
    private-use, control or pictographic characters, or one set in an icon or symbol font (`pdf_draft.icon_font`, as a PDF's) (its own
    font, else its character style's, else its paragraph style's or the default one's, each style through the
    ones it is based on)."""
    with zipfile.ZipFile(path) as zf:
        root = ElementTree.fromstring(zf.read("word/document.xml"))
        styles = ElementTree.fromstring(zf.read("word/styles.xml") if "word/styles.xml" in zf.namelist() else "<styles/>")
    based = {s.get(f"{_W}styleId"): (_font(s), _val(s, f"{_W}basedOn")) for s in styles.iter(f"{_W}style")}
    default = next((s.get(f"{_W}styleId") for s in styles.iter(f"{_W}style")
                    if s.get(f"{_W}type") == "paragraph" and s.get(f"{_W}default") in ("1", "true")), None)

    def styled(style_id: str | None) -> str | None:
        seen = set()
        while style_id in based and style_id not in seen:
            seen.add(style_id)
            font, style_id = based[style_id]
            if font:
                return font
        return None

    paragraphs = []
    for p in root.iter(f"{_W}p"):
        texts = []
        for run in p.iter(f"{_W}r"):
            text = "".join(t.text or "" for t in run.findall(f"{_W}t"))
            font = (_font(run) or styled(_val(run, f"{_W}rPr/{_W}rStyle"))
                    or styled(_val(p, f"{_W}pPr/{_W}pStyle") or default))
            if not (text and pdf_draft.glyph_only(text)) and not (font and pdf_draft.icon_font(font)):
                texts.append(text)
        paragraphs.append("".join(texts))
    return "\n".join(p for p in paragraphs if p.strip()).strip()


def _val(element, path: str) -> str | None:
    """The `w:val` of `element`'s child at `path`, or None."""
    found = element.find(path)
    return found.get(f"{_W}val") if found is not None else None


def _font(element) -> str | None:
    """The font a run or a style names in its own `w:rPr/w:rFonts` (its ASCII one, else its high-ANSI one)."""
    fonts = element.find(f"{_W}rPr/{_W}rFonts")
    return fonts.get(f"{_W}ascii") or fonts.get(f"{_W}hAnsi") if fonts is not None else None


_BOMS = ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16"))


def _decode_text_file(data: bytes) -> str:
    """A text file as Windows' Notepad may have saved it: its BOM's encoding (UTF-8 or UTF-16), else UTF-8,
    else the Western "ANSI" code page (cp1252), which reads any byte."""
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            return data.decode(encoding)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _onboarding_cv_text(profile_dir: Path, config: dict) -> str | None:
    """The CV to read: `profile/cv.draft.md` while onboarding, else the profile's CV; `None` when there is
    neither, or the CV is still profile.example/'s. Before Save there is no config, so no `cv_content`."""
    draft = profile_dir / _DRAFT_NAME
    path = draft if draft.is_file() else Path(config.get("cv_content") or profile_dir / "cv.md")
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    if not text.strip() or common._is_example_cv(path):
        return None
    return text.strip()


def _words(text: str) -> str:
    """`text` as lower-case words alone, for comparing a todo with a line or a title."""
    return " ".join(re.sub(r"[^\w\s]", " ", text).split()).casefold()


def _without_skills_todos(markdown: str, todos: list[str], headings: list[str]) -> tuple[str, list[str]]:
    """A CV need not list its skills, so nothing asks for them: `TODO`s go from the skills sections the model named
    (`headings`, the `## ` texts it wrote), a section with nothing else left goes too, and so do the model's todos about
    them: one that says what a removed `TODO` line said, or (for a bare `TODO`) names the section."""
    named = {" ".join(h.split()).casefold() for h in headings if h.strip()}
    found = False
    kept: list[str] = []
    gone: set[str] = set()  # what each removed TODO line said, and the section's title for a bare one
    for section in cv_sections.split(markdown):
        title = " ".join(cv_sections.heading(section[0]).split()).casefold() if section and section[0].startswith("## ") else None
        if title not in named or not any("TODO" in line for line in section):
            kept.extend(section)
            continue
        found = True
        gone.add(_words(title))
        for line in section[1:]:
            if "TODO" in line and _skills_line_without_todo(line) is None:
                if said := _words(line.replace("TODO", " ")):
                    gone.add(said)
        body = [left for left in map(_skills_line_without_todo, section[1:]) if left is not None]
        if any(line.strip() for line in body):
            kept.extend([section[0], *body])
    if not found:
        return markdown, todos
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip() + "\n"
    return text, [t for t in todos if not any(g in _words(t) for g in gone)]


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
    config = profile_loader.load_config_or_defaults(profile_dir)

    described = []
    parts = []
    urls = []
    for source in sources:
        if common._is_url(source):
            described.append({"source": source, "kind": "url"})
            urls.append(source)
        else:
            path = Path(source)
            text = _extract_text(path)
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
        "cv-drafter", prompt, model=model, fields={"webfetch_rules": common._WEBFETCH_RULES}, feature="draft_cv", schema=_SCHEMA,
        timeout_s=timeout_s, profile_dir=profile_dir,
    )
    markdown = answer.get("cv_markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        raise claude_cli.ClaudeError("claude's answer has no `cv_markdown`")
    markdown = markdown.strip() + "\n"
    provenance = [p for p in answer.get("provenance") or [] if isinstance(p, dict)]
    todos = [str(t) for t in answer.get("todos") or []]
    markdown, todos = _without_skills_todos(markdown, todos, [str(h) for h in answer.get("skills_headings") or []])

    migrations.ensure_folder(profile_dir, "profile")
    draft_path = profile_dir / _DRAFT_NAME
    result = {"written": write, "sources": described, "provenance": provenance, "todos": todos, "markdown": markdown}
    if write:
        cv_path = profile_dir / "cv.md"
        backup = common._write_with_backup(cv_path, markdown)
        if draft_path.exists():
            draft_path.unlink()
        result.update(cv_path=str(cv_path), backup=str(backup) if backup else None)
    else:
        utils.write_atomic(draft_path, markdown)
        result["draft_path"] = str(draft_path)
    return result


_DEFAULT_REMOTE = "hybrid"

def _usable(value) -> str | None:
    """`value` as text, or `None` when it is empty or still a `TODO` of the draft."""
    text = " ".join(str(value or "").split())
    return text if text and "TODO" not in text else None


def _working_languages(read) -> list[str]:
    """English, plus each supported language the reading puts at a working level (by its ISO code), by its file's name."""
    packs = i18n.languages()
    codes = ["en"]
    for item in read:
        if item.get("code") in packs and item["code"] not in codes and item.get("level") in cv_read.LEVELS[:3]:  # native, fluent, working
            codes.append(item["code"])
    return [packs[c].name for c in codes]


def _infer_basics_core(
    markdown: str | None = None,
    *,
    profile_dir: Path | None = None,
) -> dict:
    """Read the profile basics from the CV: `markdown`, else the draft or the CV on disk, through `cv_read.read` (one
    cached model call per CV text). Works before the profile exists, and a CV that could not be read never stops a
    flow: what it would have said is `missing`.

    Returns:
        ``{"name", "email", "location", "languages", "remote", "missing"}`` (`None` for what was not found;
        `missing` lists the keys to ask about, and is the only reason to ask), plus ``"unsupported_location"`` (a
        place in a country The other door does not cover: ask) and ``"warning"`` (the CV could not be read).

    Raises:
        ConfigError: an invalid profile/config.json.
    """
    if profile_dir is None:
        profile_dir = workspace.PROFILE_DIR
    text = (markdown or "").strip() or _onboarding_cv_text(profile_dir, profile_loader.load_config_or_defaults(profile_dir))
    result = {"name": None, "email": None, "location": None, "languages": ["English"], "remote": _DEFAULT_REMOTE, "missing": []}
    if not text:
        return {**result, "missing": ["name", "email", "location"]}
    try:
        read = cv_read.read(text)
    except cv_read.CvReadError as exc:
        return {**result, "missing": ["name", "email", "location"], "warning": str(exc)}

    city = _usable(read.get("city"))
    location = i18n.known_city(city) if city else None
    country = str(read.get("country") or "").lower()
    # A city in a country The other door does not cover is one to say so about; a country alone, or a city of a
    # covered country that is not listed, says too little to search and is only asked about.
    unsupported = city if city and not location and country and country not in i18n.countries() else None
    result.update(name=_usable(read.get("name")), email=_usable(read.get("email")), location=location,
                  languages=_working_languages(read.get("languages") or []))
    if unsupported:
        result["unsupported_location"] = unsupported
    result["missing"] = [key for key in ("name", "email", "location") if not result[key]]
    return result


@click.group("cv")
def cv_group():
    """Your CV over time: `cv enrich` adds what your public pages show, `cv gaps` plans what to learn, `cv titles` suggests titles to look for, `cv stories` keeps the story bank the tailor draws on."""
