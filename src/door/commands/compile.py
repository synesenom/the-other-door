"""HTML body → PDF for a prepared application (#146): the `compile` tool the tailor agent calls and `revise` reuses; there is no command.

The tailor writes `cv.html` / `cover_letter.html`, a body fragment in the closed vocabulary of `render/html_guard`.
`compile` fills its tokens, guards it, gives it its photo and its language's typography, wraps it in the resolved
template (the head, the CSS, the fonts, the page) and prints it with the pinned Chromium (`render/html_pdf`). Each
PDF is read back as an ATS would, and its pages rendered to PNGs. The file on disk stays the body, unwrapped.
"""

import re
import shutil
from datetime import date
from pathlib import Path

from door import i18n
from door.commands import _common as common
from door.core import chromium, templates
from door.core import photo as photo_mod
from door.core import utils, workspace
from door.render import html_doc, html_guard, html_pdf, readability, typography

_FILES = {"cv.html": "cv_template", "cover_letter.html": "cover_letter_template"}

# What the tailor writes in place of the ad's own words (#441): `compile` fills each in from the output folder's
# posting.json, ATS-normalised and HTML-escaped, so a title such as `<script>x</script>` or `R&D_Lead` is plain text
# on the page and the agent needs no shell.
_PLACEHOLDERS = {"<<company>>": "company", "<<title>>": "title"}
_DATE_TOKEN = "<<date>>"


def _language(posting: dict) -> str:
    """The code of the ad's language (the tailor writes in it), English when the posting is untagged or has none."""
    return i18n.language_code(str(posting.get("language") or "")) or "en"


def _fill_placeholders(body: str, posting: dict, output_dir: Path) -> str:
    """`body` with each `_PLACEHOLDERS` token replaced by the posting's field, escaped, and `<<date>>` by today's date
    in the ad's language.

    Raises:
        ValueError: a posting token is used but posting.json is missing or unreadable.
    """
    used = [token for token in _PLACEHOLDERS if token in body]
    if used:
        if not posting:
            raise ValueError(f"{', '.join(used)} need posting.json in {output_dir}")
        for token in used:
            value = str(posting.get(_PLACEHOLDERS[token]) or "")
            body = body.replace(token, utils._escape_html(utils._normalize_text_for_ats(value)))
    if _DATE_TOKEN in body:
        body = body.replace(_DATE_TOKEN, i18n.format_date(date.today(), _language(posting)))
    return body


# The CV photo (#605): the tailor writes `<<photo>>` where it wants one. After the guard has read the body, `compile`
# swaps it for this one trusted image of the copy of the profile's photo it puts beside the page (the template must
# style `.photo`, or it prints no photo), or for nothing. The body on disk keeps the token, so a recompile
# (`revise`) passes the guard again.
_PHOTO_TOKEN = "<<photo>>"
_PHOTO_CLASS = re.compile(r"\.photo(?![\w-])")
_COMMENTS = re.compile(r"/\*.*?\*/|<!--.*?-->", re.S)
_PHOTO_FILES = {"jpeg": "photo.jpg", "png": "photo.png"}
_PHOTO_HTML = '<img class="photo" src="%s" alt="">'


def _profile_photo(posting: dict, config: dict) -> Path | None:
    """The profile's photo (`config` is the raw config: a photo needs no valid profile around it), when the job's
    country lets a CV carry one and the file is a usable picture."""
    if not isinstance(config.get("photo"), str) or common._cv_conventions(posting, config).photo == "no":
        return None
    path = Path(config["photo"])
    path = path if path.is_absolute() else workspace.HOME / path
    return path if photo_mod.problem(path) is None else None


def _with_photo(body: str, template: str, output_dir: Path, photo: Path | None) -> tuple[str, str | None]:
    """`body` with `<<photo>>` swapped for the image of `photo` (the first token; any other for nothing) and the name
    of the copy put into `output_dir`, else with every one removed and ``None`` (no photo, or a template that does
    not style `.photo`)."""
    if _PHOTO_TOKEN not in body:
        return body, None
    source = photo if _PHOTO_CLASS.search(_COMMENTS.sub("", template)) else None
    if source is None:
        return body.replace(_PHOTO_TOKEN, ""), None
    name = _PHOTO_FILES[photo_mod.kind(source.read_bytes()[:16])]
    shutil.copyfile(source, output_dir / name)
    first, _, rest = body.partition(_PHOTO_TOKEN)
    return first + _PHOTO_HTML % name + rest.replace(_PHOTO_TOKEN, ""), name


