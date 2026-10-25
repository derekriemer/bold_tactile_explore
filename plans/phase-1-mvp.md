# Phase 1 build plan

Phase 1 is the roadmap section of the same name in [`terrain-print-handoff.md`](../terrain-print-handoff.md) (the spec). This file only says **in what order** and **how we know each step is done**. *What* to build is in the spec, mostly under **Implementation design**. If a brief and the spec disagree, the spec wins; fix the brief.

## How to use this file

- **One milestone per session.** Start a fresh session, read `CLAUDE.md`, this file's "Conventions" section, the one milestone brief, and only the spec sections it lists.
- A milestone is done when its acceptance tests pass with `uv run pytest -q` and its manual check (if any) has been done.
- **Finishing a milestone:**
  1. Commit, with a message starting `M<n>:`.
  2. Tick the milestone in the status list below.
  3. If the work changed a design decision, edit the spec in the same commit.
- If a brief turns out to be wrong or too vague to act on, stop and ask the user rather than inventing scope.

## Status

- [x] M0 Scaffold
- [x] M1 Spec, config and profiles
- [x] M2 Geometry core
- [x] M3 Data providers and `resolve_area`
- [x] M4 Line features and the full build
- [x] M5 Analyzers
- [x] M6 `describe_model`
- [x] M7 MCP server and editing
- [x] M8 `check_print`, print pack and `doctor`
- [ ] M9 Sampler plate
- [ ] M10 Plugin and skill
- [ ] M11 Winter Park validation
- [ ] M12 Release 0.1.0

M10 can start any time after M7. M12 waits for M11.

## Conventions (all milestones)

- **Python:** run through `uv` only (`python` is not on PATH). Python 3.12 or newer. Use `ruff` for linting and formatting, and `pytest` for tests.
- **Code layout:**
  - All code lives in `src/tactile_terrain/`.
  - Plain functions in `api.py` do the work. `server.py` and `cli.py` are thin wrappers around them, so everything can be tested without MCP.
- **Tests:**
  - Use synthetic grids from `tests/synthetic.py` wherever possible.
  - Real data comes only from small recorded fixtures in `tests/fixtures/`. Tests that hit the network are marked `@pytest.mark.network` and skipped by default (`-m "not network"` in the pytest config).
- **Meshes:** every test that builds a mesh asserts `is_watertight` and `is_volume`, through the shared helper `assert_printable(mesh)`.
- **Tactile numbers:** none in code (invariant 1). They come from the profile object; the M1 test enforces this.
- **Tool output:** every user-facing string follows the spec's describe_model output rules: plain text, units on every number, never a reference to images.
- **Invariant comments:** where code implements a design invariant, add a comment such as `# Invariant 3: see docs/design-invariants.md`.

## Repository layout (target at the end of Phase 1)

```
pyproject.toml, uv.lock, LICENSE, README.md, CONTRIBUTING.md, CLAUDE.md
docs/design-invariants.md
.claude-plugin/plugin.json, .claude-plugin/marketplace.json, .mcp.json
skills/tactile-terrain/SKILL.md
examples/winter-park.json, winter-park-library.json, winter-park-flat.json, winter-park-cirques.json
src/tactile_terrain/
  api.py  server.py  cli.py
  spec.py  config.py  registry.py  geo.py  mesh.py  styles.py  compose.py
  warp.py  textures.py  glyphs.py  sampler.py  describe.py  printpack.py  doctor.py  attribution.py
  tactile/profile.py  tactile/presets/{fine,standard,coarse,extra_coarse}.toml
  pipeline/stages.py  pipeline/cache.py
  providers/base.py  providers/usgs3dep.py  providers/nhd.py  providers/osm.py  providers/nominatim.py
  analyzers/base.py  analyzers/{relief,min_width,bed_fit,spacing,resolution}.py
  export/stl.py
tests/  (synthetic.py, helpers.py, fixtures/, test_*.py)
```

---

## M0 Scaffold

**Goal:** an empty but correctly set-up package that installs, lints and tests.

