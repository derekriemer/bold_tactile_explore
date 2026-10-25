# Plans

Plans derived from [`docs/design-spec.md`](../docs/design-spec.md), the spec. The spec is the source of truth for *what* is built, and it's a living document: when a decision changes what the tool does, edit the spec instead of adding a note here. These files decide *how* and *in what order*.

| File | What it covers |
|---|---|
| [phase-1-mvp.md](phase-1-mvp.md) | Phase 1 as 13 self-contained milestone briefs (M0–M12), each listing the spec sections to read, what to build, and its acceptance tests. Design decisions live in the spec's "Implementation design" section. |
| [winter-park-prototype.md](winter-park-prototype.md) | The first real model: area, data, spec, expected numbers, and the validation protocol |
| [claude-plugin-and-skill.md](claude-plugin-and-skill.md) | Packaging as a Claude plugin (MCP server + skill), local install, and the Winter Park test run |
| [printing-access.md](printing-access.md) | Louisville library 3D print rules (152 mm, 8 h, 5/month), printer profiles, how Winter Park fits, questions for the library and your friend. Not yet folded into the other plans. |
| [packaging-and-distribution.md](packaging-and-distribution.md) | What a user must install, PyPI/uvx, plugin marketplace, `.mcpb` one-file install, print packs and filament estimates |

## Status

- 2026-10-23: plans drafted. No code yet.

## Environment facts checked on 2026-10-23

- Windows 11. `python` is not on PATH; `uv` 0.11 is installed and has CPython 3.13 managed. All Python is run through `uv`.
- Network from this machine reaches the USGS 3DEP image service, the USGS NHDPlus HR map service, and the Overpass API (Overpass needs a `User-Agent` header, it returned 406 to a bare request). This answers the spec's open question about network access for local runs; it still needs rechecking from inside the MCP server once it's launched by the Claude app.
- No PrusaSlicer or OrcaSlicer CLI on PATH, so `check_print` will report print time as unavailable (which Phase 1 does anyway).
