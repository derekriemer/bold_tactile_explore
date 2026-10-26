import asyncio
import json
import zipfile
from pathlib import Path

import pytest

from tactile_terrain.devkit.notes import write_dev_note
from tactile_terrain.devkit.plugin import PLUGIN_NAME, build_dev_plugin

ROOT = Path(__file__).parent.parent


def test_dev_note_is_saved_as_markdown_under_the_models_folder(tmp_path):
    message = write_dev_note(tmp_path, "Slope text is unclear!", "I guessed the units.")
    [saved] = (tmp_path / "dev-notes").glob("*.md")
    assert saved.name.endswith("slope-text-is-unclear.md") and str(saved) in message
    assert saved.read_text(encoding="utf-8") == "# Slope text is unclear!\n\nI guessed the units.\n"


def test_dev_note_needs_title_and_body(tmp_path):
    with pytest.raises(ValueError, match="title and a body"):
        write_dev_note(tmp_path, " ", "x")


def test_dev_plugin_is_separate_from_the_published_one(tmp_path):
    archive = build_dev_plugin(ROOT, tmp_path)
    out = tmp_path / "dev-plugin"
    manifest = json.loads((out / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    server = manifest["mcpServers"]["tactile-terrain"]
    assert manifest["name"] == PLUGIN_NAME != "tactile-terrain"
    assert server["env"] == {"TACTILE_TERRAIN_DEV": "1"} and str(ROOT.resolve()) in server["args"]
    assert (out / "skills" / PLUGIN_NAME / "SKILL.md").exists()
    assert (out / "skills" / "tactile-terrain" / "SKILL.md").exists()
    with zipfile.ZipFile(archive) as zf:
        assert ".claude-plugin/plugin.json" in zf.namelist()
    published = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert "env" not in published["mcpServers"]["tactile-terrain"]


def test_dev_tool_exists_only_when_registered():
    from tactile_terrain import server

    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert "write_dev_note" not in names or server.os.environ.get("TACTILE_TERRAIN_DEV")
    server.register_dev_tools()
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert "write_dev_note" in names


def test_dev_plugin_folder_is_git_ignored():
    assert "dev-plugin/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
