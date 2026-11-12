"""The packaged app's Python packages (#223): poetry.lock's main group as pip requirements, each pinned by
every hash the lock records and carrying its platform marker. Run by bundle-python.sh with any Python 3.11+:

    python3 app/scripts/lock_requirements.py poetry.lock > requirements.txt

`poetry export` would do the same but needs a plugin; this reads the lock directly (tomllib, no deps)."""

import sys
import tomllib
from pathlib import Path


def requirements(lock_path: Path) -> list[str]:
    data = tomllib.loads(Path(lock_path).read_text(encoding="utf-8"))
    lines = []
    for package in data.get("package", []):
        if "main" not in package.get("groups", ["main"]) or package.get("optional", False):
            continue
        line = f"{package['name']}=={package['version']}"
        markers = package.get("markers")
        if isinstance(markers, dict):  # one per group when a package is in several: the runtime's is main's
            markers = markers.get("main")
        if markers:
            line += f" ; {markers}"
        line += "".join(f" --hash={f['hash']}" for f in package.get("files", []))
        lines.append(line)
    return sorted(lines)


if __name__ == "__main__":
    print("\n".join(requirements(Path(sys.argv[1]))))
