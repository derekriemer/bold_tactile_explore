# Handoff: tactile terrain printing (MCP server + skill)

## Goal

Build an open-source tool that turns elevation data plus line features (rivers, roads, trails, ski lifts) into 3D-printable models (STL/3MF), designed first for blind users who check the model by text description and by touch.

Ship it as one repository that is:

- a standalone MCP server (Python), usable with any MCP client
- a Claude plugin (the MCP server plus a skill) that installs in both Claude Code and Cowork

The user is blind and uses NVDA. Every result the tools return must be useful as text. Never rely on images or rendered previews.

## Design invariants (do not remove)

These are deliberate decisions, kept explicit so that a later refactor or "simplification" doesn't quietly undo them. Copy this section into the repo as `docs/design-invariants.md`, and point to it from `CONTRIBUTING.md` and from comments at the relevant code.

1. **Tactile parameters are per person, never hard-coded.**
   - *Why:* tactile sensitivity varies widely, and the people most affected are the people this tool is for. Diabetic neuropathy is common among blind people, because diabetes is a leading cause of blindness. Age, calluses, other neuropathies, and plain biological variation all reduce what a fingertip can resolve. A single tuned default works only for whoever tuned it, and silently excludes everyone else.
   - *Rule:* every line width, line height, spacing, texture amplitude, relief threshold and label size comes from the active tactile profile.
   - *Enforce with a test:* the analyzers and style code must not contain hard-coded numeric tactile thresholds. Search the code for them, or require all of them to come through the profile object.
2. **The sampler and calibration flow is a core feature, not a developer tool.**
   - *Why:* it's the only way a user can find their own limits. Without it, the profiles in invariant 1 are just guesses.
   - *Rule:* don't remove it, don't move it behind a developer flag, and don't reduce it to detecting single samples. The plate must test whether two samples can be told apart.
3. **Sample and tile IDs must not depend on reading Braille.**
   - *Why:* many blind people don't read Braille. Reduced sensitivity can make fine Braille unreadable even for people who do.
   - *Rule:* always include a non-Braille ID, such as counted notches or large raised numerals. Braille is optional and in addition.
4. **Every output must be fully usable as text.**
   - *Why:* the primary users can't see renders. A feature that only shows up in an image doesn't exist for them.
   - *Rule:* every tool returns structured text, and `describe_model` covers every feature, region, warp and legend entry. Images are optional, for model context only.
5. **Distortion is always disclosed.**
   - *Why:* a squished or exaggerated map that doesn't say so teaches false geography.
   - *Rule:* every warp and every regional z scale carries a texture by default, and is reported by `describe_model` with its actual ratios.
6. **Profiles never collect health information.**
   - *Why:* it's not needed, and it's sensitive.
   - *Rule:* profiles hold only numbers and choices. Presets are named by sensitivity level, never by medical condition.

## Architecture

- A local MCP server (stdio) running on the user's machine, which has full network access.
- Files are written to disk. Tools return text summaries, never mesh bytes.
- One project folder per model, for example `models/<name>/`:
  - `spec.json`: the single source of truth (area, print size, scales, features, style)
  - `<name>.stl`, `<name>.3mf`: always rebuilt from the spec
  - `cache/`: raw elevation and vector downloads, keyed by bounding box and resolution, so edits rebuild quickly without network access
  - `ATTRIBUTION.txt`: generated automatically from the data sources used
- Every edit changes the spec and rebuilds. The spec should be easy to compare between versions so edits can be undone.
- Personal defaults (units, tactile profile, models folder) live in a user config file, not in code or the skill.
- Printers are named profiles in that config: bed size, nozzle, print grid cell, and any service limits such as maximum print hours. Each model names its target printer, and the analyzers check against it. One user may print in several places, such as a library and a friend's printer.

## Data sources

| Feature | Source | License |
|---|---|---|
| Elevation | USGS 3DEP (10 m nationwide, 1 m lidar where available), via `py3dep` or the 3DEP image service | Public domain |
| Rivers and streams | USGS NHDPlus HR flowlines, with a stream-order or drainage-area attribute for filtering | Public domain |
| Roads | OpenStreetMap `highway=*`, filtered by class | ODbL, attribution required |
| Trails | OpenStreetMap `highway=path/footway/track` | ODbL |
| Ski lifts | OpenStreetMap `aerialway=*` (chair_lift, gondola, and so on) | ODbL |
| Ski runs (later) | OpenStreetMap `piste:type=downhill` | ODbL |

Fetch OpenStreetMap data through Overpass, with a configurable endpoint and polite rate limiting.

### Outside the US

3DEP and NHD cover the US only. For anything else, the subcontinent included:

- **Elevation:** Copernicus DEM GLO-30 or GLO-90, from AWS Open Data. It has its own license terms, so check them and record them in the attribution file.
- **Rivers:** HydroRIVERS (part of HydroSHEDS), which has an order or discharge attribute for filtering. Check its license. Natural Earth is a coarse, public-domain fallback.
- **Coastline and ocean:** OpenStreetMap or Natural Earth land polygons. The ocean becomes a flat area with its own texture.
- **Projection:** for regions larger than a UTM zone, use a suitable conic projection, such as Lambert conformal conic or Albers. Pick it from the bounding box automatically, and allow it to be overridden.

Make the data source a provider interface (elevation, lines, areas) chosen by region. The rest of the code should never know which provider it is using.

Because OpenStreetMap data is used, attribution is mandatory: write `ATTRIBUTION.txt`, and optionally emboss a short credit on the base or the underside.

