"""Proposing job-board search terms (`search_keywords`) and the title terms that make a job relevant
(`topic_terms`) from the role targets.

"Expand my search keywords" in a conversation (the `keywords` tool) and
`init`'s keywords step in a shell are the same one `claude -p` call: the rules below are the one place the
term-proposal rules live (`/onboard`'s keywords step calls the tool too).
"""

from pathlib import Path

from door import i18n
from door.commands import profile as profile_cmd
from door.core import claude_cli, profile_loader, utils, workspace

_STALE = ".search_terms_stale"


def stale(profile_dir: Path) -> bool:
    """Whether a saving proposal started and did not finish: the search terms do not follow the role targets."""
    return (profile_dir / _STALE).exists()



_SCHEMA = {
    "type": "object",
    "properties": {
        "keywords": {"type": "array", "items": {"type": "string"}},
        "topic_terms": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["keywords", "topic_terms"],
}


def _clean(terms) -> list[str]:
    """Trimmed, non-empty, unique (case-insensitively, first spelling wins), in order."""
    seen = set()
    cleaned = []
    for term in terms:
        text = " ".join(str(term).split())
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        cleaned.append(text)
    return cleaned


def _keywords_core(
    role_targets: list[str] | None = None,
    *,
    languages: list[str] | None = None,
    save: bool = False,
    model: str | None = None,
    profile_dir: Path | None = None,
    timeout_s: float = 120,
) -> dict:
    """Propose `search_keywords` from `role_targets` (default: the profile's) in English and
    each of the job-ad `languages` (default: the profile's), and the `topic_terms` that make a job
    title relevant, with one `claude -p` call; with `save`, write both to profile/config.json.

    Returns:
        ``{"role_targets", "keywords", "topic_terms", "saved"}`` plus ``"config_path"`` when saved.

    Raises:
        ConfigError: an invalid profile/config.json (onboarding proposes before there is one).
        ValueError: no role targets to work from.
        claude_cli.ClaudeError: the `claude -p` call failed or answered
            something else.
    """
    if profile_dir is None:
        profile_dir = workspace.PROFILE_DIR
    config = profile_loader.load_config_or_defaults(profile_dir)
    targets = _clean(role_targets if role_targets is not None else config.get("role_targets") or [])
    if not targets:
        raise ValueError("no role targets to propose keywords from: pass some, or set role_targets in profile/config.json")

    packs = i18n.languages()
    wanted = languages if languages is not None else config.get("languages") or []
    codes = [c for c in (i18n.language_code(v) for v in wanted) if c]
    ad_languages = [packs[c].name for c in dict.fromkeys(["en", *codes]) if c in packs]
    if save:
        utils.write_atomic(profile_dir / _STALE, "")
    answer = claude_cli.ask(
        "keywords", "Role targets: " + "; ".join(targets) + "\nAd languages: " + ", ".join(ad_languages),
        model=model, feature="keywords", schema=_SCHEMA, timeout_s=timeout_s,
        profile_dir=profile_dir,
    )
    if not isinstance(answer.get("keywords"), list):
        raise claude_cli.ClaudeError("claude's answer has no `keywords` list")
    keywords = _clean(answer["keywords"])
    if not keywords:
        raise claude_cli.ClaudeError("claude proposed no keywords")

    topic = answer.get("topic_terms")
    topic_terms = _clean(topic) if isinstance(topic, list) else []

    result = {"role_targets": targets, "keywords": keywords, "topic_terms": topic_terms, "saved": False}
    if save:
        fields = {"search_keywords": keywords, **({"topic_terms": topic_terms} if topic_terms else {})}
        written = profile_cmd._init_core(fields, profile_dir=profile_dir, example_dir=workspace.PROFILE_EXAMPLE_DIR)
        (profile_dir / _STALE).unlink(missing_ok=True)
        result["saved"] = True
        result["config_path"] = written["config_path"]
    return result
