"""A model call that reads outside text (an ad, a page, a feed) has only the tools reviewed here (#561, #582, #584).

An agent's isolation must not depend on the model obeying its prompt: a call that sees an ad or a page gets no tool
that writes, fetches or reads beyond what it needs, and a call with the web never also sees the CV. A prompt gaining a
tool fails this test until the tool is added below with the reason it is safe.
"""

from door.core import claude_cli

REVIEWED = {
    "ask": ("mcp__door__status_summary", "mcp__door__list_matches", "mcp__door__show_profile",
            "mcp__door__query_jobs", "mcp__door__list_companies", "mcp__door__why_company"),  # read-only door tools
    "careers-finder": ("WebSearch",),  # an employer's name only, no CV
    "page-reader": ("mcp__pages__fetch_page",),  # only the pages the user gave, no CV (#561)
    "reviewer": ("Read",),  # the tailor's own folder
    "salary": ("WebSearch",),  # years and title only, no CV (#583)
    "tailor": ("Read", "Write", "Agent", "mcp__door__compile", "mcp__door__check_facts"),  # restricted to jobs/.tailor/<id>/ (#582)
}


def test_every_prompt_has_only_its_reviewed_tools():
    names = sorted(p.stem for p in claude_cli.PROMPTS_DIR.glob("*.md"))
    got = {n: claude_cli.tools_of(n) for n in names if claude_cli.tools_of(n)}
    assert got == REVIEWED, (
        "A prompt's tools changed. A call that reads an ad, a page or a feed must not get a tool that writes, fetches "
        "or reads more than it needs, and one with the web must not see the CV: split the call (as #561 did) or add "
        "the tool to REVIEWED with the reason it is safe.")


def test_the_tailors_real_grant_is_the_reviewed_one():
    from door.commands import prepare

    # `--allowedTools` is this list plus Read/Edit rules scoped to the job's folders (`_tailor_tools`)
    assert prepare._TAILOR_ALLOWED_TOOLS == ("Agent", "mcp__door__compile", "mcp__door__check_facts"), (
        "The tailor reads the ad: a tool added to its grant must be reviewed here, never a shell or the web.")


def test_the_scorer_and_the_title_translator_have_no_tools():
    from door.matching import language, scorer

    for argv in (scorer.build_claude_argv("s", "haiku", {}), language.build_argv("haiku")):
        assert argv[argv.index("--tools") + 1] == "", "The scorer and the title translator read ad text: no tools."


def test_no_call_overrides_its_prompts_tools():
    from paths import REPO_ROOT

    callers = [p.relative_to(REPO_ROOT).as_posix() for p in (REPO_ROOT / "src" / "door").rglob("*.py")
               if "allowed_tools=" in p.read_text(encoding="utf-8") and p.name != "claude_cli.py"]
    assert callers == [], (
        f"{callers} pass allowed_tools= to claude_cli.ask: give the prompt file its tools instead, so they are "
        "reviewed in REVIEWED above.")
