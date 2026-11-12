"""`enrich`: propose additions to profile/cv.md from public URLs, then add the
ones the user picks.

Two phases, one call each: *propose* (one `claude -p` call that fetches the
URLs and returns bullets evidenced on them, saved to
`profile/.enrich_proposals.json`, nothing written to the CV) and *apply*
(insert the chosen proposals under their `##` sections, keeping a `.bak`).
`/expand` in a conversation and `enrich` in a shell make the same two calls.
"""

import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

import click

from door.commands import _common as common
from door.commands import _prompts
from door.core import claude_cli, workspace

_DEFAULT_MODEL = "sonnet"
_PROPOSALS_FILE = ".enrich_proposals.json"

_RULES = (
    "You enrich a job seeker's CV (Markdown) from their public pages. " + common._WEBFETCH_RULES + " "
    "Propose additions that are directly evidenced in the fetched text (quote or paraphrase "
    "accurately; never invent, never embellish), that are not already in the CV, and that "
    "are relevant to the role targets. Each proposal has `section` (the `##` section of the "
    "CV it belongs in: an existing one when it fits, otherwise a new short heading), `text` "
    "(one bullet ready to paste, without the leading dash) and `source` (the URL it came "
    "from). List every URL you could not fetch under `unreachable`. Answer with the JSON only."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"section": {"type": "string"}, "text": {"type": "string"}, "source": {"type": "string"}},
                "required": ["section", "text", "source"],
            },
        },
        "unreachable": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["proposals", "unreachable"],
}

_BULLET_RE = re.compile(r"^\s*[-*]\s+")
_NOT_A_WORD = re.compile(r"[^\w]+")
# How alike a proposal and a CV line must be, word for word, to be the same thing said again.
_SAME_LINE = 0.9


def _words(text: str) -> str:
    """`text` as its words only: lowercase, with punctuation and Markdown marks as spaces."""
    return " ".join(_NOT_A_WORD.sub(" ", text.lower().replace("_", " ")).split())


def _in_cv(text: str, cv_words: str, cv_lines: list[str]) -> bool:
    """Whether the CV already says `text`: its words appear in the CV, or a line of the CV is nearly the same.

    What a read of the pages proposes is compared this way, so reading them again (or Claude wording a
    thing a little differently) adds nothing twice; a proposal that says more than a line stays."""
    words = _words(text)
    if f" {words} " in f" {cv_words} ":
        return True
    return any(difflib.SequenceMatcher(None, words, line).ratio() >= _SAME_LINE for line in cv_lines)


def _clean_proposals(raw, cv_text: str) -> list[dict]:
    """Well-formed, de-duplicated proposals not already in the CV, numbered from 1."""
    seen = set()
    cleaned = []
    cv_words = _words(cv_text)
    cv_lines = [w for w in (_words(line) for line in cv_text.splitlines()) if w]
    for item in raw:
        if not isinstance(item, dict):
            continue
        section = " ".join(str(item.get("section") or "").lstrip("#").split())
        text = _BULLET_RE.sub("", " ".join(str(item.get("text") or "").split()))
        if not section or not text:
            continue
        key = (section.lower(), _words(text))
        if key in seen or _in_cv(text, cv_words, cv_lines):
            continue
        seen.add(key)
        cleaned.append({"n": len(cleaned) + 1, "section": section, "text": text, "source": str(item.get("source") or "")})
    return cleaned