## Suggested libraries

- `rasterio` and `numpy`: read, reproject and resample the elevation grid
- `scipy`: resampling and distance helpers
- `pyproj`: project to a local metric CRS (UTM)
- `shapely` (2.x): clip, simplify and measure distance to lines in print space
- `trimesh`: mesh assembly, checks and export
- `manifold3d`: robust booleans, for later backends such as separate 3MF bodies and joints. The Phase 1 build doesn't need it (see Implementation design).
- `py3dep` and `pynhd` (HyRiver): 3DEP elevation and NHD flowlines
- `httpx`: Overpass and Nominatim requests
- `pydantic` (v2): spec, profile and config models
- `platformdirs`: config and data locations
- `mcp` (`MCPServer` in the 2.x SDK, formerly `FastMCP`): the server. Anticipated failures are raised as `ToolError` so their text reaches the model; other exceptions are reported only as "Error executing tool".

Python 3.12 or newer, managed with `uv` (`pyproject.toml` plus `uv.lock`). Package `tactile_terrain`, distribution `tactile-terrain`, one console script `tactile-terrain` with subcommands `mcp`, `build` and `doctor`.

## Tools

1. **`resolve_area(place | bbox, width_km?)`**
   - Returns the bounding box, elevation min and max, the available resolution, and the count of features by type inside the area.
   - Cheap and does not build anything.
2. **`create_model(name, area, print_mm, z_exaggeration, base_mm, features, mode)`**
   - `mode` is `"terrain"` or `"flat"`. Flat lays features onto a flat plate with no topography.
   - `features` is a list of feature types with filters, for example:
     - roads: classes `motorway`, `trunk`, `primary`
     - rivers: minimum stream order, plus specific names to always include
     - lifts: all
   - Writes the spec and builds the model.
3. **`update_model(name, changes)`**
   - Applies a partial change to the spec and rebuilds.
   - Examples: z 2x; crop 10% off the east edge; raise rivers to 1.2 mm; drop trails; undo (revert to an earlier spec version).
4. **`describe_model(name, sections?)`**, the most important tool. `sections` asks for extra cross-sections. It returns text covering:
   - footprint and height in mm, the scale (for example, 1 mm = 100 m), and the vertical exaggeration
   - the highest and lowest points, given in mm from the southwest corner, with names where known
   - the course of each line feature, for example: "Fraser River enters the south edge at x=60 mm, runs north-northwest, and exits the north edge at x=40 mm"
   - crossings, for example: road over river at (x, y)
   - two or three cross-section profiles, east to west and north to south, as mm heights at intervals
   - the tactile legend: which line style means what
5. **`check_print(name)`**
   - Checks that the mesh is watertight, and reports minimum feature width and height against the configured thresholds, plus overhang warnings.
   - Reports the mesh volume and the filament mass if printed solid, as an upper bound. Those come from the mesh, so they're exact, not a guess.
   - If a PrusaSlicer or OrcaSlicer command-line tool is available, slices the model to get real print time and filament use, and compares the time with the target printer's limit. Otherwise, says the estimate is unavailable rather than guessing.
   - Writes a print pack: the STL, the attribution, and plain-text print notes for whoever does the printing.
6. **`export(name, format, tiles?)`** (later): STL or 3MF, and tiling for areas larger than the printer bed.
7. **`analyze_model(name)`**, **`list_capabilities()`**, **`create_sampler(profile, focus?)`**: see the sections below.
8. Small helpers:
   - **`list_models()`** and **`get_spec(name)`**, so the LLM never guesses model names or current values
   - **`doctor()`**, an environment report; see Implementation design

## Making line types distinguishable by touch

This is the central design problem. Make the line styles configurable and expect several test-print iterations.

Starting defaults:

| Feature | Profile | Width | Height above terrain |
|---|---|---|---|
| River, major | Rounded ridge | 1.6 mm | 1.0 mm |
| Creek | Rounded ridge | 1.2 mm | 0.7 mm |
| Major road | Flat-topped ridge | 2.0 mm | 1.5 mm |
| Trail | Dotted (bumps about 1.2 mm, spaced about 3 mm) | 1.2 mm | 1.0 mm |
| Ski lift | Straight line plus a 2.5 mm bump at each terminal (and optionally at each tower) | 1.2 mm | 1.2 mm |

"Profile" here means the shape of a raised line in cross-section. It's a tactile code for the feature type and has nothing to do with the terrain. The profile set is:

- `rounded`
- `flat_top`
- `pointed`: a triangular peak with flanks of 45° or steeper so it prints without supports
- the dotted and terminal-bump patterns

As with textures, the legend maps meanings to profiles per model.

Whether fingers can reliably tell rounded, flat and pointed apart at 1 to 2 mm wide is an open question. Answer it empirically with the tactile sampler, below.

### Tactile profiles and the sampler (user-facing feature)

Tactile sensitivity varies a lot between people. Diabetic neuropathy, age, calluses and plain biology all change what someone can feel, so one set of defaults won't fit everyone. Calibrating per person is a shipped feature, not a developer step.

**Tactile profile:**

- A named, shareable config file holding:
  - minimum line width and height
  - minimum spacing between parallel lines
  - which line profiles and textures the person can tell apart
  - texture amplitude and spacing
  - minimum relief
  - the label mode
- Every analyzer threshold and style default comes from the active profile. Nothing is hard-coded.
- Ship presets named by sensitivity level, never by medical condition: `fine`, `standard`, `coarse`, `extra_coarse`. The coarse presets use wider and taller lines, fewer distinct categories, larger texture spacing and wider gaps.
- Profiles store only numbers and choices. They don't need, and must not ask for, any health information.