**Read:**
- spec "Design invariants"
- spec "Suggested libraries" (dependencies, package and script names)
- spec "Extensibility → Registries"

**Build:**
- `uv init --package` with the package `tactile_terrain` and distribution `tactile-terrain`. Add every dependency from "Suggested libraries", plus dev dependencies `pytest` and `ruff`.
- Console script `tactile-terrain` in `cli.py`, with subcommands `mcp`, `build` and `doctor` that print "not implemented yet".
- `registry.py`:
  - a generic `Registry[T]` with `register(name, obj)`, `get(name)` (whose error lists the valid names) and `names()`
  - loading from entry-point groups `tactile_terrain.<kind>`
  - one registry each for elevation providers, line providers, area providers, line styles, textures, warps, analyzers, joints and exporters, all empty for now
- `docs/design-invariants.md`, copied from the spec section. `CONTRIBUTING.md` points to it.
- `LICENSE`: the full AGPL-3.0 text (decided; SPDX `AGPL-3.0-or-later`). Set `license` in `pyproject.toml` to match. Check that every dependency licence is compatible.
- `README.md` stub.
- `.gitignore` covering `.venv/`, `models/`, `__pycache__/`, `*.stl`, except `tests/fixtures/`.
- pytest config with the `network` marker excluded by default.

**Acceptance tests:**
- `tests/test_registry.py`:
  - registering and getting a name works
  - an unknown name raises an error whose message lists the registered names
  - the entry-point loading function finds an entry point declared in a test fixture (or use monkeypatched `importlib.metadata`)
- `uv run tactile-terrain --help` exits 0 and lists the three subcommands (test with `subprocess`).
- `uv run ruff check` is clean.

**Out of scope:** any geometry or data.

---

## M1 Spec, config and profiles

**Goal:** typed, validated spec, user config, tactile profiles and printer profiles, plus the invariant-1 enforcement test.

**Read:**
- spec "Implementation design" subsections: Spec schema v1, Tactile profile file, Printer profile, Files on disk
- spec "Design invariants" 1 and 6

**Build:**
- `spec.py`:
  - pydantic v2 models for spec v1, with `extra="forbid"` everywhere
  - `schema_version` and a `MIGRATIONS` dict (empty for now)
  - reserved `regions`, `textures` and `tiles` keys accepted
  - `scale_m_per_mm` or `long_side_mm`, exactly one
  - `load_spec(path)` and `save_spec(spec, path)` with stable key order and 2-space indent, so diffs are readable
- `tactile/profile.py`:
  - a `TactileProfile` model
  - loading shipped presets from package data, and user profiles from the config directory
  - `extends` resolution, with the child's values overriding the parent's, and cycles detected
  - pointed-style validation: `height ≥ width / 2`
- The four preset TOML files, with values from the spec. `coarse` is about 1.4× and `extra_coarse` about 2×; the coarse presets drop `pointed` from `distinguishable_profiles`.
- `config.py`:
  - a `UserConfig` model, read from `platformdirs.user_config_dir("tactile-terrain")/config.toml`
  - created with defaults on first load: `models_dir = ~/TactileModels`, active profile `standard`, a `[printers.louisville-library]` entry from the spec, and default printer `louisville-library`
  - a `TACTILE_TERRAIN_CONFIG_DIR` environment variable override, so tests use a temporary directory
- Validation of registry names in spec fields. For now only `tactile_profile` and `printer` can be checked; providers and styles are checked once registered in M3 and M4.

**Acceptance tests:**
- `test_spec.py`:
  - the Winter Park example from the spec round-trips through `load_spec`/`save_spec` byte-identically
  - an unknown top-level key raises an error naming the key
  - an unknown nested key raises an error naming the key
  - giving both `scale_m_per_mm` and `long_side_mm` raises
  - the reserved keys are accepted
