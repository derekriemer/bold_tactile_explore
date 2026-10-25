# tactile-terrain

Tactile terrain printing: an MCP server and Claude plugin that turn map areas into 3D-printable models for touch.

Status: Phase 1 under construction. Licensed AGPL-3.0-or-later.

Everything the tool reports is plain text, so it works with a screen reader.

Design documents:

- [Design spec](docs/design-spec.md): what the tool does and why; the source of truth when the code and a plan disagree.
- [Design invariants](docs/design-invariants.md): the rules the tool must keep.
- [Plans](plans/README.md): the build plans and milestones.

## What it does

- `resolve_area`: describe an area before building (size, elevation range, named streams, roads, lifts and peaks).
- `create_model` and `update_model`: build a model from US elevation and map data, then change it. Every edit keeps the previous version, so it can be undone.
- `describe_model`: read the whole model out as text: high points, the course of every line, crossings, cross-sections and the tactile legend.
- `analyze_model` and `check_print`: warnings with exact fixes, volume and filament, and a print pack (STL, attribution, print notes, submission notes).
- `create_sampler`: a calibration plate for finding which line shapes, sizes and spacings you can tell apart. Tactile sizes come from your own tactile profile, never from fixed defaults.
- `doctor` and `list_capabilities`: check the installation and see what is available.

## Install for development

Python runs only through [uv](https://docs.astral.sh/uv/). From this folder:

```bash
uv sync
```

```bash
uv run pytest -q
```

Models are written to `~/TactileModels`. The config file is created on first use; `uv run tactile-terrain doctor` prints its path.

## Use with Claude

Run `uv sync` once first, so Claude does not have to build the environment while it starts the server.

Load the plugin straight from this folder for a session:

```bash
claude --plugin-dir C:/path/to/bold_tactile_explore
```

Or install it from this folder as a local marketplace:

```bash
claude plugin marketplace add C:/path/to/bold_tactile_explore
```

```bash
claude plugin install tactile-terrain@tactile-terrain-local
```

Any other MCP client can run the server directly:

```bash
claude mcp add tactile-terrain -- uv run --directory C:/path/to/bold_tactile_explore tactile-terrain mcp
```

## Command line

```bash
uv run tactile-terrain build examples/winter-park-library.json
```

```bash
uv run tactile-terrain doctor
```