def _insert(cv_text: str, section: str, text: str) -> str:
    """`cv_text` with `- text` added under `## section`: after the section's last
    bullet, after its prose when it has none, or in a new section at the end."""
    lines = cv_text.split("\n")
    heading_re = re.compile(rf"^##\s+{re.escape(section)}\s*$", re.IGNORECASE)
    start = next((i for i, line in enumerate(lines) if heading_re.match(line)), None)
    bullet = f"- {text}"
    if start is None:
        body = cv_text.rstrip("\n")
        return (f"{body}\n\n" if body else "") + f"## {section}\n\n{bullet}\n"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    last_bullet = next((i for i in range(end - 1, start, -1) if _BULLET_RE.match(lines[i])), None)
    if last_bullet is not None:
        lines.insert(last_bullet + 1, bullet)
    else:
        last_content = next((i for i in range(end - 1, start, -1) if lines[i].strip()), start)
        lines[last_content + 1:last_content + 1] = ["", bullet]
    result = "\n".join(lines)
    return result if result.endswith("\n") else result + "\n"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _propose(urls, *, config, cv_path, profile_dir, model, timeout_s) -> dict:
    urls = [u.strip() for u in (urls or []) if u and u.strip()] or list(config.get("enrich_sources") or [])
    if not urls:
        raise ValueError("no URLs to read: pass some, or list them under enrich_sources in profile/config.json")
    if not cv_path.is_file():
        raise FileNotFoundError(f"{cv_path} not found (profile/cv.md): set up the profile first")
    cv_text = cv_path.read_text(encoding="utf-8")

    prompt = (
        f"Role targets: {', '.join(config.get('role_targets') or [])}\n\n"
        f"Current CV (profile/cv.md):\n<<<\n{cv_text}\n>>>\n\n"
        "Read these pages:\n" + "\n".join(urls) + "\n"
    )
    answer = claude_cli.ask(
        _RULES, prompt, model=model or _DEFAULT_MODEL, feature="enrich", schema=_SCHEMA, allowed_tools=("WebFetch",),
        timeout_s=timeout_s, profile_dir=profile_dir,
    )
    if not isinstance(answer.get("proposals"), list):
        raise claude_cli.ClaudeError("claude's answer has no `proposals` list")
    proposals = _clean_proposals(answer["proposals"], cv_text)
    unreachable = [str(u) for u in answer.get("unreachable") or [] if u]
    result = {"outcome": "proposed" if proposals else "nothing_new", "urls": urls, "proposals": proposals, "unreachable": unreachable}
    proposals_path = profile_dir / _PROPOSALS_FILE
    if proposals:
        proposals_path.write_text(
            json.dumps({"cv_path": str(cv_path), "cv_digest": _digest(cv_text), "proposals": proposals}, indent=2),
            encoding="utf-8",
        )
        result["proposals_path"] = str(proposals_path)
    elif proposals_path.exists():
        proposals_path.unlink()
    return result


def _apply(apply, all_, *, profile_dir) -> dict:
    proposals_path = profile_dir / _PROPOSALS_FILE
    if not proposals_path.is_file():
        raise FileNotFoundError("no proposals to apply: run `enrich` (with URLs) first")
    saved = json.loads(proposals_path.read_text(encoding="utf-8"))
    proposals = saved["proposals"]
    cv_path = Path(saved["cv_path"])
    cv_text = cv_path.read_text(encoding="utf-8") if cv_path.is_file() else ""
    if _digest(cv_text) != saved["cv_digest"]:
        raise ValueError(f"{cv_path} changed since the proposals were made; run `enrich` again")

    if all_:
        chosen = proposals
    else:
        bad = [n for n in apply if not 1 <= n <= len(proposals)]
        if bad:
            raise ValueError(f"no proposal {', '.join(map(str, bad))}: pick numbers in 1-{len(proposals)}")
        wanted = set(apply)
        chosen = [p for p in proposals if p["n"] in wanted]

    new_text = cv_text
    for proposal in chosen:
        new_text = _insert(new_text, proposal["section"], proposal["text"])
    backup = common._write_with_backup(cv_path, new_text)
    proposals_path.unlink()
    return {"outcome": "applied", "added": chosen, "cv_path": str(cv_path), "backup": str(backup) if backup else None}


