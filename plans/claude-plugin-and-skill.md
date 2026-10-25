# Claude plugin and skill plan

One repository is both a standalone MCP server and a Claude plugin. The plugin is just three small files on top of the Python package; nothing in the server knows it's running as a plugin.

## Plugin layout (repo root is the plugin root)

```
.claude-plugin/
  plugin.json          # manifest
  marketplace.json     # one-plugin local marketplace, so it can be installed by path
.mcp.json              # how Claude launches the server
skills/
  tactile-terrain/
    SKILL.md           # the thin skill
    reference.md       # optional: rules of thumb and output format, loaded only when needed
```

### `.claude-plugin/plugin.json`

```json
{
  "name": "tactile-terrain",
  "version": "0.1.0",
  "description": "Turn elevation and map features into 3D-printable tactile terrain models, described fully in text.",
  "author": { "name": "Derek Riemer" },
  "license": "AGPL-3.0-or-later"
}
```

### `.mcp.json`

```json
{
  "mcpServers": {
    "tactile-terrain": {
      "command": "uv",
      "args": ["run", "--directory", "${CLAUDE_PLUGIN_ROOT}", "--frozen", "tactile-terrain-mcp"]
    }
  }
}
```

- `uv run --directory` uses the repo's own `uv.lock`, so the plugin gets exactly the tested dependency set.
- First launch has to build the environment (rasterio, HyRiver, trimesh: large). That can exceed the client's MCP start-up timeout. The README tells the user to run `uv sync` in the repo once before enabling the plugin; the server also starts fast by importing heavy libraries lazily inside tools, not at module import.
- The server must write nothing to stdout except protocol messages: logging goes to stderr, and any library that prints is wrapped.

### `.claude-plugin/marketplace.json`

```json
{
  "name": "tactile-terrain-local",
  "owner": { "name": "Derek Riemer" },
  "plugins": [
    { "name": "tactile-terrain", "source": "./", "description": "Tactile terrain models for 3D printing." }
  ]
}
```

Later, when the repo is public on GitHub, the same file lets anyone add it as a marketplace by repo name.

## The skill

Kept thin, per the spec: workflow and judgement, not facts that live in the server. Anything about which providers, styles, or analyzers exist comes from `list_capabilities`, so the skill doesn't go stale.

Draft `skills/tactile-terrain/SKILL.md`:

```markdown
---
name: tactile-terrain
description: Build, edit, describe and check 3D-printable tactile terrain models and tactile sampler plates with the tactile-terrain MCP tools. Use when the user wants a tactile or 3D-printed map, terrain model, relief model, or touch-readable map of a place, wants to change one (exaggeration, crop, features, line sizes), wants to know what a model contains, or wants to calibrate their tactile profile with a sampler.
---

# Tactile terrain

The user may be blind and using a screen reader. Everything you report must be complete as text.
Never refer to images, previews, colours or "as you can see". Use headings and short lines; put
units on every number; give positions as mm from the south-west corner, north is the far edge.

## Workflow for a new model

1. `list_capabilities` if you haven't this session, to learn the provider, style and preset names.
2. `resolve_area` with the place or bbox. Read back the area in km, elevation range, and the
   feature counts, including named streams and lifts, so the user can spot missing or wrong data.
3. Confirm the build parameters back to the user in ONE line (area, scale, exaggeration, base,
   mode, feature filters, tactile profile) and wait for a yes or changes.
4. `create_model`. Report the analysis it returns: warnings first, each with its proposed fix.
5. Always `describe_model` and give the user its full text, lightly organised. Don't summarise
   away line courses, crossings or cross-sections; they are the map.
6. `check_print` before calling the model done. Report the file paths.

## Editing

Use `update_model` with the smallest change. Say what changed in before → after form, then run
`describe_model` again if anything the user can feel changed, and `check_print`.
If `analyze_model` attaches a fix, offer it; apply it only when the user agrees.

## Defaults and rules of thumb

- Take printer, units and tactile profile from the user's config; don't invent sizes.
- Never put tactile sizes in your own words as fixed rules; they come from the user's profile.
- Vertical exaggeration: about 1–1.5× for mountains, about 3× for plains or gentle terrain. Let
  the relief analyzer's suggestion win if it disagrees.
- Creeks: filter by stream order and add named exceptions rather than lowering the cutoff.
- If the user hasn't printed a sampler yet, suggest `create_sampler` before a big print.

## Sampler

`create_sampler(profile)` then `describe_model` on it, and read out every row. Ask the user to
report results by row and sample number. In this version, turn their results into suggested
profile edits and show them; there is no automatic calibration yet.
```

