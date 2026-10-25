# Packaging and distribution plan

Goal: an average user, often a blind person on a screen reader, gets a working tool by installing as few things as possible, with each install step accessible. A friend who only prints should not need Claude at all.

## What has to be on the machine

The Python dependencies (rasterio with bundled GDAL, shapely, pyproj, trimesh, manifold3d, pydantic, HyRiver) all ship prebuilt wheels for Windows, macOS and Linux. No compiler, no separate GDAL install. So the real requirements are:

| Need | Why | How the user gets it |
|---|---|---|
| A Claude client | Runs the skill and calls the tools | Claude desktop app or Claude Code; any MCP client works without the skill |
| `uv` | Installs Python itself and the locked dependencies; runs the server | One command (PowerShell or shell) from astral.sh; screen-reader friendly. Not needed for the `.mcpb` route, where the Claude app manages it |
| Network on first use | Elevation and map downloads | Already confirmed for this machine |
| Disk | Dependency cache ~300–500 MB, ~10–80 MB per model | Default models folder `~/TactileModels` (easy to find, not hidden) |

Not needed: Git, a system Python, a slicer (optional, enables real print time and filament).

## Distribution channels, in the order to build them

### 1. PyPI package, run with `uvx` (the foundation)

Publish `tactile-terrain` to PyPI. Then every other channel is a thin pointer to a pinned version:

```bash
uvx tactile-terrain@0.1.0 mcp
```

- One package, three entry points under one CLI: `tactile-terrain mcp` (stdio server), `tactile-terrain build <spec.json>`, `tactile-terrain doctor`.
- The plugin's `.mcp.json` changes from `uv run --directory ${CLAUDE_PLUGIN_ROOT}` (development) to `uvx tactile-terrain@<version> mcp` (release), so installing the plugin no longer needs the repo on disk.
- Released from GitHub Actions on a tag, using PyPI trusted publishing (no token stored).

### 2. Claude plugin through a GitHub marketplace

Once the repo is public, users add it by name and install it; the plugin is just the manifest, `.mcp.json` (pointing at `uvx`) and the skill. This is the Claude Code and Cowork route, and the only one that ships the skill.

### 3. Claude Desktop extension (`.mcpb`) for one-file install

An MCP Bundle is a single file the user opens to install into the Claude desktop app, with a settings form for options such as the models folder. The newer `uv` server type lets the Claude app manage Python and the dependencies from `pyproject.toml`, so the bundle stays small and cross-platform, and the user doesn't install `uv` themselves.

- To verify at build time: that the user's Claude app version supports the `uv` server type, and that its install and settings screens work with NVDA. If the settings form isn't accessible, defaults must be good enough to skip it.
- A desktop extension doesn't carry the skill. The server's own MCP `instructions` field should therefore hold a short version of the workflow (resolve → confirm → create → describe → check), so any client gets the essentials.

### 4. Not planned: a frozen standalone executable

PyInstaller with GDAL would be a 200–300 MB per-platform binary that antivirus software often flags, and it would have to be rebuilt for every OS. Revisit only if the `.mcpb` `uv` route doesn't work out.

## Built into the tool to make installs work

- **`doctor` (CLI command and MCP tool)**: a text report of Python and package versions, config file location, models folder (and whether it's writable), whether each data service is reachable, slicer found or not, and the active tactile profile. This is the first thing to run when something is wrong, and it's what a user reads back to whoever is helping them.
- **First-run setup**: if no config exists, write one with defaults and say where it is, in text. Printer settings stay "unknown" until set, and tools that depend on them say so instead of assuming.
- **Fast start**: heavy imports happen inside tools, not at server start, so the first launch doesn't hit the client's start-up timeout while dependencies load.
- **Version pinning**: the plugin and `.mcpb` pin an exact package version, so an update never changes a model build without the user choosing it. `spec.json` records the tool version that built it.

## The "friend who prints" path

They need files, not the tool:

- `create_model` writes a `print-pack/` folder per model: the STL, `ATTRIBUTION.txt`, and `PRINT-NOTES.txt` (footprint, height, base, recommended layer height, no supports needed, which side faces up, and the filament estimate below). Zip it and send it.
- If they want to rebuild or tweak it themselves, `uvx tactile-terrain build spec.json` reproduces the STL from the spec, with no Claude needed.

## Filament estimates (for reimbursing your friend)

The spec says not to guess print time without a slicer, but filament has a solid upper bound: the mesh volume is exact. `check_print` reports:

- mesh volume in cm³
- grams of PLA if printed 100% solid (volume × 1.24 g/cm³), stated as an upper bound
- a typical range at 15–20% infill, clearly labelled as an estimate, plus a note that the slicer gives the real number

Rough numbers for the planned prints, from their dimensions (to be replaced by real ones once built):

| Print | Approx. size | Rough PLA at ~15% infill |
|---|---|---|
| Sampler plate | 150 × 120 × ~5 mm | 40–60 g |
| Winter Park cirque crop | 50 × 50 × ~20 mm | 15–30 g |
| Winter Park flat | 128 × 189 × ~5 mm | 60–90 g |
| Winter Park terrain | 128 × 189 × up to 24 mm | 110–170 g |
| **Total** | | **roughly 250–350 g**, about a third of a 1 kg spool |

At typical PLA prices that's on the order of US$5–10 of filament. Print time (likely the bigger ask of a friend) needs their slicer: the terrain model is probably most of a day.

Later option to cut filament: a hollow base with internal ribs for terrain models, as a printer-config setting. It isn't needed for Winter Park.

## When this happens

- Phase 1: first-run config (M1), lazy imports (M7), `doctor`, `print-pack/` with print notes and the filament numbers in `check_print` (M8).
- Phase 1, M10: plugin running from the checkout (`uv run --directory`).
- After Winter Park validates (**M12, release 0.1.0**): PyPI publishing, the plugin switched to `uvx`, the GitHub marketplace, and a `.mcpb` build in CI with an accessibility check of its install flow.