**Sampler workflow:**

1. **`create_sampler(profile, focus?)`** generates a plate around the profile's current values. `focus` narrows the plate to one area, such as line profiles or textures.
2. The plate tests **telling samples apart, not just detecting them**:
   - side-by-side pairs, so the person can judge whether two samples feel the same or different, including control pairs of identical samples, so guessing shows up
   - parallel lines at decreasing spacing
   - the same texture at increasing amplitude
3. Every sample has an ID that doesn't depend on reading Braille. Not everyone reads Braille, and fine Braille can be hard to feel with reduced sensitivity. Use counted notches along the plate edge plus large raised numerals. Braille labels are optional, and jumbo Braille is available.
4. `describe_model` on a sampler reads out the grid: "row 2, sample 3: flat-top 1.6 mm wide, 1.0 mm tall, next to rounded at the same size."
5. **`calibrate(profile, results)`** turns the user's spoken results ("I can't tell 2-3 from 2-4"; "the lines in row 4 merge after sample 2") into profile updates. A second, narrower plate is optional, to refine the values.

**Priority:** Phase 1 covers the profile file, the presets, and a single-round sampler. Phase 2 adds `calibrate` and adaptive second-round plates.

**Open source:** make it easy to share profiles. Anonymous, aggregated calibration results from many users could eventually inform better presets. That should be opt-in only.

Rules:

- Absolute minimum: 1.2 mm wide, or 3× the nozzle width, for anything meant to be felt or reliably printed.
- At crossings, the higher-priority feature stays continuous and the lower one gets a gap of about 1.5 mm. The priority order is configurable, with a default of road > river > lift > trail.
- Features follow the terrain surface: sample terrain height along the buffered line, then extrude upward. Lifts follow the terrain too, for printability, even though real lifts are cables in the air.
- Simplify lines to about 0.3 mm at print scale before buffering, to avoid mesh noise.

## Area textures and region morphs

Region morphs are a first-class concept. A morph applies a different scale to a region, and the region is stamped with a texture that says, by touch, that it has been altered. The motivating example is the Indian subcontinent: compress the huge, flat Indo-Gangetic plain so the Himalaya and the Western Ghats get more of the print area, and make it unmistakable by touch which areas are distorted.

### Spec model

```json
"regions": [
  {
    "name": "Indo-Gangetic plain",
    "geometry": "<polygon | named area | bbox>",
    "horizontal_scale": 0.4,
    "compress_axis": "auto | NS | EW | both",
    "z_scale": 3.0,
    "texture": "compressed"
  }
]
```

### Horizontal warp

- **v1, band warp:** piecewise-linear scaling along x and y in bands. It's simple, it can't fold the map over itself, line features map through it exactly, and it covers the subcontinent case reasonably well.
- **v2, polygon warp:** a smooth displacement field from region polygons and scale factors, using ARAP or a thin-plate spline with a check that the map doesn't fold over itself. This is research-grade, so leave it for later.
- Smooth the edges of each scaled band or region over a transition zone so there are no cliffs.
- `describe_model` must report each warp in plain terms, for example: "the plain is shown at 40% of true east–west width; 1 mm there is 30 km, versus 12 km elsewhere."

### Vertical scale per region

Each region can have its own z scale, blended smoothly at the edges. For example, multiply the plains by 5 to make river terraces readable, and leave the Himalaya at the global exaggeration.

### Texture library

Textures are a small, fixed set of categories, applied as surface displacement on top of the terrain. They must stay below the size of the meaningful terrain detail. Start with:

Textures are named by **pattern**, not by meaning. Each model's legend maps meanings to patterns. That way the same tactile primitive can mean "compressed" on a morphed map and "buildings" on an unmorphed or flat map.

| Pattern | Description | Typical meaning |
|---|---|---|
| `ridged` | Parallel ridges, like an accordion. It has a direction, so on a morphed map run them perpendicular to the compression axis. Spacing can encode a value. | Compressed region (morphed maps); buildings or urban (otherwise) |
| `dots_sparse` | Sparse dots | Region with a different vertical scale |
| `smooth_recessed` | Flat and smooth, slightly recessed | Ocean or large lake |
| `dots_dense` | Dense fine dots | User-defined (glacier, protected area…) |
| `crosshatch` | Crosshatch | User-defined |

**Legend rules:**

- The legend is part of the spec.
- Within one model, each pattern has exactly one meaning. The analyzer errors on conflicts.
- Morph regions claim their pattern first, and other areas can't reuse it.
- In flat mode no terrain competes with the textures, so allow a higher default texture amplitude there.

- Keep the categories few and very distinct. Tactile graphics guidelines (BANA) recommend limiting the number of area textures and line types on one graphic. Check the guidance and use it to inform the default limits and the lint warnings.
- Texture amplitude is about 0.3 to 0.5 mm, configurable. Line features and texture must not be confusable: lines are taller and continuous, textures are low and periodic.
- Textures and line styles are named categories in config, with meanings the user can redefine. The tactile legend in `describe_model` reads from this config.

## Tiles and joints

Support for tiling is needed. Big regions and tall relief will exceed one bed.

