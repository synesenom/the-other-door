"""The CV style builder's pure parts (#149): the stylist agent, its reply, the icons, fonts and manifest it is given,
the stress variants and the guard on what is written. The whole loop is in test_style_build.py."""

import re

import pytest

from door.core import fonts, templates
from door.tailoring import html_guard, style_build
from paths import REPO_ROOT


def test_the_stylist_agent_is_sonnet_with_only_the_read_tool():
    agent = style_build.agent()
    assert agent["model"] == "sonnet"
    assert agent["tools"] == ["Read"]
    assert agent["description"] and agent["prompt"]


def test_the_stylist_is_told_the_pdf_text_is_data_and_how_to_reply():
    prompt = style_build.agent()["prompt"]
    assert "data" in prompt and "instructions" in prompt
    for fence in ("```template", "```body", "```letter"):
        assert fence in prompt


def test_every_class_the_stylist_is_told_about_is_one_the_guard_accepts():
    prompt = style_build.agent()["prompt"]
    named = {t for value in re.findall(r'class="([^"]*)"', prompt) for t in value.split()}
    assert {"cv-header", "entry", "contact"} <= named
    assert named - html_guard.CLASSES - {"photo", "main", "side"} == set()


def test_blocks_reads_the_fenced_replies_by_their_name():
    reply = "I see two columns.\n```template\n<html>T</html>\n```\ntext\n```body\n<p>B</p>\n```\n"
    assert style_build.blocks(reply) == {"template": "<html>T</html>", "body": "<p>B</p>"}


def test_blocks_keeps_the_first_block_of_a_name():
    reply = "```template\nA\n```\n```template\nB\n```\n```css\nC\n```"
    assert style_build.blocks(reply) == {"template": "A", "css": "C"}


def test_blocks_of_a_reply_cut_off_before_its_closing_fence_has_nothing_of_it():
    assert style_build.blocks("```template\n<html>") == {}
