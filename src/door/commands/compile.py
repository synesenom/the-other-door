"""HTML body → PDF for a prepared application (#146): the `compile` tool the tailor agent calls and `revise` reuses; there is no command.

The tailor writes `cv.html` / `cover_letter.html`, a body fragment in the closed vocabulary of `tailoring/html_guard`.
`compile` fills its tokens, guards it, gives it its photo and its language's typography, wraps it in the resolved
template (the head, the CSS, the fonts, the page) and prints it with the pinned Chromium (`tailoring/html_pdf`). Each
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
from door.tailoring import html_guard, html_pdf, readability, typography

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


def _with_photo(body: str, template: str, output_dir: Path, posting: dict, config: dict) -> tuple[str, str | None]:
    """`body` with `<<photo>>` swapped for the photo image (the first one; any other for nothing) and the name of the
    photo copied into `output_dir`, else with every one removed and ``None``."""
    if _PHOTO_TOKEN not in body:
        return body, None
    source = _profile_photo(posting, config) if _PHOTO_CLASS.search(_COMMENTS.sub("", template)) else None
    if source is None:
        return body.replace(_PHOTO_TOKEN, ""), None
    name = _PHOTO_FILES[photo_mod.kind(source.read_bytes()[:16])]
    shutil.copyfile(source, output_dir / name)
    first, _, rest = body.partition(_PHOTO_TOKEN)
    return first + _PHOTO_HTML % name + rest.replace(_PHOTO_TOKEN, ""), name


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
            raise ValueError(f"{templates.MANIFEST_FILE} names {folder.name}/{file.name}, which is not in {folder}")
    return files


def _assets(template_path: Path) -> dict[str, list[Path]]:
    """What the print serves beside the page: the fonts a `template.json` names (#188), from the `fonts/` beside the
    template, else the TrueType files `_fonts_dir` finds; and the icons it names, from the `icons/` beside it.

    Raises:
        ValueError: the manifest is invalid, or names a file that is not there.
    """
    manifest = templates.manifest(template_path)
    folder = Path(template_path).parent
    if manifest and manifest.fonts:
        assets = {"fonts": _named(folder / "fonts", manifest.fonts)}
    else:
        assets = {"fonts": sorted(_fonts_dir().glob("*.ttf"))}
    if manifest and manifest.icons:
        assets["icons"] = _named(folder / "icons", manifest.icons.values())
    return assets


def _wrap(template: str, body: str, language: str) -> str:
    """`template` with its language and `body` in place.

    Raises:
        ValueError: the template has no `<<body>>` to put the body in.
    """
    if "<<body>>" not in template:
        raise ValueError("the template has no <<body>> to put the page in")
    return template.replace("<<lang>>", language).replace("<<body>>", body)


def _print(html: str, output_dir: Path, name: str, entry: dict, assets: dict) -> None:
    """Print `html` to `output_dir/<name>.pdf`; the outcome goes in ``entry`` (``status`` ``compiled`` with ``pdf``, or
    ``error`` with ``stderr``). The page is served from memory: the body on disk is not it.

    Raises:
        MissingToolError: no Chromium is installed.
    """
    if chromium.find_chromium() is None:
        from door.core import doctor

        raise common.MissingToolError(f"no Chromium to print with: {doctor._CHROMIUM_FIX}")
    pdf = output_dir / f"{name}.pdf"
    try:
        html_pdf.print_html(output_dir, html, pdf, assets=assets)
    except html_pdf.PrintError as exc:
        entry.update(status="error", stderr=str(exc))
        return
    entry.update(status="compiled", pdf=str(pdf))
    entry.pop("stderr", None)


def _read_back(entry: dict, pdf: Path, body: str, config: dict) -> None:
    """Set ``entry["readable"]`` from the compiled PDF; a failing check is a ``warning``, never a failed compile."""
    try:
        entry["readable"] = readability.check_pdf(pdf, body, config.get("name"))
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
        MissingToolError: no Chromium is installed (the message carries the install command).
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
        try:
            assets = _assets(template_path)
        except ValueError as exc:
            entry.update(status="error", stderr=str(exc))
            results.append(entry)
            continue
        built, photo_name = _with_photo(body, template, output_dir, posting, config)
        if photo_name:
            entry["photo"] = photo_name
            photos.append(photo_name)
        try:
            page = _wrap(template, typography.apply(built, language), language)
        except ValueError as exc:
            entry.update(status="error", stderr=str(exc))
            results.append(entry)
            continue
        _print(page, output_dir, Path(file).stem, entry, assets)
        if entry.get("status") == "compiled":
            _read_back(entry, Path(entry["pdf"]), body, config)
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
    from door.tailoring.pdf_render import render_pdf_pages

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