- Tile grid from the bed size. Optionally, nudge the cut lines so they don't run along major features.
- **Joints:** sliding dovetails along tile edges. Puzzle tabs or pin-and-hole are fallbacks.
  - Clearance is configurable, starting around 0.2 to 0.3 mm for FDM.
  - Generate a small **test coupon** (a pair of joint pieces) so the user can calibrate the fit on the library printer before printing a whole set.
  - The base must be thick enough for the joint, at about 5 mm or more. Force the base up when tiling is on.
- **Assembly by touch:**
  - tile ID embossed in Braille on the underside, for example "A1"
  - an orientation notch on the north edge of every tile
  - joint shapes keyed so tiles only fit the right way
- `describe_model` lists the tiles, their positions in the grid, and the assembly order.

## Model analysis and suggestions

The server should produce the numbers; the LLM should explain them and negotiate trade-offs. Don't make the LLM eyeball a mesh. Add an `analyze_model(name)` tool, and run it automatically in `create_model` and `update_model`. It returns metrics plus deterministic suggestions with the computed fix attached.

### Relief

- Printed relief in mm: overall, per region, and as a percentile spread, because the 98th-to-2nd percentile is more honest than max minus min.
- Lint example: "Printed relief is 1.1 mm; below the 8 mm comfort threshold. Setting z exaggeration to 25× gives 19 mm max and 6 mm for the 90th percentile."
- The subcontinent case makes this concrete. At 250 mm across, 1 mm ≈ 12 km, so Everest is about 0.7 mm at true scale, and the plains are about 0.02 mm. That calls for a large global z and a regional z scale.

### Feature legibility

- Narrowest printed feature, and lines below the minimum width.
- Line density: line length per cm², and the hotspots.
- Closest spacing between parallel lines. Lines too close together merge under the finger. The threshold is configurable and starts around 3 mm.
- Crossings and near-crossings.
- Texture amplitude compared with local terrain relief.
- Number of distinct line and texture categories in use, compared with the limit.

### Resolution

- Elevation data resolution compared with print resolution. Flag source detail that will be thrown away, and print detail that's finer than the data.
- Landforms smaller than the nozzle's ability to print them.

### Print

- Footprint, height, bed fit, and tile count.
- Watertightness.
- Print time and filament, from the slicer when available.

### Context for the LLM

- Named high points and passes, morph regions and their ratios, and the active printer profile and user thresholds.
- Optionally, a hillshade PNG, for an LLM that can see images to sanity-check against. It is never shown as a user-facing output.

The thresholds start as defaults and are refined from the user's test prints. Store them in config, with a comment explaining what each one is based on.

## First test case: Winter Park

The user knows this area well, which makes it the main validation target.

**Area:**

- the Fraser valley from roughly the town of Fraser south to Berthoud Pass, including the Winter Park ski area and Mary Jane
- the Second Creek cirques on the north side of Berthoud Pass
- about 20 km north to south by about 10 to 12 km east to west
- confirm the exact bounding box with `resolve_area` first

**Features:**

- **Terrain:** USGS 3DEP elevation data at 10 m. At this print scale one grid cell is about 20 m of ground, so 1 m lidar adds nothing.
- **Rivers:** the Fraser River plus significant creeks, with a stream-order cutoff to avoid clutter. Make sure Second Creek and Vasquez Creek can be included by name.
- **Roads:** US-40, including over Berthoud Pass, and other major roads only.
- **Lifts:** all lifts at Winter Park and Mary Jane.

**Print settings:** 1.5× vertical exaggeration and a 3 mm base. The scale depends on the target printer:

- 1 mm = 100 m (about 128 × 189 mm) on a printer with a bed of about 200 mm or more
- 1 mm = 125 m (about 102 × 151 mm) for the Louisville Public Library, whose limit is 152 × 152 mm and 8 hours

**Expected:** relief of roughly 2,600 m to 4,000 m. At 1 mm = 100 m that's about 14 mm at true scale and about 21 mm at 1.5×. At 1 mm = 125 m it's about 11 mm and about 17 mm.

**Success criteria:**

- The Second Creek cirques read clearly from the terrain alone. This tests whether the elevation resolution is good enough.
- The user can follow the Fraser River and US-40 by touch and tell them apart.
- The lifts are distinguishable from roads and creeks.
- `describe_model` output matches the user's knowledge of the area.

**Also build a flat-mode version** of the same area with the same features, to test the no-topography option.

## Second test case: India and Pakistan

- **Area:** the subcontinent, from the Hindu Kush and Himalaya south to Kanyakumari, and from the Indus delta east to the Brahmaputra.
- **Data:** Copernicus GLO-90 elevation, HydroRIVERS (Indus, Ganges, Brahmaputra and major tributaries), and the coastline. Major roads are optional.
- **Morph:** compress the Indo-Gangetic plain horizontally to about 40 to 50%, give it a regional z scale, and stamp it with the `compressed` texture. The ocean gets the `water` texture.
- **Tiles:** probably 2×2 or 3×3 at library bed sizes, with dovetails.

**Success criteria:**

- `analyze_model` catches the low-relief problem before the first build and proposes a z exaggeration.
- The compressed region is unambiguous by touch.
- The tiles assemble without sight.

## Implementation design

These are the concrete decisions behind the sections above. Change them here when they change.

### Print coordinates

- Units are millimetres. The origin is the **south-west corner** of the print, x runs east, y runs north, and z runs up from the bottom of the base. Every position in tool output uses these.
- World to print: project to UTM metres (zone from the bounding-box centre), subtract the south-west corner, and divide by `scale_m_per_mm`. If the spec gives `long_side_mm` instead, the scale is derived from it.
- Height: `z_mm = base_mm + (elevation_m − min_elevation_m) / scale_m_per_mm × z_exaggeration`. The lowest point of the area sits on top of the base.

