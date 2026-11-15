"""The test world's stand-in claude answers `skill_gaps` the way the real one does (#33): in an envelope."""

import json
import re
import subprocess
import sys

from door.commands import gaps
from door.core import claude_cli, usage
from paths import REPO_ROOT

CLAUDE = REPO_ROOT / "app" / "test" / "world" / "claude.py"
REPORT = "## Plan\n\n### 1. Bayesian models (Priority: High)\n- r\n\n### 2. Grid basics\n- r\n\n## Skipped gaps\n- x\n"


def test_the_gaps_answer_is_an_envelope_the_ask_reader_and_the_plan_counter_accept(tmp_path):
    (tmp_path / "world.json").write_text(json.dumps({"answers": {"gaps": REPORT}}))
    argv = [sys.executable, str(CLAUDE), str(tmp_path), "-p", "--model", "haiku", "--system-prompt", gaps._RULES,
            *claude_cli.STREAM_ARGS, "--tools", "", "--no-session-persistence"]
    out = subprocess.run(argv, input="the CV and the targets", capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    text = claude_cli.envelope_result(out.stdout)
    assert isinstance(text, str) and text.strip() == REPORT.strip()
    assert len(gaps._PLAN_ITEM_RE.findall(text)) == 2


def test_every_answer_carries_a_cost_the_usage_log_weighs(tmp_path):
    """#67: each answer is priced (`total_cost_usd`), so `status_summary`'s `cost` reads in the world."""
    (tmp_path / "world.json").write_text(json.dumps({"answers": {"gaps": REPORT}}))
    argv = [sys.executable, str(CLAUDE), str(tmp_path), "-p", "--model", "haiku", "--system-prompt", gaps._RULES,
            *claude_cli.STREAM_ARGS, "--tools", "", "--no-session-persistence"]
    out = subprocess.run(argv, input="the CV and the targets", capture_output=True, text=True)
    envelope, _ = claude_cli.read_stream(out.stdout)
    assert usage.weight(envelope) > 0