- `test_profiles.py`:
  - all four presets load
  - a user profile with `extends = "standard"` and one override returns the merged values
  - an `extends` cycle raises
  - a pointed style with `height < width / 2` raises
  - no profile field name contains a medical term (check against a small deny-list: diabetic, neuropathy, condition, diagnosis), for invariant 6
- `test_config.py`: the first load creates the file in a temporary directory, and the second load reads it back.
- `test_no_hardcoded_tactile.py`:
  - the `ast` scan described in the spec, over `styles.py`, `compose.py`, `analyzers/`, `describe.py` and `sampler.py`, with an allow-list file `tests/tactile_literal_allowlist.txt` (one `module:line-pattern  # reason` per line)
  - the scan passes on empty or missing modules
  - a test plants a temporary module containing `1.6` and checks that the scan catches it

**Out of scope:** using the profiles for geometry.

---

## M2 Geometry core

**Goal:** heightfield to watertight STL, the print coordinate transform, and the pipeline skeleton with caching.

**Read:**
- spec "Implementation design" subsections: Print coordinates, Print grid, Mesh
- spec "Extensibility → Pipeline"

**Build:**
- `tests/synthetic.py`: `cone(...)`, `plane(...)`, `valley(...)` that return a world-space elevation array plus a transform, with analytically known heights.
- `geo.py`:
  - `utm_crs_for(bbox)`
  - a `PrintTransform` with `world_to_print(x, y)`, `print_to_world(...)`, `elevation_to_z(e)` and `z_to_elevation(z)`, built from the bbox, scale, exaggeration, base and minimum elevation
- `mesh.py`: `heightfield_to_mesh(z: ndarray, grid_mm) -> trimesh.Trimesh` (top, walls, bottom).
- `export/stl.py`: a binary STL exporter registered as `stl`.
- `warp.py`: the `Warp` protocol and the `identity` warp, registered. `textures.py`: the `Texture` protocol (empty registry).
- `pipeline/stages.py`:
  - the stage functions `fetch`, `project`, `warp`, `heightfield`, `texture`, `lines`, `base`, `tile` and `export`
  - each takes `(spec, upstream)` and returns a result. `warp`, `texture` and `tile` pass through.
- `pipeline/cache.py`: stage results cached on disk under the model's `cache/stages/`, keyed by a hash of the spec slice each stage reads plus the upstream hash.
- `tests/helpers.py`: `assert_printable(mesh)`.

**Acceptance tests:**
- `test_mesh.py`:
  - a flat grid, a cone and a valley each produce printable meshes
  - the bounding box equals (grid extent, grid extent, max z) within 1e-6
  - the volume of a flat 10 × 10 × 3 mm block is 300 mm³ within 1e-6
- `test_geo.py`:
  - `world_to_print` then `print_to_world` round-trips within 1e-6 m
  - the south-west corner maps to (0, 0)
  - the minimum elevation maps to `base_mm`
  - 1,000 m above the minimum, at a scale of 100 and an exaggeration of 1.5, maps to `base + 15`
  - the UTM zone for Winter Park is EPSG:32613
- `test_pipeline_cache.py`:
  - running the pipeline twice on a synthetic spec runs each stage once (count calls with a spy)
  - changing `z_exaggeration` reruns `heightfield` and the stages after it, but not `fetch` or `project`
- `test_export.py`: the exported STL reloads with `trimesh.load` and is printable.

**Out of scope:** real data, line features.

---

## M3 Data providers and `resolve_area`

**Goal:** real elevation, rivers, roads, lifts and named points for a bounding box, cached; and `resolve_area`.

**Read:**
- spec "Data sources"
- spec "Implementation design → Data access" and "Files on disk"
- spec "Tools → resolve_area"

**Build:**
- `providers/base.py`:
  - `ElevationProvider.get(bbox, resolution_m) -> (array, transform, crs)`
  - `LineProvider.get(bbox, filter) -> list[LineFeature]`, where `LineFeature` has the geometry in WGS84, `name`, `kind` and an attribute dict
  - `AreaProvider` (protocol only)
  - a `PointProvider` for named points
