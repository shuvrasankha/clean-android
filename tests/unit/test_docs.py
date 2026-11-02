"""Docs must not drift from the CLI: every `reboot <command>` they show must exist."""

import re
from pathlib import Path

import typer.main

from reboot import cli

ROOT = Path(__file__).resolve().parents[2]
DOCS = [ROOT / "PROMPT.md", ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
FORBIDDEN_IN_PROMPT = ("pm uninstall", "pm clear", "--yes", "-y ")


def test_documented_commands_exist():
    commands = set(typer.main.get_command(cli.app).commands)
    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        # Only code: inline `reboot x ...` or a line starting with `reboot x` in a code block.
        for name in re.findall(r"`reboot ([a-z]+)|^reboot ([a-z]+)", text, re.MULTILINE):
            name = name[0] or name[1]
            assert name in commands, (path, name)


def test_prompt_never_tells_assistant_to_auto_confirm():
    text = (ROOT / "PROMPT.md").read_text(encoding="utf-8")
    assert "Never run `reboot apply`" in text
    for bad in FORBIDDEN_IN_PROMPT[2:]:
        assert bad not in text


def test_relative_doc_links_resolve():
    for path in DOCS:
        for target in re.findall(r"\]\(([^)#:]+\.md)\)", path.read_text(encoding="utf-8")):
            assert (path.parent / target).exists(), (path, target)
