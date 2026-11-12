"""`jobs/skill_aliases.json`: ``{variant: canonical | null}``, hand-editable (``null`` = not a skill).

Read by `market` (which also writes it) and by the facts check (which only reads).
"""

import json
from pathlib import Path

FILE = "skill_aliases.json"


def load(path: Path) -> tuple[dict, str | None]:
    """(``{lowercase variant: canonical | None}``, warning). A missing file is empty; a corrupt one
    (bad JSON, a value that is not text or null) is empty with a warning, and is never rewritten."""
    if not path.exists():
        return {}, None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not all(v is None or isinstance(v, str) for v in raw.values()):
            raise ValueError("expected {variant: canonical or null}")
    except (OSError, ValueError) as exc:
        return {}, f"{path.name} could not be read ({exc}); skill names are counted as written, nothing grouped or saved"
    return {str(k).strip().lower(): (v.strip() if v else None) for k, v in raw.items()}, None


def load_for(jobs_dir: Path) -> tuple[dict, str | None]:
    return load(Path(jobs_dir) / FILE)
