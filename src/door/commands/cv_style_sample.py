"""`cv_style_sample` (#465): the CV in a chosen accent colour and font pair, page 1 as a picture.

The desktop app's Profile -> CV style shows it beside the pickers. It prints the user's own CV (else the example CV)
as it is, with no model but the one cached reading of it (`cv_read`), through the same template and style that `compile`
uses for a prepared CV, so the sample is what the next prepared CV looks like. Cached under `HOME/.style/preview/` by the
CV, the style, the photo and the template. The picture is a close-up: the top of a narrow page (`SAMPLE_PAGE`), so the text
is large where the app shows it small.
"""

from __future__ import annotations

import base64
import hashlib

from door.commands import _common as common
from door.core import cv_read, templates, utils, workspace
from door.render import cv_body, html_pdf, pdf_render
from door.render import page as page_mod

# Printed on a page this size, with no margin (the app pads the picture): the lines re-flow, so the text is large in the
# app's small box and no line is cut at the edge. Only the top of page 1 is shown; the app fades it out at its foot.
SAMPLE_PAGE = "@page{size:10cm 13cm;margin:0}"


def _cv_text(config: dict) -> tuple[str, bool]:
    """The CV to print and whether it is the user's own: `profile/cv.md`, else the example CV."""
    own = workspace.cv_path(config, workspace.PROFILE_DIR)
    if own.is_file():
        return own.read_text(encoding="utf-8"), True
    return (workspace.PROFILE_EXAMPLE_DIR / "cv.md").read_text(encoding="utf-8"), False


def _answer(png: bytes, own: bool) -> dict:
    return {"png_base64": base64.b64encode(png).decode("ascii"), "own_cv": own}


def _cv_style_sample_core(accent: str, fonts: str) -> dict:
    """Page 1 of the CV printed with `accent` and `fonts` (a name `Profile` does not accept counts as the default):
    ``{"png_base64", "own_cv"}``, or ``{"error": kind}`` where kind is ``cv_unreadable`` (the CV cannot be read: the user
    can act) or ``print_failed`` (nothing the user can do).

    Raises:
        ValueError: no Chromium is installed.
    """
    config = common._load_json_tolerant(workspace.PROFILE_DIR / "config.json")
    cv_md, own = _cv_text(config)
    template_path = templates.resolve("cv_template", config)
    template = template_path.read_text(encoding="utf-8")
    photo = page_mod.profile_photo(config, {}) if own else None
    style = templates.style_css({"cv_accent": accent, "cv_fonts": fonts}) + SAMPLE_PAGE
    # `<the CV's hash>-<the rest's>.png`: a new CV drops the files of the old one, so the folder never grows
    cv_key = hashlib.sha256(cv_md.encode("utf-8")).hexdigest()[:16]
    rest = "\0".join([style, template, photo.name if photo else "", hashlib.sha256(photo.read_bytes()).hexdigest() if photo else ""])
    folder = workspace.HOME / ".style" / "preview"
    cached = folder / f"{cv_key}-{hashlib.sha256(rest.encode('utf-8')).hexdigest()[:16]}.png"
    if cached.is_file():
        return _answer(cached.read_bytes(), own)
    if not common._chromium_available():
        raise common.NoChromium
    try:
        body = cv_body.body(cv_md, cv_read.read(cv_md))
    except cv_read.CvReadError:
        return {"error": "cv_unreadable"}
    with utils.staging(folder, "print-") as staged:
        try:
            pdf, _, _ = page_mod.print_page(
                body, template, template_path, "en", staged, "cv", manifest=templates.manifest(template_path),
                photo=photo, style=style)
        except (ValueError, html_pdf.PrintError):
            return {"error": "print_failed"}
        png = pdf_render.render_pdf_pages(pdf, staged)[0].read_bytes()
    utils.write_atomic(cached, png)
    for other in folder.glob("*.png"):
        if not other.name.startswith(cv_key):
            other.unlink(missing_ok=True)
    return _answer(png, own)