def _enrich_core(
    urls: list[str] | None = None,
    *,
    apply: list[int] | None = None,
    all: bool = False,
    model: str | None = None,
    profile_dir: Path | None = None,
    timeout_s: float = 600,
) -> dict:
    """Propose additions to the CV from `urls` (default: the profile's
    `enrich_sources`), or — with `apply` (proposal numbers) or `all` — add the
    proposals of the previous call to the CV.

    Returns:
        Propose: ``{"outcome": "proposed" | "nothing_new", "urls", "proposals":
        [{"n", "section", "text", "source"}], "unreachable", "proposals_path"?}``.
        Apply: ``{"outcome": "applied", "added", "cv_path", "backup"}``.

    Raises:
        FileNotFoundError, ConfigError: no or invalid profile/config.json; no
            CV; nothing proposed yet (apply).
        ValueError: no URLs; URLs together with apply/all; a bad number; the
            CV changed since the proposals were made.
        claude_cli.ClaudeError: the `claude -p` call failed or answered
            something else.
    """
    if profile_dir is None:
        profile_dir = workspace.PROFILE_DIR
    config = common._load_config(profile_dir)
    if apply or all:
        if urls:
            raise ValueError("pass URLs to propose, or apply/all to add the last proposals, not both")
        return _apply(apply or [], all, profile_dir=profile_dir)
    return _propose(
        urls, config=config, cv_path=common._cv_path(config, profile_dir), profile_dir=profile_dir,
        model=model, timeout_s=timeout_s,
    )


def _numbers(text: str) -> list[int]:
    """"1 3" / "1,3" -> [1, 3]; ValueError for anything else."""
    try:
        numbers = [int(part) for part in re.split(r"[,\s]+", text.strip()) if part]
    except ValueError:
        raise ValueError(f"expected numbers such as 1,3 — got {text!r}") from None
    if not numbers:
        raise ValueError("expected at least one number")
    return numbers


def _echo_proposals(result: dict) -> None:
    for url in result["unreachable"]:
        click.echo(f"Could not fetch {url} — skipping.")
    if not result["proposals"]:
        return
    click.echo(f"Found {len(result['proposals'])} potential addition(s):")
    for p in result["proposals"]:
        click.echo(f"  {p['n']}. [{p['section']}] {p['text']}")
        if p["source"]:
            click.echo(f"     Source: {p['source']}")


def _echo_applied(result: dict) -> None:
    click.echo(
        f"Added {len(result['added'])} item(s) to {common._display_path(result['cv_path'])}"
        + (f" (previous version: {common._display_path(result['backup'])})" if result["backup"] else "")
        + "."
    )
    for a in result["added"]:
        click.echo(f"  [{a['section']}] {a['text']}")
    click.echo("Review the changes before your next run.")


@click.command()
@click.argument("urls", nargs=-1)
@click.option(
    "--apply", "apply", default=None, metavar="NUMBERS", help="Add these proposals from the last run (e.g. 1,3) and stop.",
    callback=lambda ctx, param, value: None if value is None else _numbers(value),
)
@click.option("--all", "all_", is_flag=True, default=False, help="Add every proposal from the last run.")
@click.option("--model", default=None, help=f"Claude model to read the pages with (default: {_DEFAULT_MODEL}).")
def enrich(urls: tuple[str, ...], apply: list[int] | None, all_: bool, model: str | None):
    """Propose additions to profile/cv.md from public URLS (default: the
    profile's enrich_sources), then add the ones you pick.

    One `claude -p` call reads the pages; nothing is written until you choose.
    On a terminal it asks which proposals to add; elsewhere it prints them
    and `enrich --apply 1,3` (or `--all`) adds them.
    """
    try:
        result = _enrich_core(list(urls), apply=apply, all=all_, model=model, profile_dir=workspace.PROFILE_DIR)
        if result["outcome"] == "applied":
            _echo_applied(result)
            return
        _echo_proposals(result)
        if not result["proposals"]:
            click.echo("Nothing new found across all sources.")
            return
        if not common._stdout_is_tty():
            click.echo("Add some with `enrich --apply 1,3`, or all of them with `enrich --all`.")
            return
        answer = _prompts.text("apply", "Which items do you want to add? (numbers such as 1 3, all, or none)", default="none").strip()
        if not answer or answer.lower() == "none":
            click.echo("No changes made.")
            return
        chosen = {"all": True} if answer.lower() == "all" else {"apply": _numbers(answer)}
        _echo_applied(_enrich_core(**chosen, profile_dir=workspace.PROFILE_DIR))
    except (ValueError, FileNotFoundError, claude_cli.ClaudeError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
