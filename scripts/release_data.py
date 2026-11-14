"""What a release read back from its own data (#57): the snapshot, its normal form and the comparison.

Used from two sides, so it imports nothing from `door` at load time and needs only the standard library:

- `save_release_data.py` runs `python release_data.py snapshot <home>` inside a worktree of a release tag, so that
  release's own code reads the data it just wrote (`expected.json`);
- `tests/release/` imports it and runs `snapshot` on the current code, after `migrations.upgrade_all`, then
  `compare`s the two.

`snapshot` calls the tools a user reads the data back with (`show_profile`, `list_companies`, `list_matches`, `show`
for each job, `status_summary`, `list_stories`), as functions of `door.mcp_server`, the same on every release.
"""

from __future__ import annotations

import fnmatch
import json
import re
import sys
from pathlib import Path

# What a tool returns that is not the user's data and so not part of what a release must read back: `show_profile`'s
# catalogue (every known city with its boards, the supported languages, ...: it grows with every release) and
# `status_summary`'s Google Drive block (whether this build has Google's client, this computer's connection).
CODE_OWNED_KEYS = {"show_profile": ("options",), "status_summary": ("drive",)}

_TIME = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?([+-]\d{2}:?\d{2}|Z)?")


def normalise(value, home: Path):
    """*value* with the data folder's path as ``<home>`` and every time of day as ``<time>``.

    A time is volatile (a "last run" read against now, a clock in a message) and the saved ones are fake; the key
    must still be there and still hold a time.
    """
    homes = sorted({str(home), str(Path(home).resolve())}, key=len, reverse=True)

    def walk(item):
        if isinstance(item, dict):
            return {key: walk(sub) for key, sub in item.items()}
        if isinstance(item, (list, tuple)):
            return [walk(sub) for sub in item]
        if isinstance(item, str):
            for prefix in homes:
                item = item.replace(prefix, "<home>")
            return _TIME.sub("<time>", item)
        return item

    return walk(value)


def snapshot(home: Path) -> dict:
    """What the running code reads back from the data folder *home* (`workspace` must already point at it)."""
    from door import mcp_server as tools
    from door.core import selection, workspace

    out: dict = {}
    profile = tools.show_profile()
    for key in CODE_OWNED_KEYS["show_profile"]:
        profile.pop(key, None)
    out["show_profile"] = profile
    out["list_companies"] = tools.list_companies()
    out["list_stories"] = tools.list_stories()
    out["list_matches"] = tools.list_matches()
    out["list_matches_closed"] = tools.list_matches(closed=True)
    out["list_matches_ongoing"] = tools.list_matches(ongoing=True)
    ids = sorted(p["id"] for p in selection.read_postings(workspace.JOBS_DIR))
    out["show"] = {job_id: tools.show(job_id) for job_id in ids}
    summary = tools.status_summary()
    for key in CODE_OWNED_KEYS["status_summary"]:
        summary.pop(key, None)
    out["status_summary"] = summary
    return normalise(json.loads(json.dumps(out, default=str)), home)


def _walk(expected, actual, path: str, found: list[str]) -> None:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            found.append(f"{path}: was an object, now {type(actual).__name__}")
            return
        for key, value in expected.items():
            sub = f"{path}.{key}" if path else key
            if key not in actual:
                found.append(f"{sub}: missing (was {_short(value)})")
            else:
                _walk(value, actual[key], sub, found)
    elif isinstance(expected, list):
        if not isinstance(actual, list):
            found.append(f"{path}: was a list, now {type(actual).__name__}")
        elif len(expected) != len(actual):
            found.append(f"{path}: {len(expected)} items before, {len(actual)} now")
        else:
            for index, (old, new) in enumerate(zip(expected, actual)):
                _walk(old, new, f"{path}[{index}]", found)
    elif expected != actual:
        found.append(f"{path}: {_short(expected)} became {_short(actual)}")


def _short(value) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= 80 else text[:77] + "..."


def differences(expected, actual) -> list[str]:
    """Every place where *actual* does not read back what *expected* did, as ``path: what`` lines.

    A key *expected* has must be in *actual* with the same value (recursively; a list keeps its length and order);
    a key only *actual* has is new, and fine. A path is dotted, a list item ``[index]``.
    """
    found: list[str] = []
    _walk(expected, actual, "", found)
    return found


def unlisted(found: list[str], changes) -> list[str]:
    """The *found* lines whose path is neither in *changes* nor below one of them.

    A change is a glob over the dotted path (``show_profile.config.cv_template``; ``*`` stands for any text, a list
    index included) and covers everything under it.
    """
    patterns = [str(change).replace("[", "[[]") for change in changes]  # a list item's brackets are text, not a class

    def covered(path: str) -> bool:
        return any(
            fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(path, pattern + ".*")
            or fnmatch.fnmatchcase(path, pattern + "[[]*")
            for pattern in patterns
        )

    return [line for line in found if not covered(line.split(": ", 1)[0])]


def main(argv: list[str]) -> int:
    """``snapshot <home>``: print the snapshot of the data folder *home* as JSON (run with that release's `src` on PYTHONPATH)."""
    if len(argv) != 2 or argv[0] != "snapshot":
        sys.stderr.write("usage: release_data.py snapshot <home>\n")
        return 2
    home = Path(argv[1]).resolve()
    from door.core import lock, workspace

    for name, relative in (("PROFILE_DIR", "profile"), ("JOBS_DIR", "jobs"), ("BACKUPS_DIR", "backups"), ("UPSKILL_DIR", "upskill")):
        setattr(workspace, name, home / relative)
    workspace.HOME = home
    for hook in ("pre_acquire_hook", "post_release_hook"):  # never a Google Drive: the data is a sample
        if hasattr(lock, hook):
            setattr(lock, hook, lambda *args, **kwargs: None)
    sys.stdout.write(json.dumps(snapshot(home), indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
