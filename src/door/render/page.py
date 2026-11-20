"""Page assembly for a CV or letter body (#355): the photo placed, the template's two columns, the language's
typography, the body wrapped in the template and printed with the pinned Chromium (`html_pdf`). `commands/compile`
(a prepared job) and `commands/matches` (the CV as placed) all place a body through this module.
"""

import re
from pathlib import Path

from door import i18n
from door.core import photo as photo_mod
from door.core import templates, utils, workspace
from door.render import html_doc, html_pdf, typography

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


def _page(body: str, template: str, folder: Path, *, photo: Path | None, columns: templates.Columns | None,
         language: str) -> tuple[str, str, str | None]:
    """The page `print_page` prints for a body: the photo placed (copied into `folder`), the two columns, the language's
    typography, each entry heading's separator kept to the text before it, wrapped in `template`. Returns the page,
    the body as placed and the photo's file name (None when it was not placed).

    Raises:
        ValueError: the template cannot hold the body.
    """
    built, name = _with_photo(body, template, folder, photo)
    placed = place_columns(built, columns)
    return _wrap(template, _glue_separators(typography.apply(placed, language)), language), placed, name


_SEP_SPACE = re.compile(r'(<span class="sep">) ')


def _glue_separators(body: str) -> str:
    """`body` with the space that opens an entry heading's separator (`<span class="sep"> | </span>`) a no-break one:
    a heading too long for its line breaks after the separator, never before it (#246)."""
    return _SEP_SPACE.sub("\\1&#160;", body)


def print_page(body: str, template: str, assets_of: Path, lang: str, folder: Path, name: str, *,
               columns: templates.Columns | None = None, photo: Path | None = None) -> tuple[Path, str, str | None]:
    """`body` placed in `template` (its text) by `_page` and printed to `folder/<name>.pdf` with the pinned Chromium,
    the fonts and icons that the template file `assets_of` names served. Returns the pdf, the body as placed and the
    photo's file name in `folder` (None when it was not placed).

    Raises:
        html_pdf.PrintError: the print failed.
        ValueError: the template or its manifest cannot be used.
    """
    folder.mkdir(parents=True, exist_ok=True)
    assets = templates.assets(assets_of)
    html_text, placed, picture = _page(body, template, folder, photo=photo, language=lang, columns=columns)
    pdf = folder / f"{name}.pdf"
    html_pdf.print_html(folder, html_text, pdf, assets=assets)
    return pdf, placed, picture


_H2 = re.compile(r"(?=<h2[\s>])")


def place_columns(body: str, columns: templates.Columns | None) -> str:
    """The CV `body` with its sections in the template's two columns (#147): what comes before the first `<h2>` after
    the header (the notes, the photo, the whole header: an `<h2>` inside it is the header's, #242) as it is, then
    `<div class="main">` and `<div class="side">` (`html_doc.columns` reads them back), each section in the order the
    body has it. A section goes to the side when its heading is, whole and without case, a title of one of
    the template's ``columns.side`` kinds in any supported language (a CV's headings are in its own language, whatever
    the ad's, #227); any other goes to the main column.
    `body` itself when the template has no side column."""
    if columns is None or not columns.side:
        return body
    cut = body.find("</header>") + len("</header>") if "</header>" in body else 0
    first, *sections = _H2.split(body[cut:])
    first = body[:cut] + first
    main, side = [], []
    for section in sections:
        heading = (html_doc.headings(section) or [""])[0]
        (side if i18n.cv_section_kind(heading, columns.side) else main).append(section)
    return f'{first}{html_doc.MAIN}{"".join(main)}</div>{html_doc.SIDE}{"".join(side)}</div>'


def placed_cv(body: str, config: dict) -> str:
    """The CV `body` as its printed page reads it (`place_columns` by the resolved CV template's manifest); `body` itself when the template has no side column or cannot be read."""
    try:
        columns = (templates.manifest(templates.resolve("cv_template", config)) or templates.Manifest()).columns
    except (OSError, ValueError):
        columns = None
    return place_columns(body, columns)


def _wrap(template: str, body: str, language: str) -> str:
    """`template` with its language and `body` in place.

    Raises:
        ValueError: the template has no `<<body>>` to put the body in.
    """
    if "<<body>>" not in template:
        raise ValueError("the template has no <<body>> to put the page in")
    return template.replace("<<lang>>", language).replace("<<body>>", body)
