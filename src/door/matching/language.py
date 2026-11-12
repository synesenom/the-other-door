"""Language pass (``scrape``, after dedup, before condense and prescreen): tag
each posting with the language it is written in, drop the ones not in the
profile's ``languages``, and give the kept non-English titles an English
``title_en``.

The language is detected offline from the description alone
(``door.i18n.detect_language``) and written as ``language`` (an ISO 639-1
code, or ``null`` when the text gives too little evidence). An ad in a language
the profile doesn't list (``languages``, default English) gets ``score=0.0``
and a ``"language: ..."`` reason, like a prefilter drop: it stays on disk,
counted as filtered out by `status`, but is never condensed, ranked or scored. So is
an ad whose language can't be detected, and an ad with no description at all
(``"no description"``: there is nothing to score or tailor it against). Kept titles in any other language than
English are translated by one ``claude -p`` call per
``BATCH_SIZE`` titles (Haiku by default, ``translate_model`` to change it), so
a scrape costs a call or two, not one per posting. Only the title is
translated: prescreen compares it with ``role_targets``; the matcher and the
tailor read the original description, whose exact wording ("dansk er en
fordel" vs "dansk er et krav") a translation could blur.

A failed or unavailable call leaves ``title_en`` unset and is counted, never
raised: prescreen then falls back to the original title.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from door import i18n
from door.core import claude_cli, installers, usage
from door.matching import scorer

DEFAULT_MODEL = "haiku"
BATCH_SIZE = 50
_TIMEOUT_S = 300

TITLES_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "titles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "title_en": {"type": "string"}},
                "required": ["id", "title_en"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["titles"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You translate job titles into English. The next message is a JSON list of "
    "job postings, each with an id, a title and the ISO 639-1 code of the "
    "language it is written in. For each one, return the title an English-"
    "language job board would use for the same role. Keep company, product and "
    "technology names unchanged, and do not add seniority, specialisms or other "
    "details that are not in the original. Return every id exactly once. "
    "Respond only with structured output matching the provided JSON schema."
)


def build_argv(model: str) -> list[str]:
    return scorer.build_claude_argv(SYSTEM_PROMPT, model, TITLES_SCHEMA)


def parse_output(stdout: str) -> dict[str, str]:
    """``{id: title_en}`` from a call's result envelope (``claude_cli.read_stream``). Raises
    ``ValueError`` on anything malformed."""
    data = json.loads(scorer._parse_envelope(stdout))
    if not isinstance(data, dict) or not isinstance(data.get("titles"), list):
        raise ValueError("structured result must be an object with a 'titles' array")
    titles: dict[str, str] = {}
    for item in data["titles"]:
        if not isinstance(item, dict):
            raise ValueError("each title must be an object")
        job_id, title_en = item.get("id"), item.get("title_en")
        if isinstance(job_id, str) and isinstance(title_en, str) and title_en.strip():
            titles[job_id] = title_en.strip()
    return titles


def _run_claude(
    argv: list[str],
    stdin: str,
    *,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., object] = subprocess.run,
) -> str | None:
    """Run one ``claude -p`` call; its stdout, or ``None`` when the CLI is
    missing or the call fails (replaced in tests by tests/conftest.py)."""
    claude = installers.find_claude(which)
    if claude is None:
        return None
    argv = [claude, *argv[1:]]
    try:
        proc = run(
            argv,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            env=claude_cli.env(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def _load(path: Path) -> dict | None:
    try:
        return json.loads(Path(path).read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _save(path: Path, data: dict) -> None:
    try:
        Path(path).write_text(json.dumps(data, indent=2, default=str))
    except OSError:
        pass


def _accepted_codes(config: dict) -> set[str]:
    codes = {i18n.language_code(name) for name in config.get("languages") or []}
    return {c for c in codes if c} or {"en"}


def filter_languages(
    paths: list[Path],
    config: dict,
    *,
    run_fn: Callable[[list[str], str], str | None] | None = None,
) -> tuple[list[Path], dict]:
    """Write ``language`` to every posting in ``paths``, drop the ones with no
    description or in a language outside the profile's ``languages``, and write ``title_en`` to
    the kept non-English ones (unless ``translate_titles`` is false).

    Returns ``(kept paths, {"languages": {code or "unknown": count},
    "dropped": n, "translated": n, "failed_batches": n})``.
    """
    run = run_fn or _run_claude
    accepted = _accepted_codes(config)
    counts: dict[str, int] = {}
    kept: list[Path] = []
    dropped = 0
    pending: list[tuple[Path, dict]] = []

    for path in paths:
        data = _load(path)
        if data is None:  # unreadable: not this pass's to drop
            kept.append(Path(path))
            continue
        if "language" not in data:
            data["language"] = i18n.detect_language(data.get("description") or "")
            _save(path, data)
        code = data["language"]
        counts[code or "unknown"] = counts.get(code or "unknown", 0) + 1
        # No description: nothing to score or tailor against. Otherwise an ad
        # whose language is unknown is dropped like one in an unlisted language.
        if not (data.get("description") or "").strip():
            reason = "no description"
        elif code not in accepted:
            reason = f"language: {i18n.language_label(code)} not in languages"
        else:
            reason = None
        if reason:
            data["score"] = 0.0
            data["score_reason"] = reason
            _save(path, data)
            dropped += 1
            continue
        kept.append(Path(path))
        if code not in (None, "en") and not data.get("title_en"):
            pending.append((Path(path), data))

    translated = 0
    failed_batches = 0
    if pending and config.get("translate_titles", True):
        argv = build_argv(config.get("translate_model") or DEFAULT_MODEL)
        for start in range(0, len(pending), BATCH_SIZE):
            batch = pending[start : start + BATCH_SIZE]
            items = [
                {"id": data.get("id") or path.stem, "title": data.get("title", ""), "language": data["language"]}
                for path, data in batch
            ]
            stdout = run(argv, json.dumps(items, ensure_ascii=False))
            envelope, limits = claude_cli.read_stream(stdout)
            stdout = envelope or stdout
            try:
                titles = parse_output(stdout) if stdout is not None else None
            except ValueError:
                titles = None
            usage.record("title_translation", stdout, limits=limits)
            if titles is None:
                failed_batches += 1
                continue
            for (path, data), item in zip(batch, items):
                title_en = titles.get(item["id"])
                if title_en:
                    data["title_en"] = title_en
                    _save(path, data)
                    translated += 1

    stats = {"languages": counts, "dropped": dropped, "translated": translated, "failed_batches": failed_batches}
    return kept, stats
