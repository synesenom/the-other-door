"""Every prompt that carries a job ad says the ad is untrusted data (#368)."""

import pytest

from door.commands import revise as revise_cmd
from door.matching import scorer
from paths import REPO_ROOT


@pytest.mark.parametrize("agent", ["matcher", "tailor", "reviewer"])
def test_agent_prompts_call_the_ad_untrusted(agent):
    text = (REPO_ROOT / ".claude" / "agents" / f"{agent}.md").read_text(encoding="utf-8").lower()
    assert "untrusted" in text


def test_revise_prompt_calls_the_ad_untrusted():
    assert "untrusted" in revise_cmd._REVISE_PROMPT.lower()


def test_scorer_system_prompt_calls_the_ad_untrusted():
    prompt = scorer.build_system_prompt({}, "cv", "## Scoring rubric (0-1)\nx\n")
    assert "untrusted" in prompt.lower()