def page(body: str, template: str, folder: Path, *, photo: Path | None, columns: templates.Columns | None,
         language: str) -> tuple[str, str, str | None]:
    """The page `compile` prints for a body: the photo placed (copied into `folder`), the two columns, the language's
    typography, each entry heading's separator kept to the text before it, wrapped in `template`. Returns the page,
    the body as placed and the photo's file name (None when it was not placed).

    Raises:
        ValueError: the template cannot hold the body.
    """
    built, name = _with_photo(body, template, folder, photo)
    placed = _place_columns(built, columns)
    return _wrap(template, _glue_separators(typography.apply(placed, language)), language), placed, name


_SEP_SPACE = re.compile(r'(<span class="sep">) ')


def _glue_separators(body: str) -> str:
    """`body` with the space that opens an entry heading's separator (`<span class="sep"> | </span>`) a no-break one:
    a heading too long for its line breaks after the separator, never before it (#246)."""
    return _SEP_SPACE.sub("\\1&#160;", body)


def print_page(body: str, template: str, assets_of: Path, lang: str, folder: Path, name: str, *,
               columns: templates.Columns | None = None, photo: Path | None = None) -> tuple[Path, str, str | None]:
    """`body` placed in `template` (its text) by `page` and printed to `folder/<name>.pdf` with the pinned Chromium,
    the fonts and icons that the template file `assets_of` names served. Returns the pdf, the body as placed and the
    photo's file name in `folder` (None when it was not placed).

    Raises:
        html_pdf.PrintError: the print failed.
        ValueError: the template or its manifest cannot be used.
    """
    folder.mkdir(parents=True, exist_ok=True)
    assets = templates.assets(assets_of)
    html_text, placed, picture = page(body, template, folder, photo=photo, language=lang, columns=columns)
    pdf = folder / f"{name}.pdf"
    html_pdf.print_html(folder, html_text, pdf, assets=assets)
    return pdf, placed, picture


_H2 = re.compile(r"(?=<h2[\s>])")


def _place_columns(body: str, columns: templates.Columns | None) -> str:
    """The CV `body` with its sections in the template's two columns (#147): what comes before the first `<h2>` after
    the header (the notes, the photo, the whole header: an `<h2>` inside it is the header's, #242) as it is, then
    `<div class="main">` and `<div class="side">` (`html_doc.columns` reads them back), each section in the order the
    body has it. A section goes to the side when its heading is, whole and without case, a title of one of
    the template's ``columns.side`` kinds in any supported language (a CV's headings are in its own language, whatever
    the ad's, #227), or is, whole and without case, one of its ``columns.headings``; any other goes to the main column.
    `body` itself when the template has no side column."""
    if columns is None or not (columns.side or columns.headings):
        return body
    cut = body.find("</header>") + len("</header>") if "</header>" in body else 0
    first, *sections = _H2.split(body[cut:])
    first = body[:cut] + first
    main, side = [], []
    for section in sections:
        heading = (html_doc.headings(section) or [""])[0]
        named = heading.casefold() in {h.casefold() for h in columns.headings}
        (side if named or i18n.cv_section_kind(heading, columns.side) else main).append(section)
    return f'{first}{html_doc.MAIN}{"".join(main)}</div>{html_doc.SIDE}{"".join(side)}</div>'


def placed_cv(body: str, config: dict) -> str:
    """The CV `body` as its printed page reads it (`_place_columns` by the resolved CV template's manifest); `body` itself when the template has no side column or cannot be read."""
    try:
        columns = (templates.manifest(templates.resolve("cv_template", config)) or templates.Manifest()).columns
    except (OSError, ValueError):
        columns = None
    return _place_columns(body, columns)


def _wrap(template: str, body: str, language: str) -> str:
    """`template` with its language and `body` in place.

    Raises:
        ValueError: the template has no `<<body>>` to put the body in.
    """
    if "<<body>>" not in template:
        raise ValueError("the template has no <<body>> to put the page in")
    return template.replace("<<lang>>", language).replace("<<body>>", body)


def _read_back(entry: dict, pdf: Path, body: str, config: dict, cv: bool = False) -> None:
    """Set ``entry["readable"]`` from the compiled PDF, read against the `body` it was printed from (a CV's sections as
    placed); `cv` adds the CV's overflow and layout checks; a failing check is a ``warning``, never a failed compile."""
    try:
        entry["readable"] = readability.check_pdf(pdf, body, config.get("name"), cv=cv)
    except Exception as exc:  # the check must never fail a compile
        entry["readable"] = None
        entry["warning"] = f"could not read the PDF back: {exc}"


