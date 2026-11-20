"""One cached, checked model answer (#433): what `cv_read` and `tailoring.facts` share.

`cached_answer` returns the checked result for a key: the cached answer of this version when it is there and still
holds, else the model's (`ask`), held to `check` and asked once more when it does not hold (the model's answers vary),
then cached. A failed call or an answer that does not hold twice is the caller's error and one problem-log line; nothing
is cached then and there is no fallback. Where answers are kept is a store (`DirStore`: one file per key, the newest
`keep` of them); a caller with its own file (`facts.json`) brings its own.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Protocol

from door.core import claude_cli, problem_log, utils


class Store(Protocol):
    def read(self, key: str) -> Any: ...
    def write(self, key: str, record: dict) -> None: ...
    def drop(self, key: str) -> None: ...


class DirStore:
    """`<dir>/<key>.json` holding `{version, rows?, answer}`; `write` keeps the `keep` most recently written."""

    def __init__(self, folder: Path, keep: int = 20):
        self.folder, self.keep = Path(folder), keep

    def _file(self, key: str) -> Path:
        return self.folder / f"{key}.json"

    def read(self, key: str) -> Any:
        try:
            return json.loads(self._file(key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def write(self, key: str, record: dict) -> None:
        utils.write_json_atomic(self._file(key), record, indent=None)
        try:
            stale = sorted(self.folder.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)[self.keep:]
            for old in stale:
                old.unlink(missing_ok=True)
        except OSError:
            pass  # the cache is a convenience: a file that will not go is left

    def drop(self, key: str) -> None:
        self._file(key).unlink(missing_ok=True)


def cached_answer(*, key: str, version: int, ask: Callable[[], dict], check: Callable[[dict], Any],
                  error: type[Exception], unreached: Callable[[Exception], Exception], label: str, store: Store,
                  tag: str | None = None) -> Any:
    """The result of `check` on the answer for `key`.

    Args:
        key: Names the cached answer in the `store`.
        version: A cached answer of another version is a miss.
        ask: The one model call; raises `claude_cli.ClaudeError`, which `unreached` turns into the caller's error.
        check: Holds an answer to what code can verify: returns the result, raises `error` when it does not hold.
            A cached answer is checked again on every read; one that no longer holds is dropped and asked again.
        error: What `check` raises.
        unreached: The caller's error for a failed call.
        label: The problem log's name for this failure.
        tag: Also part of a hit (the digest of what the answer was made for), kept as `rows`.

    Raises:
        `error` (or what `unreached` returns): the call failed or its answer did not hold twice.
    """
    record = store.read(key)
    if (isinstance(record, dict) and record.get("version") == version and record.get("rows") == tag
            and isinstance(record.get("answer"), dict)):
        try:
            return check(record["answer"])
        except error:
            store.drop(key)
    try:
        for attempt in (1, 2):
            try:
                answer = ask()
            except claude_cli.ClaudeError as exc:
                raise unreached(exc) from None
            try:
                result = check(answer)
                break
            except error:
                if attempt == 2:
                    raise
    except Exception as exc:
        problem_log.failure(label, getattr(exc, "detail", "") or str(exc))
        raise
    store.write(key, {"version": version, **({"rows": tag} if tag is not None else {}), "answer": answer})
    return result