- `providers/usgs3dep.py` (registered `usgs3dep`), `providers/nhd.py` (`nhd`, HR first and V2 as fallback, as in the spec), `providers/osm.py` (`osm`: roads, aerialways and named points in one Overpass query), and `providers/nominatim.py`.
- A download cache in `<model>/cache/` keyed by provider, bbox rounded to 1e-5°, resolution and filter hash. A cache hit makes no network call.
- Polite HTTP: a `User-Agent` of `tactile-terrain/<version> (+repo URL)`, at least 1 s between Overpass calls, and retries with backoff on 429 and 504.
- Name normalisation for `include_names`.
- `api.resolve_area(place=None, bbox=None, width_km=None) -> str`, returning the text report described in the spec:
  - the bbox and size in km
  - the UTM zone
  - the elevation range, from a coarse 90 m fetch
  - the available 3DEP resolutions
  - counts by stream order with named streams listed, roads by class with refs, lifts by type with names, and named peaks and passes
- Record fixtures: a script `tests/fixtures/record.py` (network) that saves a **small** Winter Park sub-area (about 3 × 3 km around the Winter Park base) as a GeoTIFF plus GeoJSON. The recorded files are committed, and should total under 2 MB.

**Acceptance tests:**
- `test_providers_offline.py`:
  - with the fixture files placed in a cache directory, every provider returns data without network access (monkeypatch `httpx` to raise)
  - stream-order filters and `include_names` behave as specified, including "Ck" matching "Creek"
- `test_resolve_area.py` (offline, from fixtures): the report contains the bbox, the size in km with units, the elevation range in m, and at least one named stream and one lift name; it contains no image references.
- `test_providers_network.py` (`@pytest.mark.network`): for the Winter Park bbox in the spec, there's elevation between 2,500 and 4,200 m, a river named "Fraser River", a road with ref "US 40", and at least 10 aerialways.

**Manual check:** run `uv run pytest -m network -q` once and paste the `resolve_area` text for Winter Park into the session, to sanity-check the names.

**Out of scope:** printing the lines.

---

## M4 Line features and the full build

**Goal:** `create_model` builds a real STL with raised lines, in terrain and flat modes (from Python, not MCP yet).

**Read:**
- spec "Implementation design" subsections: Line features are cross-section profiles…, Print grid, Files on disk
- spec "Making line types distinguishable by touch"

**Build:**
- `styles.py`: a `LineStyle` with `profile`, `width_mm`, `height_mm` and `h(d: ndarray) -> ndarray`; the profiles `rounded`, `flat_top` and `pointed`, registered. Widths and heights always come from the resolved profile entry.
- `compose.py`: the procedure in the spec. It clips, simplifies, drops short pieces (returning a list of what was dropped), computes distances, and takes the max over features. In flat mode, terrain is a constant.
- Pipeline `lines` and `base` stages wired to it.
- `attribution.py`: `ATTRIBUTION.txt` from the providers used (each provider declares its source, licence and attribution text).
- `api.create_model(name, area, print, mode, features, style=None, overwrite=False) -> str`: it writes the spec, runs the pipeline, exports the STL and attribution, and returns a short build summary. Analysis is added in M5.
- `cli.py build <spec.json>` runs the same thing from a spec file.
- The four `examples/winter-park*.json` specs, per the Winter Park plan.

**Acceptance tests:**
- `test_styles.py`, for each profile:
  - `h(0) == height`
  - `h(width/2) == 0` (within 1e-9)
  - it's monotonic non-increasing in `d`
  - `flat_top` has a plateau and 60° shoulders
  - `pointed`'s flank slope is at least 45°
- `test_compose.py`:
  - On a synthetic plane at 3 mm with one straight east–west line of each style: the max over the cells on the centreline equals `3 + height` within one grid quantisation, and the raised width measured across the line equals `width` within ±1 grid cell.
  - Two overlapping features take the taller value.
  - A line shorter than `min_feature_length_mm` is dropped and reported.
  - In flat mode, the surface outside lines equals `base_mm` exactly.
