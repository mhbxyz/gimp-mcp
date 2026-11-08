"""The installation documentation is short, complete and consistent with `gimp-mcp setup` (#44)."""

from __future__ import annotations

import json
import re

import pytest

from gimp_mcp.setup import ClaudeCode, ClaudeDesktop, Cursor, VSCode, server_entry
from tests.docs.doctest_blocks import ROOT, blocks, commands

UVX_SERVER = ["uvx", "gimp-mcp", "serve"]
CLIENT_PAGES = ["claude-code", "claude-desktop", "vscode-cursor", "generic"]


def test_readme_starts_with_a_quickstart_of_at_most_three_commands():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    quickstart = next(b for b in blocks("doctest") if b.name == "quickstart")
    assert quickstart.page.name == "README.md"
    assert 1 <= len(commands(quickstart)) <= 3
    first_section = readme.split("\n## ", 2)[1]
    assert first_section.lower().startswith("quickstart")


def test_one_page_per_main_client_with_the_same_steps():
    for name in CLIENT_PAGES:
        page = ROOT / "docs" / "clients" / f"{name}.md"
        text = page.read_text(encoding="utf-8")
        for heading in ("## Install", "## Configure", "## First prompt", "## Check"):
            assert heading in text, (name, heading)
        assert "Flatpak" in text, name  # both GIMP packagings are covered
        assert "troubleshooting.md" in text, name


@pytest.mark.linux_paths  # the docs show the Linux locations
def test_client_snippets_are_what_setup_writes():
    env: dict[str, str] = {"HOME": "/home/u"}
    expected = {
        "claude-desktop": {"mcpServers": {"gimp": server_entry(UVX_SERVER, env)}},
        "cursor": {"mcpServers": {"gimp": server_entry(UVX_SERVER, env)}},
        "vscode": VSCode("vscode", "VS Code", env, UVX_SERVER).payload(),
    }
    seen = set()
    for block in blocks("snippet"):
        if block.name == "claude-code":
            command = " ".join(ClaudeCode("claude-code", "Claude Code", env, UVX_SERVER).add_command())
            assert block.body.strip() == command
        else:
            assert json.loads(block.body) == expected[block.name], block.name
        seen.add(block.name)
    assert seen == {"claude-code", "claude-desktop", "cursor", "vscode"}
    # the documented files are the ones setup edits
    assert (
        str(ClaudeDesktop("claude-desktop", "", env, UVX_SERVER).path())
        == "/home/u/.config/Claude/claude_desktop_config.json"
    )
    assert str(Cursor("cursor", "", env, UVX_SERVER).path()) == "/home/u/.cursor/mcp.json"


def test_install_reference_covers_upgrade_uninstall_and_troubleshooting():
    install = (ROOT / "docs" / "install.md").read_text(encoding="utf-8")
    for heading in ("## Upgrade", "## Uninstall", "## Troubleshooting"):
        assert heading in install
    assert "gimp-mcp doctor" in install and "troubleshooting.md" in install


def test_documented_links_point_to_existing_files():
    for page in [ROOT / "README.md", *(ROOT / "docs").rglob("*.md")]:
        for target in re.findall(r"\]\((?!https?://|#|mailto:)([^)#]+)", page.read_text(encoding="utf-8")):
            assert (page.parent / target).exists(), f"{page.relative_to(ROOT)} -> {target}"
        for target in re.findall(
            r"\]\(https://github\.com/mhbxyz/gimp-mcp/blob/main/([^)#]+)", page.read_text(encoding="utf-8")
        ):
            assert (ROOT / target).exists(), f"{page.relative_to(ROOT)} -> {target}"
