"""Where the HTML templates are read from (#56, #146).

`cv.template.html` and `cover-letter.template.html` (and the `fonts/` they load) ship with the code in `profile.example/`,
so a release that changes the building blocks never breaks a profile that holds an older copy. A user who wants their own
styling keeps a file of that name in `profile/` (or names one in `config.json`); it wins. A file that is not `.html`
(an old LaTeX template) is never read: a browser cannot print it.
"""

from __future__ import annotations

from pathlib import Path

from door.core import workspace

# The config key of each template and the file it defaults to.
FILES = {"cv_template": "cv.template.html", "cover_letter_template": "cover-letter.template.html"}


def resolve(key: str, config: dict | None = None, profile_dir: Path | None = None, example_dir: Path | None = None) -> Path:
    """The template for ``key`` (``cv_template`` or ``cover_letter_template``), as an absolute path.

    The file `config` names (relative paths from the data folder) when it is there; else the file of that name the user
    put in `profile/`; else the code's own in `profile.example/`.
    """
    name = FILES[key]
    named = (config or {}).get(key)
    if named and str(named).lower().endswith(".html"):
        path = Path(named)
        path = path if path.is_absolute() else workspace.HOME / path
        if path.is_file():
            return path
    own = Path(profile_dir if profile_dir is not None else workspace.PROFILE_DIR) / name
    if own.is_file():
        return own
    return Path(example_dir if example_dir is not None else workspace.PROFILE_EXAMPLE_DIR) / name


# The CV style a profile picks (#465): `cv_accent` colours the section headings and the rule under the name, `cv_fonts`
# names a pair of fonts. Both are fixed tables, the one source of the `Profile` choices, the CSS and the app's pickers
# (`show_profile`'s `options.cv_styles`): a config value is only ever a key here, never CSS.
INK = "#1E1A16"  # the shipped templates' ink
ACCENTS = {"none": INK, "navy": "#1f3a5f", "blue": "#2f55c8", "teal": "#0f6466", "forest": "#2f6b3a", "burgundy": "#8a1c3c",
           "plum": "#5e2a72", "slate": "#475569", "rust": "#a1401a"}  # `none`: ink headings and a hairline rule; `blue` is the app's own
DEFAULT_ACCENT, DEFAULT_FONTS = "blue", "door"  # what the templates' own CSS already says
NO_ACCENT = "--heading:var(--ink);--rule:var(--hairline)"
# pair: (heading font, text font, heading weight, strong weight)
FONT_PAIRS = {"door": ('"Young Serif", serif', "Figtree, sans-serif", 400, 600),
              "editorial": ('"Playfair Display", serif', "Lato, sans-serif", 700, 700),
              "friendly": ("Montserrat, sans-serif", "Merriweather, serif", 700, 700),
              "plain": ("Figtree, sans-serif", "Figtree, sans-serif", 600, 600)}


def cv_styles() -> dict:
    """The tables as the app's pickers read them: ``{"accents": {name: hex}, "fonts": {name: {heading, text, weight}}}``."""
    return {"accents": dict(ACCENTS),
            "fonts": {name: {"heading": h, "text": t, "weight": w} for name, (h, t, w, _) in FONT_PAIRS.items()}}


def style_css(config: dict | None) -> str:
    """The `:root{...}` block that sets the shipped templates' style variables from `cv_accent` and `cv_fonts`; "" for the
    defaults (blue and the door fonts: the templates' own CSS). A value that is not a name in the tables (the config is read
    tolerantly) counts as the default."""
    config = config or {}
    accent, fonts = config.get("cv_accent"), config.get("cv_fonts")
    rules = []
    if accent == "none":
        rules.append(NO_ACCENT)
    elif isinstance(accent, str) and accent in ACCENTS and accent != DEFAULT_ACCENT:
        rules.append(f"--heading:{ACCENTS[accent]};--rule:{ACCENTS[accent]}")
    if isinstance(fonts, str) and fonts in FONT_PAIRS and fonts != DEFAULT_FONTS:
        heading, text, weight, strong = FONT_PAIRS[fonts]
        rules.append(f"--heading-font:{heading};--text-font:{text};--heading-weight:{weight};--strong:{strong}")
    return ":root{" + ";".join(rules) + "}" if rules else ""


def _fonts_dir() -> Path:
    """The folder the templates' `/fonts/...` is served from: the profile's own when it holds TrueType files, else the
    code's. (Chromium writes a CFF `.otf` font into a PDF as nameless text.)"""
    own = workspace.PROFILE_DIR / "fonts"
    if own.is_dir() and any(own.glob("*.ttf")):
        return own
    return workspace.PROFILE_EXAMPLE_DIR / "fonts"


def fonts() -> list[Path]:
    """The fonts the print serves beside the page: the TrueType files `_fonts_dir` finds."""
    return sorted(_fonts_dir().glob("*.ttf"))
