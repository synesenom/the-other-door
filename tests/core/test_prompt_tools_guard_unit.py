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