What deliberately stays out of the skill: line widths, preset contents, data source details, any image-based check. All of that is either in the profile, in `list_capabilities`, or not allowed.

## Standalone (non-plugin) use

For any MCP client, documented in the README:

```bash
claude mcp add tactile-terrain -- uv run --directory C:/path/to/bold_tactile_explore tactile-terrain-mcp
```

Other clients get the equivalent `command`/`args` JSON. The skill is optional there.

## Installing and testing locally (Claude Code)

During development, load the plugin straight from the checkout without installing:

```bash
claude --plugin-dir C:/Users/driem/programmer_shit/python/bold_tactile_explore
```

To install it the way a user would:

```bash
claude plugin marketplace add C:/Users/driem/programmer_shit/python/bold_tactile_explore
```

```bash
claude plugin install tactile-terrain@tactile-terrain-local
```

Then in a session, `/mcp` should list `tactile-terrain` as connected, and the skill shows up in the skills list. (`/mcp` and `/plugin` are terminal commands; in the desktop app use an interactive `claude` terminal or the app's plugin UI.)

Exact CLI flags get rechecked against current Claude Code docs at M10, since plugin commands have changed between versions.

### Cowork

Cowork installs the same plugin format. Two things to verify at M10 rather than assume: whether Cowork runs plugin stdio MCP servers on the local machine (needed: the server writes STL files to `~/TactileModels` and needs network), and whether `uv` on PATH is visible to it. If Cowork can't run it, the plugin still works in Claude Code and the desktop Code tab, and the README says so.

## Winter Park test run through the plugin

The point of M10 and M11 is that the Winter Park build happens through the plugin + skill, so the test exercises the real user path.

1. `uv sync` in the repo; `uv run pytest` green.
2. Start Claude Code with `--plugin-dir` (or after installing). Confirm `/mcp` shows the server connected and `list_capabilities` returns text.
3. Prompt, as a user would say it:
   > Make me a tactile model of the Fraser valley from Fraser down to Berthoud Pass, including Winter Park and Mary Jane and the Second Creek cirques. Fraser River and the major creeks including Second Creek and Vasquez Creek, US-40, and all the lifts. About 1 mm per 100 m, 1.5 times vertical, 3 mm base.
4. Check the skill did, in order: `resolve_area` → one-line confirmation → (you say yes) → `create_model` → `describe_model` (full text) → `check_print`.
5. Prompt: "Now make a flat version of the same thing." Expect a new model `winter-park-flat`, same features, `mode: flat`.
6. Prompt: "Make a small crop around the Second Creek cirques, same scale." Expect `winter-park-cirques`.
7. Prompt an edit: "Double the vertical exaggeration." Expect `update_model`, before→after text, re-describe, check.
8. Prompt: "Undo that." Expect restore from the backed-up spec version.
9. Confirm on disk: `~/TactileModels/winter-park/` has `spec.json`, `spec.1.json`, `winter-park.stl`, `ATTRIBUTION.txt`, `cache/`.
10. Second session, same prompt as step 7 on an existing model: rebuild should be fast and work offline (cache).

Record anything the skill did wrong (skipped confirmation, summarised describe text, mentioned an image) as a skill fix; anything the tools did wrong as a server bug.

### Skill evals (later, cheap to add)

Once the steps above pass by hand, capture steps 3–8 as a small eval set so skill wording changes can be checked for regressions (the order of tool calls, the one-line confirmation, no image references).
