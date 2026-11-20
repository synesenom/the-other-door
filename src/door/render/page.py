"""Page assembly for a CV or letter body (#355): the photo placed, the language's
typography, the body wrapped in the template and printed with the pinned Chromium (`html_pdf`). `commands/compile`
(a prepared job) and `commands/matches` (the CV as placed) all place a body through this module.
"""

import re
from pathlib import Path

from door import i18n
from door.core import photo as photo_mod
from door.core import templates, utils, workspace
from door.render import html_pdf, typography

# The CV photo (#605): the tailor writes `<<photo>>` where it wants one. After the guard has read the body, `compile`
# swaps it for this one trusted image of the copy of the profile's photo it puts beside the page (the template must
# style `.photo`, or it prints no photo), or for nothing. The body on disk keeps the token, so a recompile
# (`revise`) passes the guard again.
_PHOTO_TOKEN = "<<photo>>"
_PHOTO_CLASS = re.compile(r"\.photo(?![\w-])")
_COMMENTS = re.compile(r"/\*.*?\*/|<!--.*?-->", re.S)
PHOTO_FILES = {"jpeg": "photo.jpg", "png": "photo.png"}
_PHOTO_HTML = '<img class="photo" src="%s" alt="">'


def profile_photo(config: dict, posting: dict) -> Path | None:
    """The profile's photo (`config` is the raw config: a photo needs no valid profile around it), when the country
    of `posting` (else the profile's) lets a CV carry one and the file is a usable picture."""
    if not isinstance(config.get("photo"), str) or i18n.cv_conventions(posting, config).photo == "no":
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
    name = PHOTO_FILES[photo_mod.kind(source.read_bytes()[:16])]
    utils.write_atomic(output_dir / name, source.read_bytes())
    first, _, rest = body.partition(_PHOTO_TOKEN)
    return first + _PHOTO_HTML % name + rest.replace(_PHOTO_TOKEN, ""), name


def _page(body: str, template: str, folder: Path, *, photo: Path | None, language: str, style: str = "") -> tuple[str, str, str | None]:
    """The page `print_page` prints for a body: the photo placed (copied into `folder`), the language's
    typography, each entry heading's separator kept to the text before it, wrapped in `template`. Returns the page,
    the body as placed and the photo's file name (None when it was not placed).

    Raises:
        ValueError: the template cannot hold the body.
    """
    placed, name = _with_photo(body, template, folder, photo)
    return _wrap(template, _glue_separators(typography.apply(placed, language)), language, style), placed, name


_SEP_SPACE = re.compile(r'(<span class="sep">) ')


def _glue_separators(body: str) -> str:
    """`body` with the space that opens an entry heading's separator (`<span class="sep"> | </span>`) a no-break one:
    a heading too long for its line breaks after the separator, never before it (#246)."""
    return _SEP_SPACE.sub("\\1&#160;", body)


def print_page(body: str, template: str, lang: str, folder: Path, name: str, *, photo: Path | None = None,
               style: str = "") -> tuple[Path, str, str | None]:
    """`body` placed in `template` (its text) by `_page` and printed to `folder/<name>.pdf` with the pinned Chromium,
    the fonts (`templates.fonts`) served. Returns the pdf, the body as placed and the
    photo's file name in `folder` (None when it was not placed). `style` (`templates.style_css`) goes in the page's head.

    Raises:
        html_pdf.PrintError: the print failed.
        ValueError: the template cannot be used.
    """
    folder.mkdir(parents=True, exist_ok=True)
    html_text, placed, picture = _page(body, template, folder, photo=photo, language=lang, style=style)
    pdf = folder / f"{name}.pdf"
    html_pdf.print_html(folder, html_text, pdf, fonts=templates.fonts())
    return pdf, placed, picture


def _wrap(template: str, body: str, language: str, style: str = "") -> str:
    """`template` with its language and `body` in place, and the CSS `style` (if any) in a `<style>` before `</head>`.

    Raises:
        ValueError: the template has no `<<body>>` to put the body in.
    """
    if "<<body>>" not in template:
        raise ValueError("the template has no <<body>> to put the page in")
    if style:
        template = template.replace("</head>", f"<style>{style}</style></head>", 1)
    return template.replace("<<lang>>", language).replace("<<body>>", body)