- `test_build_offline.py`:
  - building the fixture sub-area in terrain and flat modes produces printable STLs, and `ATTRIBUTION.txt` mentions USGS and OpenStreetMap
  - rebuilding with no changes makes no provider calls

**Manual check:** `uv run tactile-terrain build examples/winter-park-library.json` succeeds. Report the STL size and build time.

**Out of scope:** analysis text, MCP.

---

## M5 Analyzers

**Goal:** `analyze_model` with the relief, min width, bed fit, parallel spacing and resolution analyzers, each suggestion carrying its patch; run automatically by `create_model`.

**Read:**
- spec "Implementation design → Analyzers"
- spec "Model analysis and suggestions"
- the printer profile

**Build:**
- `analyzers/base.py`: the `Analyzer` protocol, returning `AnalyzerResult(metrics: dict, suggestions: list[Suggestion])`, where a `Suggestion` has `severity` ("info" | "warn" | "error"), `message` and `patch`.
- The five analyzers, registered.
- `api.analyze_model(name) -> str`: text with warnings first, each followed by "Fix: <patch in plain words>".
- `create_model` appends the analysis to its summary.

**Acceptance tests (`test_analyzers.py`, synthetic and exact):**
- **Relief:**
  - A cone with relief 2 mm and `min_relief_mm` 8 suggests the z exaggeration that gives `target_relief_mm` (12 mm), rounded to 0.5, and the patch sets that value.
  - When the bed height cap applies, the suggestion is capped.
  - Flat mode gives no relief result.
- **Min width:** a style at 1.0 mm with a 0.5 mm nozzle (floor 1.5) gives a warning with a patch that sets the width to 1.5.
- **Bed fit:**
  - A 128 × 189 mm footprint on a 152 mm bed with a 5 mm margin gives an error.
  - The suggested scale is the smallest multiple of 5 m/mm that fits: compute it in the test from the synthetic extent.
- **Spacing:** two parallel lines 2 mm apart edge to edge, over 20 mm, with a 3 mm minimum, are reported at the right position. Lines 4 mm apart are not reported.
- **Resolution:** a 1 m source on a 20 m-per-cell grid reports detail lost to the grid.
- **No hard-coded numbers:** the M1 scan still passes over `analyzers/`.

---

## M6 `describe_model`

**Goal:** the full text description, the most important output.

**Read:**
- spec "Implementation design → describe_model details" (follow it exactly)
- spec "Tools → describe_model"
- design invariants 4 and 5

**Build:**
- `describe.py`, with one function per section so each can be tested alone. It returns a string.
- `api.describe_model(name, sections=None) -> str`.
- Describe settings (`summit_radius_mm`, `describe_min_run_mm`) in the user config, under `[describe]`.

**Acceptance tests (`test_describe.py`, synthetic):**
- **Line course:** a line entering the south edge at x = 60, running north for 50 mm, then north-west for 30 mm, then leaving the west edge. The text contains "enters the south edge at x = 60 mm", then "north" with "50 mm", then "north-west", then "exits the west edge". A 3 mm wiggle is absorbed, not reported.
- **Lift:** the bottom and top terminal positions and elevations are reported, the lower one first.
- **Crossing:** two crossing lines are reported once, with a position within 1 grid cell and the taller profile named as on top.
- **Summits:** on two cones of different heights, both are listed, the higher first, with positions within one cell. A named point within 3 mm gives its name.
- **Cross-sections:**
  - the default four sections are present, with values every 10 mm
  - `sections=[{"y_mm": 40}]` adds one with values every 5 mm
  - `{"through": "<name>"}` resolves a named feature
- **Legend and distortion:** the legend lists exactly the styles in use; the distortion section says there's no horizontal distortion and gives the exaggeration.
- **Output rules:** no line is longer than 200 characters; there are no Markdown tables with more than four columns; the text contains no "image", "see", "shown", "colour" or "color"; every number is followed by a unit or is a coordinate pair label. Use a small regex check, with an allow-list for "x =" and "y =".
- **Golden test:** describing the fixture sub-area matches a snapshot in `tests/fixtures/describe_snapshot.txt`. Regenerate it only deliberately, with an environment variable.

