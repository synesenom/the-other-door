"""LaTeX → PDF for a prepared application (Tectonic, else xelatex), each PDF read back as an ATS would, and PDF pages → PNGs: the `compile` tool the tailor agent calls and `revise` reuses; there is no command."""

import json
import re
import shutil
import subprocess
from pathlib import Path

from door.commands import _common as common
from door.tailoring import readability, tex_guard
from door.core import photo as photo_mod
from door.core import utils, workspace

# What the tailor writes in place of the ad's own words (#441): `compile` fills each in from
# the output folder's posting.json, ATS-normalised and LaTeX-escaped, so a title such as
# `\write18{...}` or `R&D_Lead` is plain text on the page and the agent needs no shell.
_PLACEHOLDERS = {"<<company>>": "company", "<<title>>": "title"}


def _fill_placeholders(tex: str, output_dir: Path) -> str:
    """`tex` with each `_PLACEHOLDERS` token replaced by the posting's field, escaped.

    Raises:
        ValueError: a token is used but posting.json is missing or unreadable.
    """
    used = [token for token in _PLACEHOLDERS if token in tex]
    if not used:
        return tex
    try:
        posting = json.loads((output_dir / "posting.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{', '.join(used)} need posting.json in {output_dir}: {exc}") from None
    for token in used:
        value = str(posting.get(_PLACEHOLDERS[token]) or "")
        tex = tex.replace(token, utils._escape_latex(utils._normalize_text_for_ats(value)))
    return tex


# The CV photo (#605): the tailor writes `<<photo>>` where it wants one. After the guard has read the document,
# `compile` swaps it for this one trusted `\includegraphics` of the copy of the profile's photo it puts beside
# the .tex, inside the template's `\cvphotobox` (a template without that macro prints no photo), or for nothing.
# The .tex on disk keeps the placeholder, so a recompile (`revise`) passes the guard again.
_PHOTO_TOKEN = "<<photo>>"
_PHOTO_BOX = re.compile(r"\\(?:re)?newcommand\s*\{?\\cvphotobox(?![A-Za-z])")
_PHOTO_FILES = {"jpeg": "photo.jpg", "png": "photo.png"}
_PHOTO_TEX = "\\cvphotobox{\\includegraphics[width=2.2cm]{%s}}"


def _profile_photo(posting_path: Path) -> Path | None:
    """The profile's photo, when the job's country lets a CV carry one and the file is a usable picture."""
    try:  # the raw config: a photo needs no valid profile around it
        config = json.loads((workspace.PROFILE_DIR / "config.json").read_text(encoding="utf-8"))
        posting = json.loads(posting_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(config.get("photo"), str) or common._cv_conventions(posting, config).photo == "no":
        return None
    path = Path(config["photo"])
    path = path if path.is_absolute() else workspace.HOME / path
    return path if photo_mod.problem(path) is None else None


def _with_photo(tex: str, output_dir: Path) -> tuple[str, str | None]:
    """`tex` with `<<photo>>` swapped for the photo macro (the first one; any other for nothing) and the name
    of the photo copied into `output_dir`, else with every one removed and ``None``. Only a token in the body
    counts: the template's preamble names it in a comment, which is no request for a photo."""
    preamble, begin, body = tex.rpartition("\\begin{document}")  # its comments name it too
    if not begin or _PHOTO_TOKEN not in body:
        return tex, None
    source = _profile_photo(output_dir / "posting.json") if _PHOTO_BOX.search(preamble) else None
    if source is None:
        return preamble + begin + body.replace(_PHOTO_TOKEN, ""), None
    name = _PHOTO_FILES[photo_mod.kind(source.read_bytes()[:16])]
    shutil.copyfile(source, output_dir / name)
    first, _, rest = body.partition(_PHOTO_TOKEN)
    return preamble + begin + first + _PHOTO_TEX % name + rest.replace(_PHOTO_TOKEN, ""), name


# The templates' fonts (#623): a template loads them from `<<fonts>>`; `compile` swaps the token for the profile's
# `fonts/` folder (the example's when the profile has none) only while LaTeX runs, like the photo, so the .tex on
# disk names no path of this computer and a job folder holds no copy of the fonts.
_FONTS_TOKEN = "<<fonts>>"


def _with_fonts(tex: str) -> str:
    """`tex` with `<<fonts>>` swapped for the absolute fonts folder, in forward slashes (what LaTeX reads)."""
    if _FONTS_TOKEN not in tex:
        return tex
    folder = workspace.PROFILE_DIR / "fonts"
    if not folder.is_dir():
        folder = workspace.PROFILE_EXAMPLE_DIR / "fonts"
    return tex.replace(_FONTS_TOKEN, folder.as_posix())


def _find_tectonic() -> str | None:
    """Tectonic on PATH or in ~/.local/bin (a seam for tests)."""
    from door.core.installers import find_tectonic

    return find_tectonic()


def _run_compilers(tex_path: Path, output_dir: Path, entry: dict) -> None:
    """Compile ``tex_path``, Tectonic first when installed (what `setup` installs, possibly in ~/.local/bin off
    PATH; shell escape is off by default there), then `xelatex`; the outcome goes in ``entry``
    (``status`` ``compiled`` with ``pdf`` and ``compiler``, or ``error`` with ``stderr``).

    Raises:
        MissingToolError: no compiler is installed.
    """
    ran_any = False
    tectonic = _find_tectonic()
    compilers = (["tectonic"] if tectonic else []) + ["xelatex"]
    for compiler in compilers:
        if compiler == "tectonic":
            argv = [tectonic, "--outdir", str(output_dir), str(tex_path)]
        else:
            argv = [compiler, "-no-shell-escape", "-interaction=nonstopmode", "-output-directory", str(output_dir), str(tex_path)]
        try:
            result = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        except FileNotFoundError:
            continue
        ran_any = True
        if result.returncode == 0:
            entry["status"] = "compiled"
            entry["pdf"] = str(tex_path.with_suffix(".pdf"))
            entry["compiler"] = compiler
            entry.pop("stderr", None)  # an earlier compiler's failure
            break
        entry["status"] = "error"
        entry["stderr"] = result.stderr
    if not ran_any:
        from door.core import doctor

        raise common.MissingToolError(f"no LaTeX compiler (tectonic/xelatex) found — {doctor._LATEX_FIX}")


def _profile_name() -> str | None:
    """The candidate's name from the raw config (the read-back needs no valid profile)."""
    try:
        name = json.loads((workspace.PROFILE_DIR / "config.json").read_text(encoding="utf-8")).get("name")
    except (OSError, ValueError, AttributeError):
        return None
    return name if isinstance(name, str) else None


def _read_back(entry: dict, tex_path: Path, tex: str) -> None:
    """Set ``entry["readable"]`` from the compiled PDF; a failing check is a ``warning``, never a failed compile."""
    try:
        entry["readable"] = readability.check_pdf(tex_path.with_suffix(".pdf"), tex, _profile_name())
    except Exception as exc:  # the check must never fail a compile
        entry["readable"] = None
        entry["warning"] = f"could not read the PDF back: {exc}"


def _compile_core(job_id: str, render: bool = False, jobs_dir: Path | None = None) -> dict:
    """Compile LaTeX sources for a job application into PDFs; return structured data.

    Mirrors the `compile` CLI command's side effects (invokes Tectonic, else
    `xelatex`, via `subprocess.run`, falling back in that order)
    but never prints — callers (CLI, MCP) render their own
    presentation from the returned dict.

    Args:
        job_id: The job: its id, or words from its company and title
            (see `_resolve_job_ref`).
        render: Also render the PDFs that compiled to page PNGs (see
            `_render_pages`) — what the tailor agent inspects.
        jobs_dir: Directory containing `output/<job_id>/` (defaults to the
            module-level `JOBS_DIR`).

    Returns:
        ``{"job_id", "output_dir", "results": [{"file", "status": "compiled"
        | "skipped" | "error", "pdf"?, "compiler"?, "stderr"?, "readable"?, "warning"?}, ...]}``;
        ``readable`` (`readability.check_pdf`) is what an ATS would not read back from a compiled PDF,
        ``[{kind, detail}]`` (``[]`` clean, None when the check itself failed, with a ``warning``); plus
        ``"render"`` (`_render_pages`'s ``results``, for the PDFs that just
        compiled) when ``render``.

    Raises:
        ValueError: `job_id` is not a valid slug.
        FileNotFoundError: `jobs_dir/output/<job_id>/` does not exist.
        MissingToolError: no Tectonic or `xelatex` is installed
            (the message carries the install command).
    """
    if jobs_dir is None:
        jobs_dir = workspace.JOBS_DIR

    job_id = common._resolve_job_ref(job_id, jobs_dir)

    output_dir = jobs_dir / "output" / job_id
    if not output_dir.exists():
        raise FileNotFoundError(f"output directory not found: {output_dir}")

    results = []
    photos: list[str] = []
    for tex_file in ["cv.tex", "cover_letter.tex"]:
        tex_path = output_dir / tex_file
        if not tex_path.exists():
            results.append({"file": tex_file, "status": "skipped"})
            continue

        entry = {"file": tex_file}
        text = tex_path.read_text(encoding="utf-8", errors="replace")
        try:
            filled = _fill_placeholders(text, output_dir)
        except ValueError as exc:
            entry.update(status="error", stderr=str(exc))
            results.append(entry)
            continue
        if filled != text:
            tex_path.write_text(filled, encoding="utf-8")
        refused = tex_guard.unsafe(filled)
        if refused:  # model output never gets to read or write other files, or run anything
            entry.update(status="error", stderr=f"refused: {tex_file} uses {', '.join(refused)}, which reads or writes other files or runs programs; a CV or letter needs none of it")
            results.append(entry)
            continue
        built, photo_name = _with_photo(filled, output_dir)
        built = _with_fonts(built)
        if photo_name:
            entry["photo"] = photo_name
            photos.append(photo_name)
        if built != filled:  # LaTeX reads the trusted \includegraphics and fonts path; the file on disk keeps neither
            tex_path.write_text(built, encoding="utf-8")
        try:
            _run_compilers(tex_path, output_dir, entry)
        finally:
            if built != filled:
                tex_path.write_text(filled, encoding="utf-8")
        if entry.get("status") == "compiled":
            _read_back(entry, tex_path, filled)
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
