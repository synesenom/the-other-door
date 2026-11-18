"""HTML body → PDF for a prepared application (#146): the `compile` tool the tailor agent calls and `revise` reuses; there is no command.

The tailor writes `cv.html` / `cover_letter.html`, a body fragment in the closed vocabulary of `render/html_guard`.
`compile` fills its tokens, guards it, gives it its photo and its language's typography, wraps it in the resolved
template (the head, the CSS, the fonts, the page) and prints it with the pinned Chromium (`render/html_pdf`). Each
PDF is read back as an ATS would, and its pages rendered to PNGs. The file on disk stays the body, unwrapped.
"""

from datetime import date
from pathlib import Path

from door import i18n
from door.commands import _common as common
from door.core import templates, utils, workspace
from door.render import html_guard, html_pdf, readability
from door.render import page as page_mod

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
            photo = page_mod.profile_photo(config, common._cv_conventions(posting, config)) if config.get("photo") else None
            pdf, placed, photo_name = page_mod.print_page(
                body, template, template_path, language, output_dir, Path(file).stem, columns=columns, photo=photo)
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

    for name in page_mod.PHOTO_FILES.values():  # a photo from an earlier compile that this one does not use
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