---

## M7 MCP server and editing

**Goal:** every Phase 1 tool callable over MCP; `update_model` with patches, shortcuts and undo.

**Read:**
- spec "Tools" (all of it)
- spec "Implementation design" subsections: Spec schema v1 (`update_model` rules) and Server hygiene
- spec "Extensibility → MCP tools"

**Build:**
- `api.update_model(name, changes)`:
  - a JSON merge-patch plus the shortcuts `z_multiply`, `crop_percent`, `drop_feature` and `revert_to`
  - backs up the old spec as `spec.<n>.json`, validates, rebuilds and analyzes
  - returns a before → after list
- `api.list_capabilities()` (every registry with names, parameters and one-line descriptions, plus the active profile, the presets and the printers), `api.list_models()` and `api.get_spec(name)`.
- `server.py`:
  - a MCPServer (mcp 2.x, formerly FastMCP) stdio server with tools wrapping the api functions
  - `instructions` text from the spec
  - progress notifications during builds
  - logging to stderr
  - lazy imports
- `cli.py mcp` runs the server.

**Acceptance tests:**
- `test_update.py`:
  - `z_multiply: 2` doubles the exaggeration, and the before → after text says "1.5 → 3.0"
  - `crop_percent: {east: 10}` moves the east bbox edge by 10% of the width
  - `drop_feature: "lift"` removes lifts
  - `revert_to: 1` restores the first spec exactly
  - an invalid patch leaves `spec.json` unchanged and returns an error naming the bad key
- `test_server.py`:
  - start the server in-process with the MCP client test utilities (or as a subprocess over stdio)
  - list the tools and check the full set is present
  - call `list_capabilities` and `describe_model` on a fixture model, and check that text comes back
  - nothing but JSON-RPC is written to stdout
- `test_startup.py`: importing `tactile_terrain.server` doesn't import `rasterio`, `py3dep` or `trimesh` (check `sys.modules`).

**Manual check:** `npx @modelcontextprotocol/inspector uv run tactile-terrain mcp`, or any MCP client, and call `resolve_area` for Winter Park.

---

## M8 `check_print`, print pack and `doctor`

**Goal:** everything needed to hand a file to the library or a friend.

**Read:**
- spec "Implementation design" subsections: check_print and the print pack, doctor, Printer profile, Mesh (decimation)
- `plans/printing-access.md`

**Build:**
- `api.check_print(name)`: mesh checks, volume, solid mass, the slicer step if available, and the print pack.
- `printpack.py`: writes `print-pack/` with the STL, the attribution, `PRINT-NOTES.txt` and `SUBMIT-NOTES.txt`.
- Decimation of near-flat regions when `max_stl_mb` would be exceeded. The result must still pass `assert_printable`.
- `doctor.py`, plus `api.doctor()`, the `doctor` tool and the `cli.py doctor` command.

**Acceptance tests:**
- `test_check_print.py`:
  - On a 10 × 10 × 3 mm block, the volume is 0.300 cm³ and the solid mass at 1.24 g/cm³ is 0.372 g. The text says "upper bound".
  - With no slicer on PATH (monkeypatch `shutil.which`), the text says the print time is unavailable and states the printer's 8-hour limit.
- `test_printpack.py`: all files exist; `PRINT-NOTES.txt` contains the footprint, "no supports" and the filament line; `SUBMIT-NOTES.txt` contains the printer's `submit_notes`.
- `test_decimate.py`: a mostly flat synthetic model with `max_stl_mb` set low decimates to under the limit, stays printable, and keeps the line ridge heights within one grid cell.
- `test_doctor.py`: with network monkeypatched off, it reports each endpoint as unreachable without crashing, and includes the config path.

**Manual check:** run `uv run tactile-terrain doctor` on this machine and paste the output.

---

