# Dashed lines: integrating dash-trails

Branch: `feature/dash-trails-integration` (fork `brianhinch/bold_tactile_explore`).
Status: implemented on the branch (steps 0–5). `scripts/verify_dash.py` passes; see `dash-trails-verification.txt` and `dash-trails-baseline.txt`.

## Decisions (2026-11-25)

- **Golden "on" output:** dash-trails 1.0.0's own output on the pre-dash print-pack STL. The Nov 7 hand-made files aren't reproducible by 1.0.0, so they are not used as gates.
- **Default block height:** 2 mm, the next step up from the script's 1 mm default. Golden: `additions/golden/tilden_dashed_2mm_v1.stl`. A 1 mm golden (`tilden_dashed_1mm_v1.stl`) checks that profile overrides work.
- **Other block sizes:** width, length and gap are 2 mm, the script defaults. All four presets use the standard values until they are tuned.
- **Size limit:** a printer's STL size limit thins the terrain before the blocks are added.
- **No blocks:** when no line is long enough for a block, the solid export is kept, so no line is lost.
- **Saved specs:** `line_render` is left out of saved specs when it equals the default, so older spec files stay byte-identical.
- **scikit-image 0.26:** under 0.26, 1.0.0's positional `remove_small_objects(mask, n)` behaves as `max_size=n`. The port calls it that way, with no deprecation warning.
- **Export cache fix:** a cached export is reused only if the STL's hash still matches. Before this, an undo could leave the previous version's STL on disk. This was an upstream bug.

The sections below are the original plan, kept for reference.

## Goal

Build the `dash-trails` stand-alone tool (`../additions/dash-trails/dash_trails.py`, v1.0.0) into the build pipeline. It turns raised line ridges into a dashed row of raised blocks. It is a spec option that can be turned on or off, and it is **on by default in this fork**.

The tool calls them "trails", but it acts on every raised line on the map. On the Tilden sample those are the roads and creeks.

Acceptance, on the Tilden sample:

| Dash setting | Must produce |
|---|---|
| off | `tilden_berkeley_sample.stl` (the print-pack file from before dash-trails) |
| on, tall dashes | the dashed reference (see "What was found") |

## What was found before planning (2026-11-25)

These were measured, not assumed.

1. **The "off" target can be reproduced.** I rebuilt from `spec.json` and the model's `cache/` folder, with the stage pickles deleted, in a temporary config. It needs a printer named `bambu-a1-mini` with `grid_mm = 0.2` and no STL size limit. That printer is only in the original machine's config. The result has the same 1,287,994 faces in the same order. The largest vertex difference is 0.0000019 mm, which is float32 rounding. The bytes differ, so tests must compare geometry, not file hashes.
2. **The "on" target cannot be reproduced exactly by today's script.** `additions/tilden_berkeley_dashed_trails.stl` (the tall reference) is dated Nov 7. `dash_trails.py` v1.0.0 is dated Nov 11, and `dash-trails.zip` holds the same v1.0.0. I ran v1.0.0 on the "off" STL with `--height 1`, `2`, `3` and `4`. None matches the tall reference or `_1mm` reference in faces, volume or geometry. About 3% of top-surface cells differ by more than 0.2 mm.
3. **The tall reference is very probably `--height 4`.** Volume grows by about 936 mm³ for each mm of height, and the tall reference is +2,820 mm³ over the 1 mm reference. That matches a 3 mm increase, so a block height of 4 mm.
4. **Baseline test suite:** `uv run pytest -q` gives 198 passed, 1 deselected (network), in 60 s.
5. **Cost:** dash-trails takes about 18 s on the Tilden map (800 × 801 grid at 0.2 mm) and finds 27 segments and 234 blocks.

**Decision needed before step 1:** what is the "on" golden file? Recommended: the output of dash-trails v1.0.0 with `--height 4` on the "off" STL, after you check it by hand as you did the Nov 7 file. The Nov 7 file stays as a reported similarity score, not a pass/fail gate. Otherwise we would need the older script that made it.

## Design

### Where it runs

Add one stage, `dash`, between `tile` and `export`. It takes the composed `Heightfield` and returns it with two fields set:

- `dash_z`: the surface with the ridges filled back into the ground.
- `dash_blocks`: the placed blocks, each with centre, direction, bottom z and top z.

The stage runs only when dashing is on. When it is off it returns its input unchanged, so the off path is byte-for-byte today's pipeline. That is what makes the "off" acceptance safe.

`export` checks for blocks. With none it does exactly what it does now. With blocks it builds the solid from `dash_z`, adds the blocks with a `manifold3d` union, and writes the result. manifold3d is already a dependency.

### Faithful port first

Port the detection, ridge removal, centreline and placement functions from v1.0.0 verbatim into `src/tactile_terrain/dashes.py`. Two details keep it identical to the stand-alone tool:

