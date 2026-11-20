"""Every model prompt lives in `.claude/agents/<name>.md` and `claude_cli.prompt` returns it byte for byte.

Recorded answers (cv reading, style structure, facts) are keyed by a hash of prompt plus input, so a prompt
moved into a file must be exactly the text the code sent before: pinned here by sha256."""

import hashlib
import re

import pytest

from door.commands import _common as common
from door.core import claude_cli, workspace

# name -> (model in the frontmatter, sha256 of the text sent)
PROMPTS = {
    "posting-reader": ("haiku", "cd4aa55578ca16f0e551b341a754ecf550fb53b6f1b6a3535e1307472279a65d"),
    "ask": ("haiku", "380bb96a9a677ee3e27b32ff7b1615324e5ccaaed57b3b0f3ba5f3e29cc87fb5"),
    "cv-drafter": ("sonnet", "ca694cc5fcdc69329c8ccdd44d707bc41c887d84c4b8b0ad73a09180766228d4"),
    "cv-enricher": ("sonnet", "5352b1ea450a1dda5c2e1afad47758cb928120413e96fd79299739ecccacd5b5"),
    "skill-gaps": ("sonnet", "05f47fcc2d6605a23f4b1cb120805901bc001ece629c7b9b7b7eea9750587529"),
    "keywords": ("haiku", "6b9c81f3e5d8791f6750aca0c4207840daba6280df0b3d0d1a0519e2395f3513"),
    "skill-grouper": ("haiku", "f3492df541d158d0b13e3071464e7879bcdbabb30aca2a536bd304daa63d5e96"),
    "reviser": ("sonnet", "9a8da9bb9b5c78cf17197c78731e23d40f2395367388cf5bbd6eb6cfbb75406b"),
    "salary": ("haiku", "bcc343a5e311c3daa8dfefafc790c59764b51305d0670fd0fadaf40f15b6988e"),
    "story-from-text": ("sonnet", "396cb41ff0c03f36daacfbd7c251ab47afe86305a1e6699c52bef0222242ce57"),
    "story-from-cv": ("sonnet", "e3d7398892b12f04dd7d8cad7d4a380342c0591139fd480462022e7b8ca49e9b"),
    "titles": ("haiku", "9a43c42623988336bf2ff2157766650e4769632e65021f1b22156f6d22484299"),
    "cv-reader": ("haiku", "47d0089f6137d469597472e2c392160874f13df59f576976f44bdbb9ec879ea7"),
    "careers-finder": ("haiku", "db7ae8bb770a26bd7b7e7e0721f7d5e8bae23dac0a8a44cb44a2b7b64539da80"),
    "title-translator": ("haiku", "7366039f9e7e68574fc0b240b86d9c456983ac93d83c46e729c571e286a79d61"),
    "cv-structure": ("haiku", "365f6265bb3c328ffd0e53ae992d21e3ec7b12f850da029f185022e4cb64ad13"),
    "fact-checker": ("haiku", "b59c8019c78432960dc58b23ebf15a133cd9db6c301c2d7b6c861697ba570f76"),
}
_FIELDS = {"cv-drafter": {"webfetch_rules": common._WEBFETCH_RULES}, "cv-enricher": {"webfetch_rules": common._WEBFETCH_RULES}}


@pytest.mark.parametrize("name", PROMPTS)
def test_the_prompt_is_the_text_the_code_sent_before(name):
    text = claude_cli.prompt(name, **_FIELDS.get(name, {}))
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == PROMPTS[name][1]


@pytest.mark.parametrize("name", PROMPTS)
def test_the_model_is_the_files(name):
    assert claude_cli.model_of(name) == PROMPTS[name][0]


def test_a_field_is_filled_where_the_file_names_it_and_other_braces_stay():
    text = (workspace.REPO_ROOT / ".claude" / "agents" / "skill-grouper.md").read_text(encoding="utf-8")
    assert "{variant, canonical, skill}" in claude_cli.prompt("skill-grouper")
    assert "{webfetch_rules}" in (workspace.REPO_ROOT / ".claude" / "agents" / "cv-drafter.md").read_text(encoding="utf-8")
    assert "{webfetch_rules}" not in claude_cli.prompt("cv-drafter", webfetch_rules="X")
    assert text.startswith("---\nname: skill-grouper\n")


def test_every_prompt_file_says_it_is_not_for_direct_use_and_names_its_module():
    for name in PROMPTS:
        text = (workspace.REPO_ROOT / ".claude" / "agents" / f"{name}.md").read_text(encoding="utf-8")
        description = re.search(r"^description: (.*)$", text, re.M).group(1)
        assert description.startswith("Not for direct use"), name
        assert "`door." in description, name