def _compile_core(job_id: str, render: bool = False, jobs_dir: Path | None = None) -> dict:
    """Print the HTML bodies of a job application into PDFs; return structured data.

    Mirrors the `compile` tool's side effects (starts the pinned Chromium headless shell, sealed: scripts off, only
    the job folder and the template's fonts and icons served) but never prints to stdout: callers render their own presentation from the
    returned dict.

    Args:
        job_id: The job: its id, or words from its company and title
            (see `_resolve_job_ref`).
        render: Also render the PDFs that compiled to page PNGs (see
            `_render_pages`) — what the tailor agent inspects.
        jobs_dir: Directory containing `output/<job_id>/` (defaults to the
            module-level `JOBS_DIR`).

    Returns:
        ``{"job_id", "output_dir", "results": [{"file", "status": "compiled"
        | "skipped" | "error", "pdf"?, "photo"?, "stderr"?, "readable"?, "warning"?}, ...]}``;
        ``readable`` (`readability.check_pdf`) is what an ATS would not read back from a compiled PDF,
        ``[{kind, detail}]`` (``[]`` clean, None when the check itself failed, with a ``warning``); plus
        ``"render"`` (`_render_pages`'s ``results``, for the PDFs that just
        compiled) when ``render``.

    Raises:
        ValueError: `job_id` is not a valid slug.
        FileNotFoundError: `jobs_dir/output/<job_id>/` does not exist.
        NoChromium: no Chromium is installed (in words; a command adds `common.INSTALL_HINT`).
    """
    if jobs_dir is None:
        jobs_dir = workspace.JOBS_DIR

    job_id = common._resolve_job_ref(job_id, jobs_dir)

    output_dir = jobs_dir / "output" / job_id
    if not output_dir.exists():
        raise FileNotFoundError(f"output directory not found: {output_dir}")

    results = []
    photos: list[str] = []
    config = common._load_json_tolerant(workspace.PROFILE_DIR / "config.json")
    posting = common._load_json_tolerant(output_dir / "posting.json")
    language = _language(posting)
    for file, key in _FILES.items():
        path = output_dir / file
        if not path.exists():
            results.append({"file": file, "status": "skipped"})
            continue

        entry = {"file": file}
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            body = _fill_placeholders(text, posting, output_dir)
        except ValueError as exc:
            entry.update(status="error", stderr=str(exc))
            results.append(entry)
            continue
        if body != text:
            path.write_text(body, encoding="utf-8")
        refused = html_guard.unsafe(body)
        if refused:  # model output never gets to load another file, reach the network or run anything
            entry.update(status="error", stderr=f"refused: {file} uses {', '.join(refused)}, which is outside the tags and links a CV or letter is written in")
            results.append(entry)
            continue
        try:
            template_path = templates.resolve(key, config)
            template = template_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            entry.update(status="error", stderr=f"could not read the template: {exc}")
            results.append(entry)
            continue
        if not common._chromium_available():
            raise common.NoChromium
        try:
            columns = (templates.manifest(template_path) or templates.Manifest()).columns if file == "cv.html" else None
            pdf, placed, photo_name = print_page(body, template, template_path, language, output_dir, Path(file).stem,
                                                 columns=columns, photo=_profile_photo(posting, config))
        except (ValueError, html_pdf.PrintError) as exc:
            entry.update(status="error", stderr=str(exc))
            results.append(entry)
            continue
        if photo_name:
            entry["photo"] = photo_name
            photos.append(photo_name)
        entry.update(status="compiled", pdf=str(pdf))
        _read_back(entry, pdf, placed, config, cv=file == "cv.html")
        results.append(entry)

    for name in _PHOTO_FILES.values():  # a photo from an earlier compile that this one does not use
        if name not in photos:
            (output_dir / name).unlink(missing_ok=True)

    result = {"job_id": job_id, "output_dir": str(output_dir), "results": results}
    if render:
        compiled = [Path(e["pdf"]).name for e in results if e["status"] == "compiled"]
        result["render"] = _render_pages(output_dir, compiled)
    return result


def _render_pages(output_dir: Path, pdf_names=("cv.pdf", "cover_letter.pdf")) -> list[dict]:
    """Render each named PDF in `output_dir` to `<stem>_page_<N>.png` beside it.

    Returns:
        ``[{"file", "status": "rendered" | "skipped", "pages"?: [str, ...],
        "page_count"?: int}, ...]`` — ``page_count`` is what the tailor
        agent's 2-page CV / 1-page cover letter checks read; a missing PDF
        is ``skipped``.
    """
    from door.render.pdf_render import render_pdf_pages

    results = []
    for pdf_name in pdf_names:
        pdf_path = Path(output_dir) / pdf_name
        if not pdf_path.exists():
            results.append({"file": pdf_name, "status": "skipped"})
            continue
        png_paths = render_pdf_pages(pdf_path, Path(output_dir))
        results.append({
            "file": pdf_name,
            "status": "rendered",
            "pages": [str(p) for p in png_paths],
            "page_count": len(png_paths),
        })
    return results
