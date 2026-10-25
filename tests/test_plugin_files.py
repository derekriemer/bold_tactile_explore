import asyncio
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
# Backticked snake_case words in SKILL.md that are spec fields or options, not tools.
NOT_TOOLS = {"revert_to", "z_multiply", "crop_percent", "drop_feature"}


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def skill_text():
    return (ROOT / "skills" / "tactile-terrain" / "SKILL.md").read_text(encoding="utf-8")


def server_tools():
    from tactile_terrain.server import mcp

    return {tool.name for tool in asyncio.run(mcp.list_tools())}


def test_manifests_parse_and_agree():
    plugin = load(".claude-plugin/plugin.json")
    market = load(".claude-plugin/marketplace.json")
    mcp = load(".mcp.json")
    assert plugin["name"] == "tactile-terrain" and plugin["version"]
    assert [p["name"] for p in market["plugins"]] == [plugin["name"]]
    assert market["plugins"][0]["source"] == "./"
    assert "tactile-terrain" in mcp["mcpServers"]


def test_mcp_json_launches_the_real_command():
    server = load(".mcp.json")["mcpServers"]["tactile-terrain"]
    assert server["command"] == "uv" and server["args"][-2:] == ["tactile-terrain", "mcp"]
    assert "${CLAUDE_PLUGIN_ROOT}" in server["args"] and "--frozen" in server["args"]
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'tactile-terrain = "tactile_terrain.cli:main"' in pyproject


def test_skill_has_front_matter_and_matches_the_plugin_name():
    text = skill_text()
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "SKILL.md needs front matter"
    fields = dict(line.split(": ", 1) for line in match.group(1).splitlines())
    assert fields["name"] == load(".claude-plugin/plugin.json")["name"]
    assert len(fields["description"]) > 40


def test_every_tool_the_skill_names_exists():
    tools = server_tools()
    named = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", skill_text())) - NOT_TOOLS
    assert named, "the skill should name tools"
    assert named <= tools, f"skill names tools the server lacks: {sorted(named - tools)}"


def test_skill_never_mentions_images_as_output():
    text = skill_text().lower()
    assert "as you can see" in text  # only inside the instruction not to say it
    assert "never refer to images" in text