### Print grid

- The model is a **heightfield**: a 2-D array of z values in mm on a regular grid. The cell size `grid_mm` comes from the target printer profile, about half the nozzle width (0.2 mm for a 0.4 mm nozzle, 0.25 mm for a 0.5 mm nozzle).
- Elevation is resampled onto the grid after projection: averaged over the area when the source is finer than the grid, bilinear when it's coarser.

### Line features are cross-section profiles added to the heightfield

Each line style is a **cross-section function** `h(d)`: the raised height as a function of the distance `d` from the line's centreline, zero for `d > width / 2`.

| Profile | h(d), for d ≤ w/2 |
|---|---|
| `rounded` | `h · sqrt(1 − (2d/w)²)` (half-ellipse) |
| `flat_top` | `h` on a central plateau, then straight shoulders at 60° from horizontal down to zero at w/2 |
| `pointed` | `h · (1 − 2d/w)`. Flanks must be 45° or steeper, so `h ≥ w/2`. Validation rejects a pointed style that breaks this. |

Building the surface:

1. Clip each line to the print footprint in print mm, and simplify it with tolerance `simplify_mm` from the tactile profile (about 0.3 mm).
2. Drop pieces shorter than the profile's `min_feature_length_mm`, and report them.
3. For each line, compute `d` for the grid cells within `width / 2` of it (vectorised `shapely.distance` on cell centres inside the line's padded bounding box), and evaluate `h(d)`.
4. `surface = terrain + max over features of h_f(d_f)`. Where features overlap, the taller profile wins. This approximates the road > river > lift > trail priority until crossing gaps arrive (Phase 3).
5. In flat mode, `terrain` is `base_mm` everywhere.

This keeps lines on the terrain surface with no booleans, and the mesh is watertight by construction. A known compromise: on a side slope, a flat-top ridge tilts with the ground. A later solid-body backend (for 3MF) can sweep the same `h(d)` along the line with `manifold3d`.

### Mesh

- One function turns a heightfield into a closed triangle mesh: two triangles per grid cell on top, four vertical walls down to z = 0, and a flat bottom. It's built directly from numpy index arrays, with no booleans.
- The tests assert `is_watertight` and `is_volume` for every mesh they build.
- Export is binary STL via `trimesh`.
- Optional decimation merges near-flat regions only, and the result must stay watertight. It's applied when the STL would exceed the printer profile's `max_stl_mb`.

### Data access

| Need | Implementation | Notes |
|---|---|---|
| Elevation | `py3dep.get_dem(bbox, resolution)` | Default 10 m; `resolution_m` can be overridden. If `py3dep` misbehaves, fall back to the 3DEP image service's `exportImage` REST call. |
| Rivers | `pynhd` against NHDPlus HR flowlines, with stream order from the value-added attributes | Fallback: medium-resolution NHDPlus V2 (`WaterData("nhdflowline_network")`, `streamorde`). |
| Roads, lifts, named points | Overpass, one combined query per area, using `httpx` | Configurable endpoint, a `User-Agent` header, at least 1 s between requests, retry on 429 and 504. Named points (`natural=peak`, `mountain_pass=yes`, `natural=saddle`) are used for naming in text only and never printed. |
| Place names | Nominatim, cached | Only for `resolve_area(place)`. |

- Name filters (`include_names`) match case-insensitively after normalising common abbreviations, such as "Ck" to "Creek" and "Mt" to "Mount".
- `resolve_area` lists the names it found, so the user can choose exact spellings.

### Files on disk

- **User config:** `platformdirs.user_config_dir("tactile-terrain")/config.toml`. It holds units, `models_dir`, the active tactile profile, the default printer, the Overpass endpoint, and `[printers.<name>]` tables. If it doesn't exist, it's created on first run with defaults, and its path is reported.
- **`models_dir`:** defaults to `~/TactileModels`. It isn't the repository, because the server's working directory is unpredictable.
- **Tactile profiles:** shipped presets live inside the package. User profiles live in `user_config_dir/profiles/<name>.toml` and can say `extends = "<preset>"`.
- **Model folder `models_dir/<name>/`:**
  - `spec.json`, plus `spec.<n>.json` for each earlier version, one per edit
  - `<name>.stl`
  - `ATTRIBUTION.txt`
  - `DESCRIPTION.md`: the default `describe_model` text, rewritten after every build, edit and `check_print`, so the model can be read without Claude running
  - `cache/`
  - `print-pack/`: the STL, the attribution, `DESCRIPTION.md`, `PRINT-NOTES.txt`, and `SUBMIT-NOTES.txt` when the printer profile has submission notes

### Spec schema v1

```jsonc
{
  "schema_version": 1,
  "name": "winter-park",
  "mode": "terrain",                                  // "terrain" | "flat"
  "area": { "bbox": [-105.86, 39.79, -105.71, 39.96], "crs": "auto" },
  "print": { "printer": "louisville-library", "scale_m_per_mm": 125, "z_exaggeration": 1.5, "base_mm": 3.0 },
  "elevation": { "provider": "usgs3dep", "resolution_m": 10 },
  "features": [
    { "type": "river", "provider": "nhd", "style": "rounded_major", "filter": { "min_stream_order": 4, "include_names": ["Fraser River"] } },
    { "type": "creek", "provider": "nhd", "style": "rounded_minor", "filter": { "min_stream_order": 3, "include_names": ["Second Creek", "Vasquez Creek"] } },
    { "type": "road",  "provider": "osm", "style": "flat_top", "filter": { "classes": ["motorway", "trunk", "primary"], "include_refs": ["US 40"] } },
    { "type": "lift",  "provider": "osm", "style": "pointed", "filter": { "aerialway": "all", "exclude": ["magic_carpet"] } }
  ],
  "style": { "tactile_profile": "standard", "overrides": {} },
  "legend": {},
  "regions": [],     // reserved, Phase 2
  "textures": [],    // reserved, Phase 2
  "tiles": null,     // reserved, Phase 2
  "built_with": "0.1.0"
}
```

- `print` takes either `scale_m_per_mm` or `long_side_mm`, not both.
- Feature `style` values are **names** that resolve through the tactile profile's `[lines]` table. Tactile numbers appear in the spec only as explicit `style.overrides`.
- `extra="forbid"` everywhere. Registry-name fields (providers, styles, profiles, printers) are validated against what's registered, and errors list the valid names.
- `update_model(changes)` takes a JSON merge-patch, plus these shortcuts:
  - `z_multiply: <factor>`
  - `crop_percent: {north|south|east|west: <percent>}`
  - `drop_feature: <type>`
  - `revert_to: <n>`

  Before writing, the current spec is saved as `spec.<n>.json`. The reply states each change as before → after.

### Tactile profile file

```toml
name = "standard"
description = "Default sensitivity."
extends = ""                        # optional preset name
min_line_width_mm = 1.2             # absolute floor; the analyzer also enforces 3 × nozzle
min_line_height_mm = 0.6
min_parallel_spacing_mm = 3.0
min_feature_length_mm = 4.0
min_relief_mm = 8.0                 # below this, relief is flagged as too low to feel
target_relief_mm = 12.0             # what the suggested z exaggeration aims for
simplify_mm = 0.3
distinguishable_profiles = ["rounded", "flat_top", "pointed"]
label_mode = "numerals"             # "numerals" | "numerals+braille" | "numerals+jumbo_braille"
label_height_mm = 8.0
label_stroke_mm = 1.5
label_relief_mm = 1.0
notch_width_mm = 3.0
notch_depth_mm = 2.0

[lines]
rounded_major = { profile = "rounded",  width_mm = 1.6, height_mm = 1.0 }
rounded_minor = { profile = "rounded",  width_mm = 1.2, height_mm = 0.7 }
flat_top      = { profile = "flat_top", width_mm = 2.0, height_mm = 1.5 }
pointed       = { profile = "pointed",  width_mm = 1.2, height_mm = 1.2 }

[sampler]
sample_length_mm = 25.0
pair_gap_mm = 6.0
widths_mm = [1.0, 1.2, 1.6, 2.0, 2.5]
heights_mm = [0.5, 0.7, 1.0, 1.5]
spacings_mm = [6.0, 4.5, 3.0, 2.0, 1.5]
```

- Presets: `fine`, `standard`, `coarse`, `extra_coarse`. The coarse presets scale widths, heights, spacing and labels up (about 1.4× and 2×) and list fewer distinguishable profiles.
- Every tactile number lives in these files and nowhere else (invariant 1).
- **Enforcement test:** parse the style, analyzer, describe and sampler modules with `ast`. Fail on any float literal, or any int literal outside {−1, 0, 1, 2}, unless it appears in an explicit allow-list with a reason. For example, the 45° and 60° flank angles are printability geometry, not tactile thresholds.

### Printer profile

```toml
[printers.louisville-library]
bed_mm = [152, 152, 158]
nozzle_mm = 0.5
grid_mm = 0.25
bed_margin_mm = 5
max_print_hours = 8                 # 0 = no limit
max_stl_mb = 0                      # 0 = no limit
filament_density_g_cm3 = 1.24       # PLA
slicer_config = ""                  # optional path to a PrusaSlicer/OrcaSlicer config for this printer
submit_notes = "Request via the library form. One colour. Up to 10 days."
```

### Analyzers

Each analyzer returns metrics and suggestions. A suggestion is `{severity, message, patch}`, where `patch` is the exact `update_model` change that applies it.

- **Relief:**
  - Reports the printed terrain relief above the base: the maximum, and the 98th-minus-2nd percentile spread.
  - If the spread is below `min_relief_mm`, it suggests the z exaggeration that brings the spread to `target_relief_mm`, rounded to 0.5. The suggestion is capped so the total height fits the printer.
  - It also flags an exaggeration that makes the model too tall for the bed.
  - It's skipped in flat mode.
- **Minimum width:** each style in use is checked against `max(min_line_width_mm, 3 × nozzle_mm)` for width and `min_line_height_mm` for height.
- **Bed fit:**
  - Compares the footprint and total height with `bed_mm` minus `bed_margin_mm`.
  - If they don't fit, it suggests the smallest round scale (multiples of 5 m/mm) that does.
- **Parallel spacing:**
  - Finds places where two different line features run with less than `min_parallel_spacing_mm` between their edges for more than `min_feature_length_mm`.
  - Reports the five worst places with positions.
- **Resolution:** compares the source DEM's ground cell with the grid's ground cell and says which way detail is lost.

### describe_model details

**Output rules:**

- Markdown: a `#` title, `##` sections, `###` entities (one per named feature, so a stream drawn in two styles is one entry) and `-` bullets for facts, so a heading search finds a feature
- short lines
- units on every number
- tables of at most four columns
- positions in print mm
- no mention of images or colours

**Sections, in order:**

1. **Summary:**
   - footprint x × y × total height
   - scale ("1 mm = 125 m") and vertical exaggeration
   - mode, tactile profile and printer
   - file paths
2. **Orientation:** north is the far edge (y maximum), and the origin is the south-west corner.
3. **High and low points:**
   - the five highest local maxima of the terrain, each the highest point within `summit_radius_mm` (a describe setting in the user config, default 10 mm)
   - each one named after the nearest OSM peak within 3 mm of print distance, if there is one
   - for each: position, printed height and real elevation
   - the lowest point, in the same form
4. **Line features**, one paragraph each, longest first:
   - Walk the simplified line and classify each step by 8-point compass bearing. Merge consecutive steps with the same bearing into runs, and absorb runs shorter than `describe_min_run_mm` (default 10 mm) into a neighbour.
   - Report where it enters (the edge and coordinate, or "starts at (x, y)"), each run's direction and length, named points within 5 mm of run ends, and where it exits.
   - For lifts: bottom and top terminal positions with elevations, the length, and the direction.
5. **Crossings:** every intersection between different features, with its position and which one is on top (the taller profile).
6. **Close parallels:** the same places the spacing analyzer finds.
7. **Cross-sections:**
   - east–west at 25%, 50% and 75% of y, and north–south at 50% of x, as heights every 10 mm
   - extra `sections` every 5 mm, given as `{"y_mm": ...}`, `{"x_mm": ...}` or `{"through": "<feature or point name>", "direction": "EW" | "NS"}`
8. **Tactile legend:** one line per style in use, giving the profile, width and height, and what it means in this model.
9. **Distortion:** every warp and regional z scale with its ratios. In Phase 1 this says there's no horizontal distortion and gives the uniform exaggeration.
10. **Attribution:** one line.

On a sampler plate, sections 3–7 are replaced by a row-by-row readout of every sample.

### check_print and the print pack

- **Mesh checks:** watertight, volume, and the minimum feature check from the analyzers.
- **Volume and filament:** reports the volume in cm³, and the solid mass (`volume × filament_density_g_cm3`), labelled as an upper bound.
- **Slicer:**
  - Looks for `prusa-slicer` or `orca-slicer` (or `prusa-slicer-console` on Windows) on PATH.
  - If one is found and the printer has a `slicer_config`, slices and reads back the estimated time and filament, then compares the time with `max_print_hours`.
  - Otherwise, says the print time is unavailable and repeats the printer's time limit.
- **`PRINT-NOTES.txt`:**
  - footprint and height
  - "flat side down, no supports"
  - suggested layer height (0.2–0.3 mm)
  - the filament figures
  - what the object is, in one sentence
- **`SUBMIT-NOTES.txt`:**
  - the printer's `submit_notes`
  - a two-sentence description for print staff, for example: "Tactile terrain map for a blind user. Any single high-contrast colour is fine."

### Sampler plate layout

- **Size:** at most 140 × 120 mm (the profile's `plate_width_mm` and `plate_height_mm`), clamped to the printer's usable bed, with a 3 mm base recorded in the sampler's spec. The plate is sized to its content. Sample lines run east-west. If the rows do not fit, samples shorten by `length_shrink` per step (down to `min_sample_length_mm`) and the readout says so; if that is not enough within the preferred size, the whole usable bed is tried, and after that the user is told to use `focus`. The sampler's `kind: "sampler"`, `focus`, `seed` and the actual `sample_length_mm` are stored in the spec, and the plate is rebuilt from them. A sampler is not edited with `update_model`; make a new one.
- **Rows:** separated by smooth 8 mm gutters, and each sample is `sample_length_mm` long:
  1. **Profile pairs** at the road width and height, with `pair_gap_mm` between the two samples in each pair: rounded|flat_top, rounded|pointed, flat_top|pointed, plus controls rounded|rounded and flat_top|flat_top.
  2. **Widths:** rounded, at each of `widths_mm`, at a fixed height.
  3. **Heights:** rounded, at a fixed width, at each of `heights_mm`.
  4. **Parallel spacing:** pairs of lines at each of `spacings_mm`.
- **Order:** the profile-pair row is shuffled with a seed recorded in the spec (cell order, and which line of a pair is upper), so position gives nothing away. Widths, heights and spacings keep their natural order. The readout reveals which pairs are controls, so the user should feel the plate first.
- **IDs (invariant 3):**
  - The row number is a count of notches on the left edge, sized `notch_width_mm` × `notch_depth_mm`.
  - The sample number (one per cell, so a pair shares one numeral) is a raised stroke numeral below each cell, `label_height_mm` tall with a `label_stroke_mm` stroke. Digits 0–9 are defined as polylines in the package (seven-segment style), drawn with the `flat_top` profile at `label_relief_mm`. There's no font dependency.
  - Braille is added only if `label_mode` asks for it. **Not implemented in 0.1.0:** a Braille `label_mode` is refused with a clear message, and numerals are always drawn.
  - Notches are slots lowered into the plate edge (to `max(base − notch_depth, label_relief)`), spaced one and a half notch widths apart and centred on the row.
- **Orientation:** one notch on the north edge.

### doctor

`doctor` is both a tool and a CLI command, and reports in text:

- package and Python versions
- the config path, and whether the models folder is writable
- the active tactile profile and printers
- whether each data endpoint is reachable
- the slicer found, or none

### Server hygiene

- Nothing but protocol messages goes to stdout; logging goes to stderr.
- Heavy libraries are imported inside tools, so the server starts quickly.
- Long builds report progress through MCP progress notifications.
- The MCP server's `instructions` field carries a short version of the workflow (resolve, confirm, create, describe, check), so clients without the skill still get it.

## Extensibility

Everything above is the full vision, not the first build. Build a small MVP, but put the extension points in from day one, so each later feature is a new implementation of an existing interface rather than a refactor.

### Pipeline

The build is a fixed sequence of stages:

`fetch → project → warp → heightfield (z scale) → texture → line features → base → tile → export`

- Each stage is a pure function of the spec plus the previous stage's output, and its result is cached by a hash of its inputs.
- A stage with nothing to do is a no-op, not a missing stage. In the MVP, warp, texture and tile pass their input through unchanged, so adding them later doesn't touch the pipeline.

### Registries

Each of these is an interface plus a name-keyed registry. Loading them through Python entry points lets third parties add implementations without forking.

| Interface | MVP implementations | Later |
|---|---|---|
| `ElevationProvider` | USGS 3DEP | Copernicus GLO-30/90, local GeoTIFF |
| `LineProvider` | NHD, OSM (roads, lifts) | HydroRIVERS, OSM trails/pistes, GPX/GeoJSON files |
| `AreaProvider` | — | OSM/Natural Earth water, user polygons |
| `LineStyle` (cross-section profile + pattern) | rounded, flat-top | dotted, terminal bumps, user-defined |
| `Texture` (displacement function) | — | compressed, z_altered, water, stipple, crosshatch |
| `Warp` (forward map + fold-over check) | identity | band, polygon |
| `Analyzer` (metrics + suggestions) | relief, min width, bed fit | spacing, density, resolution, textures, slicer |
| `Joint` | — | dovetail, pin |
| `Exporter` | STL | 3MF (separate bodies), tiled set |

### Spec

- A versioned schema (pydantic), with `schema_version` and migration functions.
- Validation rejects unknown keys and unknown registry names with a clear message. Never ignore them silently.
- Reserve the `regions`, `tiles` and `textures` keys from the start, even before they do anything.

### MCP tools

- New capabilities show up as new spec fields and registry names, not as new tools. `create_model` and `update_model` stay the main entry points.
- Add a `list_capabilities` tool that returns every registry, its names and parameters, and a one-line description of each. The LLM uses it to discover what's possible instead of relying on the skill text, which goes out of date.

### Tests

- Synthetic elevation grids (a cone, a plane, a valley) for exact-answer tests of the warp, z scale and analyzers.
- A small number of cached real tiles as golden tests.
- Every generated mesh must be watertight. Make that a test assertion, not just a check.

## Roadmap

### Phase 1: MVP (target: one weekend or less)

- the pipeline and registries above, with identity or no-op stages where needed
- the US provider: 3DEP elevation, NHD rivers, and OSM roads and lifts
- terrain and flat modes
- rounded, flat-top and pointed line styles, with configurable width and height. Lifts use pointed until terminal bumps exist (Phase 3).
- `resolve_area`, `create_model`, `update_model`, `describe_model`, `list_capabilities`
- `analyze_model` with the relief, minimum width and bed-fit analyzers, including the suggested z exaggeration and the closest spacing between parallel lines
- `check_print`: watertight, volume and filament upper bound, the print pack, and the slicer estimate when a slicer is installed
- printer profiles in the user config
- STL export and the attribution file
- tactile profile file, sensitivity presets, and a single-round sampler plate (`create_sampler`)
- **Validation:** the Winter Park model, in both terrain and flat versions

### Phase 2: big regions

- global providers (Copernicus, HydroRIVERS, coastline and water areas)
- automatic projection choice
- the band warp, regional z scale and texture library
- tiles with dovetails, the test coupon, Braille tile IDs and orientation notches
- the remaining analyzers
- `calibrate` and adaptive second-round sampler plates
- **Validation:** the India and Pakistan model

### Phase 3: polish

- polygon warp
- trails, ski runs, dotted and terminal-bump line styles, crossing gaps
- labels in Braille or embossed text
- 3MF export with features as separate bodies for multicolor printing
- slicer integration
- AI-proposed region morphs: for example, detect large low-relief areas and suggest compressing them

## Skill content (thin)

- **Workflow:** run `resolve_area`, then confirm the parameters back to the user in one line, then `create_model`, then always `describe_model`, then `check_print` before calling the model done.
- **Defaults:** load them from the user config.
- **Rules of thumb:**
  - Vertical exaggeration: about 3× for plains or gentle terrain, about 1 to 1.5× for mountains.
  - Filter creeks by stream order and add named exceptions.
  - Keep features 1.2 mm wide or more.
- **Output:** report results as structured text with headings. Never point the user at images.

## Open questions

- The library's nozzle size and slicer, and whether the larger SideKick 747 can be used. The library's request limits are known: 152 × 152 × 158 mm, 8 hours, PLA, one colour, 5 prints a month. See [plans/printing-access.md](../plans/printing-access.md).
- The friend's printer: model, bed size, nozzle, and slicer.
- Network access from the MCP server when the Claude app launches it. Direct access from this machine to 3DEP, NHDPlus HR and Overpass was confirmed on 2026-10-23.
- Whether NHDPlus HR or the simpler 3DHP/NHD service is easier to query for a bounding box. Try NHDPlus HR first, with medium-resolution NHDPlus V2 as the fallback.
- License for the repository: AGPL-3.0-or-later for the code (decided 2026-10-24), so anyone running a modified version as a hosted service must offer its source to users. The data licenses are separate and handled through the attribution file.
