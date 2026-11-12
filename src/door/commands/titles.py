"""`cv titles`: suggest job titles from the CV and the career progression.

One `claude -p` call. Onboarding (`init`, `/onboard`, the app's wizard) pre-selects the recommended ones as
`role_targets` and proposes the search terms from them; "what titles should I look for?" in a conversation is
the same call (the `suggest_titles` tool). A failed call never stops a flow: it is a `warning`, and the flow
asks in free text.
"""

from pathlib import Path

import click

from door import i18n
from door.commands import _common as common
from door.commands import cv as cv_cmd
from door.core import claude_cli, workspace

_DEFAULT_MODEL = "haiku"
_MAX_TITLES = 10
# Pre-selected when the model marks none, so the review never opens with nothing ticked.
_FALLBACK_RECOMMENDED = 3
_OWN_REASON = "You named this title"

_RULES = (
    "You suggest the job titles a job seeker should search for, from their CV. Read the latest title and the "
    "progression across roles: Analyst, then Senior Analyst, then Team Lead suggests \"Lead\", \"Head of\" and "
    "\"Manager\" titles, not only the current one. Add titles next to their own field that fit their skills and "
    "tools (Python, dbt and Airflow suggest Analytics Engineer). Match the seniority to their years and scope: "
    "no junior title for a senior person, no jump far above what they have done. Use the titles job boards "
    "use. The user names the languages of the job ads they read: where a field's ads use another title in one "
    "of those languages, suggest it in that language too; with English only, English titles only. Keep any "
    "title the user names, and when they say what they are looking for, include titles for it and mark them "
    "recommended. Suggest 6-10 titles. Each has `title`, `reason` (a few words the CV backs, like \"your last "
    "two roles led a team of 5\", never invented) and `recommended` (true for the 2-4 that fit best). Answer "
    "with the JSON only."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "titles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "reason": {"type": "string"}, "recommended": {"type": "boolean"}},
                "required": ["title", "reason", "recommended"],
            },
        },
    },
    "required": ["titles"],
}


def _clean(raw, own: list[str]) -> list[dict]:
    """The user's own titles first (always recommended, the model's reason when it gave one), then the model's:
    trimmed, unique case-insensitively, at most `_MAX_TITLES` unless the user's own alone are more."""
    answered: dict[str, dict] = {}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        title = " ".join(str(item.get("title") or "").split())
        if title and title.lower() not in answered:
            answered[title.lower()] = {
                "title": title, "reason": " ".join(str(item.get("reason") or "").split()), "recommended": bool(item.get("recommended")),
            }
    titles, seen = [], set()
    for name in (" ".join(str(n).split()) for n in own):
        if name and name.lower() not in seen:
            seen.add(name.lower())
            titles.append({"title": name, "reason": (answered.get(name.lower()) or {}).get("reason") or _OWN_REASON, "recommended": True})
    for key, item in answered.items():
        if key not in seen and len(titles) < _MAX_TITLES:
            titles.append(item)
    if titles and not any(t["recommended"] for t in titles):
        for item in titles[:_FALLBACK_RECOMMENDED]:
            item["recommended"] = True
    return titles


def _titles_core(
    titles: list[str] | None = None,
    *,
    hint: str | None = None,
    languages: list[str] | None = None,
    model: str | None = None,
    profile_dir: Path | None = None,
    timeout_s: float = 120,
) -> dict:
    """Suggest job titles from the CV (`profile/cv.draft.md` while onboarding, else `profile/cv.md`), in each of
    the job-ad `languages` (default: the profile's), with one `claude -p` call. Works before the profile exists.

    Returns:
        ``{"titles": [{"title", "reason", "recommended"}]}``, plus ``"warning"`` when the model could not be
        asked or answered nothing (then only `titles` given here are listed).

    Raises:
        ConfigError: an invalid profile/config.json.
    """
    if profile_dir is None:
        profile_dir = workspace.PROFILE_DIR
    own = list(titles or [])
    config = common._load_config_or_defaults(profile_dir)
    cv_text = cv_cmd._onboarding_cv_text(profile_dir, config)
    if not cv_text:
        return {"titles": _clean([], own), "warning": "no CV of yours to suggest titles from yet"}
    packs = i18n.languages()
    wanted = languages if languages is not None else config.get("languages") or []
    codes = [c for c in (i18n.language_code(v) for v in wanted) if c]
    prompt = (
        f"CV:\n<<<\n{cv_text}\n>>>\n\n"
        "Ad languages: " + ", ".join(packs[c].name for c in dict.fromkeys(["en", *codes]) if c in packs) + "\n"
        + ("Titles they named: " + "; ".join(own) + "\n" if own else "")
        + (f"What they are looking for: {hint}\n" if hint else "")
    )
    try:
        answer = claude_cli.ask(
            _RULES, prompt, model=model or _DEFAULT_MODEL, feature="suggest_titles", schema=_SCHEMA, timeout_s=timeout_s,
            profile_dir=profile_dir,
        )
    except claude_cli.ClaudeError as exc:
        return {"titles": _clean([], own), "warning": str(exc)}
    cleaned = _clean(answer.get("titles"), own)
    return {"titles": cleaned} if cleaned else {"titles": [], "warning": "claude suggested no titles"}


@click.command("titles")
@click.argument("titles", nargs=-1)
@click.option("--hint", default=None, help='What you are looking for, in your own words ("something with people").')
@click.option("--languages", default=None, help="The job-ad languages, comma-separated (default: the profile's).")
@click.option("--model", default=None, help=f"Claude model to ask (default: {_DEFAULT_MODEL}).")
def titles_command(titles: tuple[str, ...], hint: str | None, languages: str | None, model: str | None):
    """Suggest job titles from your CV and career progression, each with a reason."""
    wanted = [part.strip() for part in languages.split(",") if part.strip()] if languages else None
    result = _titles_core(list(titles), hint=hint, languages=wanted, model=model, profile_dir=workspace.PROFILE_DIR)
    for item in result["titles"]:
        click.echo(f"{'*' if item['recommended'] else ' '} {item['title']}: {item['reason']}")
    if result.get("warning"):
        click.echo(f"Warning: {result['warning']}", err=True)
