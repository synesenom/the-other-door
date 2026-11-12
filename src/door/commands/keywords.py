"""Proposing job-board search terms (`search_keywords`) and the title terms that make a job relevant
(`topic_terms`) from the role targets.

"Expand my search keywords" in a conversation (the `keywords` tool) and
`init`'s keywords step in a shell are the same one `claude -p` call: the rules below are the one place the
term-proposal rules live (`/onboard`'s keywords step calls the tool too).
"""

from pathlib import Path

from door import i18n
from door.commands import _common as common
from door.commands import profile as profile_cmd
from door.core import claude_cli, workspace

_DEFAULT_MODEL = "haiku"

_RULES = (
    "You propose search terms for job boards. The user gives you the job titles they are "
    "looking for (their role targets). Propose 8-15 short, job-board-friendly search terms: "
    "each target verbatim, its noun form (\"accountant\" -> \"accounting\"), common "
    "abbreviations (\"human resources\" -> \"HR\"), seniority variants (senior, lead, head of, "
    "manager) and close synonyms boards use. The user also names the languages of the "
    "job ads they read: give the terms in each ad language, as that language's job boards write "
    "them (\"nurse\" and Danish \"sygeplejerske\"), 8-15 per language; with English only, "
    "English terms only. No duplicates, no punctuation, "
    "lower case except abbreviations. "
    "Also give topic_terms, 15-30 per language: the words whose presence in a job title makes the job "
    "relevant to this person. Mostly single words: the field's own word even when it is short or broad "
    "(\"finance\", \"care\", \"data\"), its common abbreviations (\"HR\", \"ML\", \"BI\"), its subjects "
    "and tools, and the neighbouring fields this person would also take a job in (for an accountant: "
    "accounting, finance, audit, tax, payroll, controlling, bookkeeping; for a nurse: nurse, nursing, "
    "care, ward, clinical, patient). Never a bare role noun or seniority word that any field uses "
    "(analyst, engineer, manager, specialist, consultant, assistant, senior), and no word that mostly "
    "means something else alone: keep a field of several words together (\"machine learning\", "
    "\"data warehouse\", \"intensive care\"), never split. Give plain field words: the "
    "matcher itself finds a word of six letters or more inside a compound (Danish \"intensivsygeplejerske\" "
    "for \"sygeplejerske\") and in its plural, so no stems are needed; use \"x*\" (starts a word) or \"*x\" "
    "(ends one) only for a short stem or a word the plain form would miss. Keep an all-caps abbreviation that "
    "is also an ordinary word (\"MEAL\", a meal) in capitals, which the matcher reads case-sensitively, or pair it "
    "with its field words. For an academic field, the names of "
    "its institutes and departments in each ad language are topic terms too, since an academic title often "
    "names only the rank and the institute (\"Niels Bohr Institute\", \"Institut for Fysik og Astronomi\", "
    "\"DTU Physics\"); an institute or department is a valid topic term, a rank alone (professor, postdoc) is not. "
    "Answer with the JSON only."
)

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
    config = common._load_config_or_defaults(profile_dir)
    targets = _clean(role_targets if role_targets is not None else config.get("role_targets") or [])
    if not targets:
        raise ValueError("no role targets to propose keywords from: pass some, or set role_targets in profile/config.json")

    packs = i18n.languages()
    wanted = languages if languages is not None else config.get("languages") or []
    codes = [c for c in (i18n.language_code(v) for v in wanted) if c]
    ad_languages = [packs[c].name for c in dict.fromkeys(["en", *codes]) if c in packs]
    answer = claude_cli.ask(
        _RULES, "Role targets: " + "; ".join(targets) + "\nAd languages: " + ", ".join(ad_languages),
        model=model or _DEFAULT_MODEL, feature="keywords", schema=_SCHEMA, timeout_s=timeout_s,
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
        result["saved"] = True
        result["config_path"] = written["config_path"]
    return result
