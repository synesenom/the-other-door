"""Every model prompt lives in `.claude/agents/<name>.md` and `claude_cli.prompt` returns it byte for byte.

Recorded answers (cv reading, style structure, facts) are keyed by a hash of prompt plus input, so a prompt
moved into a file must be exactly the text the code sent before: pinned here by sha256."""

import hashlib
import re

import pytest

from door.commands import _common as common
from door.core import claude_cli, workspace
from door.matching import scorer
from paths import REPO_ROOT

# `reviser` is the one deliberate text change: the rules moved from the user message into the system prompt.
# name -> (model in the frontmatter, sha256 of the text sent)
PROMPTS = {
    "posting-reader": ("haiku", "cd4aa55578ca16f0e551b341a754ecf550fb53b6f1b6a3535e1307472279a65d"),
    "ask": ("haiku", "380bb96a9a677ee3e27b32ff7b1615324e5ccaaed57b3b0f3ba5f3e29cc87fb5"),
    "cv-drafter": ("sonnet", "ca694cc5fcdc69329c8ccdd44d707bc41c887d84c4b8b0ad73a09180766228d4"),
    "cv-enricher": ("sonnet", "5352b1ea450a1dda5c2e1afad47758cb928120413e96fd79299739ecccacd5b5"),
    "skill-gaps": ("sonnet", "1f46f1a229ba3db39ca73c2b2cdc990945ff177d7b5dcc65b56a5b45ab470036"),
    "keywords": ("haiku", "6b9c81f3e5d8791f6750aca0c4207840daba6280df0b3d0d1a0519e2395f3513"),
    "skill-grouper": ("haiku", "f3492df541d158d0b13e3071464e7879bcdbabb30aca2a536bd304daa63d5e96"),
    "reviser": ("sonnet", "62b1db5e4bb3ea4481c4f957f7c7caf947d3ca36cfcfedf28a87a3d51c200564"),
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



def test_the_scorer_system_prompt_is_the_text_the_code_assembled_before():
    """The rubric, phrases, profile and CV go into scorer.md's fields in one pass, so a `{cv}` in a preference stays text."""
    config = {"role_targets": ["Data Analyst", "BI Developer"], "location": "Copenhagen", "remote": "hybrid",
              "languages": ["en", "da"], "min_score": 0.6, "exclude": {"companies": ["Acme"], "keywords": ["intern"]},
              "needs_work_permit": True, "preferences": "small teams {cv} and {profile}"}
    text = scorer.build_system_prompt(config, "# Jane Doe\n\n## Skills\n\nPython, {rubric} SQL\n\n", scorer.load_rubric_md())
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == "7f9750439830700b46fd79b192c380601e51146d500822b468a44321193aaa11"


def test_the_matcher_file_tells_its_model_and_has_no_tools():
    assert claude_cli.model_of("matcher") == "haiku" and claude_cli.tools_of("matcher") == ()
    assert scorer.DEFAULT_MODEL == claude_cli.model_of("scorer")


def test_the_reviser_rules_are_the_system_prompt_and_the_user_message_has_only_the_job():
    """The one deliberate text change of the move: `revise`'s rules left its user message for the system prompt."""
    rules = claude_cli.prompt("reviser")
    assert "Rules:" in rules and "kind-summary" in rules and "untrusted" in rules


def test_the_bundle_copies_the_agent_files_the_code_names_and_no_more():
    src = "\n".join(p.read_text(encoding="utf-8") for p in (REPO_ROOT / "src" / "door").rglob("*.py"))
    named = {p.stem for p in (REPO_ROOT / ".claude" / "agents").glob("*.md")
             if re.search(rf'agents/{p.stem}\.md|"{p.stem}(\.md)?"', src)}
    for script in ("bundle-python.sh", "bundle-python.ps1"):
        text = (REPO_ROOT / "app" / "scripts" / script).read_text(encoding="utf-8")
        listed = set(re.search(r"^(?:AGENTS=\(|\$Agents = )(.*?)\)?$", text, re.M).group(1).replace(",", " ").replace("'", "").split())
        assert listed == named, f"{script}: {sorted(listed ^ named)}"