- Round `hf.z` to float32 before detecting. The stand-alone tool reads z back from a float32 STL, and its thresholds (`L > 0.13`, `tophat > 0.2`) could flip on a value right at the edge.
- Use the tool's own `heightfield_solid` and boolean code for the dashed path, not `mesh.heightfield_to_mesh`. Manifold's output depends on the input triangulation.

A later improvement could use the pipeline's own knowledge instead of detection: `hf.terrain_z` is already the ground without ridges, and `hf.lines` are the true centrelines. That would be more robust and allow per-feature dashing. But it will not match the stand-alone output, so it is a separate follow-up with its own golden file.

### The option

- **Spec:** add `style.line_render: "solid" | "dashed"` to `Style`. The default is `"dashed"` in this fork, set by a single constant (`DEFAULT_LINE_RENDER`) so an upstream PR can flip it to `"solid"` in one line.
- **Existing specs:** a spec without the field gets the default, so old models rebuild dashed after this change. Note it in `model_history` or the build summary.
- **Turning it on and off:** `update_model` takes it like any other style change, so undo works.
- **CLI flag:** `tactile-terrain build --solid-lines/--dashed-lines` overrides the spec for one build.
- **Cache key:** the `dash` stage's `spec_slice` is `[style.line_render, profile.dashes]`.

### Tactile sizes come from the profile (invariant 1)

Block height, width, length and gap are tactile parameters, so they must not be hard-coded. Add a `[dashes]` table to `TactileProfile` and to all four presets:

```toml
[dashes]
height_mm = 4.0    # standard = the "tall dash" you checked by hand; confirm
width_mm = 2.0
length_mm = 2.0
gap_mm = 2.0
```

`fine`, `coarse` and `extra_coarse` get scaled values. Ask before choosing them.

These stay as constants, allowlisted with a reason:

- `embed` (0.6 mm) is how far blocks sink into the ground. It is printability geometry, not a tactile setting.
- The detection tuning numbers (`2.0` mm opening radius, `0.13` curvature, `0.2` mm tophat, `8.0` mm² noise, `6.0` mm spurs) are image-processing parameters, not tactile ones.

Add `dashes.py` to `SCANNED` in `tests/test_no_hardcoded_tactile.py`, and give each constant its own allowlist line.

The sampler (invariant 2) should be able to test dash sizes. That is a follow-up, listed below, so this change does not grow.

### Text output (invariant 4)

- **`describe_model`** says lines are dashed and gives the block length, gap, width and height. It reports how many blocks were placed and any segments dropped (stubs, junction crowding, map edge). These come from the `dash` stage result, not a re-detection.
- **Print notes:** "are raised lines" becomes "are raised dashed lines of blocks" when dashing is on.
- **Warnings:** the stand-alone tool's "things to check" become analyzer warnings in plain text:
  - two touching lines merged into one dashed line
  - a short stub missed at a corner
  - short blocks on steep slopes
- **Golden snapshot:** `tests/fixtures/describe_snapshot.txt` is regenerated on purpose, and the diff is reviewed.

### Dependencies

Add `scikit-image` and `skan`. Both are BSD-3, which is allowed. `skan` pulls in `numba`, `pandas` and `matplotlib`, which is heavy. Record the licence re-check in `CONTRIBUTING.md`. Drop the PNG preview. If it stays, it goes behind an optional extra, because images are optional (invariant 4).

### Size limit

When a printer has `max_stl_mb` and dashing is on, decimate the heightfield solid first, then add the blocks. Booleans on the full 1.29 M-face solid are fine (about 18 s), but the size check must count the final mesh.

## Test plan

Everything below runs with one command, and none of it needs anyone to look at a picture.

### Fixtures

- `tests/fixtures/tilden-cache/`: the Tilden `nhd`, `osm` and `usgs3dep` cache files (about 3.6 MB). With these, Tilden builds offline in the tests, like the existing Winter Park golden tile.
- `tests/fixtures/tilden-config/config.toml`: a printer named `bambu-a1-mini` with `grid_mm = 0.2` and no size limit, loaded through `TACTILE_TERRAIN_CONFIG_DIR`.
- **Geometry fingerprints** in `tests/fixtures/golden/*.json`. The STLs themselves are 64 MB each, too large for git, so only fingerprints are committed. A fingerprint holds:
  - face count, watertight flag, bounds and volume
  - a SHA-256 of the triangles rounded to 1e-4 mm and sorted
  - a 0.2 mm top-surface height grid, saved as a compressed `.npz` of about 1 MB, so a failure can say where it differs
- **Full reference STLs** stay outside the repo. Point `TACTILE_GOLDEN_DIR` at them. Tests that need them are skipped with a plain reason when it is not set.

### Comparing meshes

Add `tests/golden.py` with one function, `compare(mesh_a, mesh_b) -> Report`. Pass/fail is decided on the triangles rounded to 1e-4 mm. The report gives:

