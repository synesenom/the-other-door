"""Where the LaTeX templates are read from (#56).

`cv.template.tex` and `cover-letter.template.tex` (and the `fonts/` they load) ship with the code in `profile.example/`,
so a release that changes the tailor's macros never breaks a profile that holds an older copy. A user who wants their own
styling keeps a file of that name in `profile/` (or names one in `config.json`); it wins.
"""

from __future__ import annotations

from pathlib import Path

from door.core import workspace

# The config key of each template and the file it defaults to.
FILES = {"cv_template": "cv.template.tex", "cover_letter_template": "cover-letter.template.tex"}


def resolve(key: str, config: dict | None = None, profile_dir: Path | None = None, example_dir: Path | None = None) -> Path:
    """The template for ``key`` (``cv_template`` or ``cover_letter_template``), as an absolute path.

    The file `config` names (relative paths from the data folder) when it is there; else the file of that name the user
    put in `profile/`; else the code's own in `profile.example/`.
    """
    name = FILES[key]
    named = (config or {}).get(key)
    if named:
        path = Path(named)
        path = path if path.is_absolute() else workspace.HOME / path
        if path.is_file():
            return path
    own = Path(profile_dir if profile_dir is not None else workspace.PROFILE_DIR) / name
    if own.is_file():
        return own
    return Path(example_dir if example_dir is not None else workspace.PROFILE_EXAMPLE_DIR) / name