## M9 Sampler plate

**Goal:** `create_sampler` produces the single-round calibration plate, and `describe_model` reads it out.

**Read:**
- spec "Tactile profiles and the sampler" and "Implementation design → Sampler plate layout"
- design invariants 2 and 3

**Build:**
- `glyphs.py`: digits 0–9 as polylines in a unit box (seven-segment style).
- `sampler.py`: builds the plate as a heightfield, with samples, numerals and notches all drawn through `compose.py` and the profile's styles. The plate's spec is saved like any model's, with `kind: "sampler"` and the shuffle seed.
- `api.create_sampler(profile, focus=None)`. `focus` limits the plate to one row type.
- `describe.py`: the sampler readout ("Row 1, sample 3: flat-top 2.0 mm wide, 1.5 mm tall, next to rounded at the same size").

**Acceptance tests (`test_sampler.py`):**
- the plate is printable and fits within 140 × 120 mm, or the printer bed if smaller
- row 1 contains every pair listed in the spec, including both control pairs
- the same seed gives the same layout, and a different seed gives a different order
- the readout lists every sample with its numeral, and the numerals in the readout match the positions of the glyphs in the geometry (sample the heightfield at the numeral position: it's raised)
- there are as many notches on the left edge as each row's number
- with `label_mode = "numerals"` there's no Braille; numerals are always present
- the `coarse` preset produces wider lines and fewer profile pairs (pointed excluded)

**Manual check:** read the sampler `describe_model` text aloud with NVDA, and confirm it's clear enough to use while touching the plate.

---

## M10 Plugin and skill

**Goal:** the Claude plugin (MCP server plus skill), loadable from this checkout.

**Read:** `plans/claude-plugin-and-skill.md` (all of it).

**Build:** the plugin files exactly as in that plan, with `.mcp.json` using `uv run --directory ${CLAUDE_PLUGIN_ROOT}`. Copy the skill draft into `skills/tactile-terrain/SKILL.md`. Check the current Claude Code plugin docs for manifest fields and CLI commands; send a Haiku subagent with a narrow question.

**Acceptance tests:**
- `test_plugin_files.py`:
  - `plugin.json`, `marketplace.json` and `.mcp.json` parse
  - the server name in `.mcp.json` matches what the skill refers to
  - `SKILL.md` has `name` and `description` front matter
  - every tool named in `SKILL.md` exists in the server's tool list
- Manual: `claude --plugin-dir .` starts, `/mcp` shows `tactile-terrain` connected, and `list_capabilities` works from a prompt.

---

## M11 Winter Park validation

**Goal:** the spec's Winter Park success criteria, run through the plugin.

**Read:** `plans/winter-park-prototype.md`, `plans/printing-access.md`, and `plans/claude-plugin-and-skill.md` (the "Winter Park test run" section).

**Do:**
- the 10-step test run from the plugin plan
- build `winter-park`, `winter-park-library`, `winter-park-flat`, `winter-park-cirques` and `sampler-standard`
- print packs for the library versions

**Done when:**
- every model passes `check_print`
- the user has reviewed the `describe_model` text against their knowledge of the area
- the problems found are recorded in `plans/winter-park-results.md`, each as a data issue, a describe bug or a skill fix

Physical prints happen when the library or a friend can print. Their results are added to the same file later, and don't block M12.

---

## M12 Release 0.1.0

**Goal:** installable by someone who isn't a developer.

**Read:** `plans/packaging-and-distribution.md`.

**Build:**
- PyPI publishing from GitHub Actions on a tag, with trusted publishing
- `.mcp.json` switched to `uvx tactile-terrain@0.1.0 mcp`
- the GitHub marketplace entry
- the `.mcpb` bundle build, if the `uv` server type is supported by then
- README install instructions written for screen-reader users

**Done when:**
- a clean Windows user account with only `uv` and Claude installed can install the plugin and build the sampler
- the `.mcpb` install flow has been tried with NVDA, and the result is recorded

Needs the user's go-ahead before publishing anything.
