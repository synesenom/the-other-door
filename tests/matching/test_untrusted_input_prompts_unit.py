"""Every prompt that carries a job ad says the ad is untrusted data (#368)."""

import pytest

from door.core import claude_cli
from door.matching import scorer
from paths import REPO_ROOT


@pytest.mark.parametrize("agent", ["matcher", "tailor", "reviewer"])
def test_agent_prompts_call_the_ad_untrusted(agent):
    text = (claude_cli.PROMPTS_DIR / f"{agent}.md").read_text(encoding="utf-8").lower()
    assert "untrusted" in text


def test_revise_prompt_calls_the_ad_untrusted():
    assert "untrusted" in claude_cli.prompt("reviser").lower()


def test_scorer_system_prompt_calls_the_ad_untrusted():
    prompt = scorer.build_system_prompt({}, "cv", "## Scoring rubric (0-1)\nx\n")
    assert "untrusted" in prompt.lower()


def test_preferences_text_sits_in_the_profile_block_not_the_posting_message():
    prompt = scorer.build_system_prompt({"preferences": "avoid banking"}, "cv", "## Scoring rubric (0-1)\nx\n")
    assert prompt.index("## Candidate profile") < prompt.index("- preferences: avoid banking") < prompt.index("## Candidate CV")
