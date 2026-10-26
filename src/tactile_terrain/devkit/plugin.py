"""Build the local development plugin: the real plugin plus alpha-test notes.

The output goes to a git-ignored folder, so it can't be pushed or published by accident. It runs
the server from this checkout, with TACTILE_TERRAIN_DEV set so the dev-only tools exist.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from tactile_terrain.devkit import DEV_ENV

PLUGIN_NAME = "tactile-terrain-dev"
OUT_FOLDER = "dev-plugin"

DEV_SKILL = """\
---
name: tactile-terrain-dev
description: Alpha-test notes for the tactile-terrain tools. Use alongside the tactile-terrain skill whenever you use those tools in this development build, so the developer learns where your workflow struggles.
---

# Alpha testing: tell the developer what is hard

This is an alpha development build. The person you are working with is the developer, and the
tools can be changed to suit you. When something about your workflow is awkward, record it with
`write_dev_note`. You do not need permission, and notes cost the user nothing to ignore.

Write a note when:

- you are unsure what a tool result means, or the text is confusing or ambiguous
- you needed several calls to learn something one call could have told you
- a result lacks a fact you needed, or buries it
- you had to guess, estimate or calculate something a tool could compute
- a name, unit or format was inconsistent between tools
- you wished a tool existed. Describe what it would take as input and return.

Each note says: what you were trying to do, what happened, what made it hard, and one concrete
change that would have helped. Keep it short and specific. One topic per note.

At the end of a working session, write one summary note with the three things that would most
improve your workflow. Mention in your reply that you wrote it, with its path.

Never put the user's personal or health information in a note.
"""


def build_dev_plugin(repo: Path, out_root: Path | None = None) -> Path:
    """Write dev-plugin/ and return the path of the zipped .plugin file."""
    repo = repo.resolve()
    out = (out_root or repo) / OUT_FOLDER
    if out.exists():
        shutil.rmtree(out)
    manifest = json.loads((repo / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    manifest["name"] = PLUGIN_NAME
    manifest["description"] = (
        "Development build of tactile-terrain with alpha-test notes. Not for publishing."
    )
    manifest["mcpServers"] = {
        "tactile-terrain": {
            "command": "uv",
            "args": ["run", "--directory", str(repo), "--frozen", "tactile-terrain", "mcp"],
            "env": {DEV_ENV: "1"},
        }
    }
    (out / ".claude-plugin").mkdir(parents=True)
    (out / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    market = {
        "name": "tactile-terrain-dev-local",
        "description": "Local development build. Not for publishing.",
        "owner": manifest.get("author", {"name": "developer"}),
        "plugins": [{"name": PLUGIN_NAME, "source": "./", "description": manifest["description"]}],
    }
    (out / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps(market, indent=2) + "\n", encoding="utf-8"
    )
    shutil.copytree(repo / "skills" / "tactile-terrain", out / "skills" / "tactile-terrain")
    dev_skill = out / "skills" / PLUGIN_NAME
    dev_skill.mkdir(parents=True)
    (dev_skill / "SKILL.md").write_text(DEV_SKILL, encoding="utf-8")
    archive = out / f"{PLUGIN_NAME}.plugin"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(out.rglob("*")):
            if path.is_file() and path != archive:
                zf.write(path, path.relative_to(out).as_posix())
    return archive
