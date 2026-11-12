"""Set The other door's one version (#224) in pyproject.toml, src/door/version.py, app/package.json and its lock:

    python3 scripts/set_version.py 0.2.0

A release is then a tag of the same number (`git tag v0.2.0`). tests/core/test_version_unit.py fails when the
three differ."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def set_version(new: str, root: Path = ROOT) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", new):
        raise SystemExit(f"not a version: {new!r} (want X.Y.Z)")
    pyproject = root / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    pyproject.write_text(re.sub(r'(?m)^version = "[^"]+"', f'version = "{new}"', text, count=1), encoding="utf-8")
    module = root / "src" / "door" / "version.py"
    module.write_text(re.sub(r'VERSION = "[^"]+"', f'VERSION = "{new}"', module.read_text(encoding="utf-8")), encoding="utf-8")
    package = root / "app" / "package.json"
    data = json.loads(package.read_text(encoding="utf-8"))
    data["version"] = new
    package.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lock = root / "app" / "package-lock.json"
    if lock.exists():  # npm keeps the app's own version in its lock too
        data = json.loads(lock.read_text(encoding="utf-8"))
        data["version"] = new
        data.setdefault("packages", {}).setdefault("", {})["version"] = new
        lock.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    set_version(sys.argv[1] if len(sys.argv) > 1 else "")