- a plain-text summary: faces, volume difference, largest height difference, and the share of 0.2 mm cells that differ by more than 0.05 mm
- the five worst places, as print-mm coordinates with compass words

Every golden test uses it, so a failure reads like the analyzers' output.

### Step 0: baseline, before any code changes (first commit on the branch)

Mark these tests `golden`. They are excluded from the default `pytest` run, like `network`.

1. `test_baseline_off_rebuild`: build Tilden offline from the fixtures and check it matches the "off" fingerprint. This passes today, as measured above.
2. `test_baseline_standalone_dash`: run the stand-alone v1.0.0 on the rebuilt "off" mesh with the golden settings. Import it from `../additions/dash-trails/` or from a vendored copy in `tests/oracle/dash_trails_v1.py`. Check it matches the "on" fingerprint. This pins the oracle, so a dependency upgrade (scikit-image, manifold) that changes the result shows up as an oracle failure, not an integration failure.
3. `test_baseline_suite`: the full default suite and `ruff` still pass (198 passed).
4. `scripts/verify_dash.py --baseline` runs all of the above and writes `plans/dash-trails-baseline.txt`. That file records the versions, timings and results, and is committed.

### Steps 1 onwards: after integration

Fast unit tests. These run in the default suite and use synthetic grids from `tests/synthetic.py`.

- **Detection:** a crisp raised line on a slope is detected. A smooth natural ridge is not. A short, uneven outcrop is dropped.
- **Ridge removal:** inside the band the surface sits within 0.05 mm of the original ground, and nothing changes outside the dilated band.
- **Placement:**
  - blocks are spaced `length + gap` apart
  - blocks are turned to follow the line
  - no block hangs off the edge
  - no two blocks are closer than the minimum separation
- **Mesh:** the result is watertight and a single body, and its volume equals the terrain plus the blocks to within 1%.
- **Profile:** changing `dashes.height_mm` in `style.overrides` changes the block tops and nothing else.
- **Option:**
  - with the default spec the result is dashed
  - `"solid"` gives exactly the pre-change mesh
  - toggling with `update_model` and then undoing gets back the same file
- **Cache:** changing `line_render` re-runs only `dash` and `export`.
- **Invariant 1:** `test_no_hardcoded_tactile` scans `dashes.py`.

Equivalence tests. These are marked `golden`.

- **Port matches stand-alone tool on Tilden:** `dashes.apply(hf)` gives the same blocks and mesh as the oracle run on the same STL.
- **Port matches stand-alone tool on Winter Park:** same check on the Winter Park map built from the existing `tests/fixtures/winter-park-cache`. A second map catches anything tuned to Tilden.
- **End-to-end off:** a Tilden build with `"solid"` matches the "off" fingerprint.
- **End-to-end on:** a Tilden build with the default setting matches the "on" fingerprint.
- **Nov 7 reference:** with `TACTILE_GOLDEN_DIR` set, the build is compared to `tilden_berkeley_dashed_trails.stl` and the similarity is reported as information, not pass/fail, unless you pick that file as the golden.
- **Text:** the `describe_model` snapshot and print notes mention dashes. The analyzer warnings appear in the check report.

### One command

```bash
uv run python scripts/verify_dash.py
```

It runs `ruff`, the default suite, and `pytest -m golden`. It then writes a plain-text report to `plans/dash-trails-verification.txt` and prints it:

- each check, pass or fail
- the comparison report for each golden test
- timings, against the baseline file

It exits with a non-zero status if anything fails. `--baseline` writes the baseline file instead. Claude runs it at the end of every step below and does not move on until it passes.

## Steps

Each step is one commit and must pass `verify_dash.py` first.

0. **Fixtures and baseline.** Add the fixtures, `tests/golden.py`, the oracle, the golden tests, `verify_dash.py` and the baseline file. Integration tests are written now but marked `xfail(strict=True)` until their step, so they cannot pass by accident.
1. **Port** `dashes.py` with unit tests and the port-equivalence tests. It is not wired into the pipeline yet.
2. **Profile `[dashes]`** in all presets, plus the allowlist and the scanner update.
3. **Spec option** and the fork default, the `dash` stage, the dashed export path and the cache key. The end-to-end tests stop being xfail.
4. **Text output:** `describe_model`, print notes, analyzer warnings and the snapshot.
5. **Dependencies, licence note,** and README and skill text (`skills/tactile-terrain/SKILL.md`) explaining the option.

## Follow-ups (separate work)

- **Native dashing** from `hf.terrain_z` and `hf.lines`, with no detection. This gives per-feature styles (roads dashed, creeks solid) and needs its own golden file.
- **Sampler rows** for dash length, gap and height (invariant 2).
- **Upstream PR** to Derek's repo with the default flipped to `"solid"`.
