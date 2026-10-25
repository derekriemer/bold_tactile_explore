# Winter Park prototype plan

The first real model and the acceptance test for Phase 1. You know this area, so `describe_model` and the prints are checked against your knowledge, not against a picture.

## Area

Starting bounding box, to be confirmed with `resolve_area` before building:

| Edge | Value | Why |
|---|---|---|
| West | -105.86 | Catches Vasquez Creek and the west side of Vasquez Ridge |
| East | -105.71 | Catches the Second Creek cirques and the east side of Berthoud Pass |
| South | 39.79 | Just south of Berthoud Pass summit |
| North | 39.96 | Just north of the town of Fraser |

That is roughly 12.8 km east–west by 18.9 km north–south, UTM zone 13N (EPSG:32613).

Things to check in the `resolve_area` output before building:

- Fraser River appears and is named.
- Second Creek and Vasquez Creek appear by name (and under which exact spelling).
- US-40 appears, with `ref = US 40`, including the Berthoud Pass switchbacks.
- Lift count looks right for Winter Park + Mary Jane. If OSM is missing or has extra lifts (closed, magic carpets), we see it here.
- Elevation min near the Fraser valley floor (~2,600 m) and max near 4,000 m.

If the box clips something you care about (for example the full Second Creek headwall, or Parsenn Bowl), widen it then; it's one `update_model` call.

## Print settings

| Setting | Value | Note |
|---|---|---|
| Scale | 100 m per mm, or 125 m per mm for the library | Per the spec's printer-dependent scale. Set with `scale_m_per_mm` rather than `long_side_mm`, so the describe text gives a round number. The models are `winter-park` and `winter-park-library`. |
| Vertical exaggeration | 1.5× | Spec value; mountains rule of thumb 1–1.5× |
| Base | 3 mm | |
| Grid cell | 0.2 mm (≈20 m ground) | From printer config |
| Elevation | 3DEP 10 m | 1 m would be averaged away at this cell size; `analyze_model` should say so if asked for 1 m |
| Tactile profile | `standard` (or your own, after the sampler) | |

Expected at 1 mm = 100 m: relief ≈ 14 mm at true scale, ≈ 21 mm at 1.5×, total height ≈ 24 mm with the base. At 1 mm = 125 m: ≈ 17 mm at 1.5×. Relief analyzer should *not* suggest more exaggeration (21 mm is over the 8 mm comfort threshold); if it does, that's a bug.

## Features

| Feature | Source | Filter | Style (standard profile) |
|---|---|---|---|
| Fraser River | NHD | name, plus stream order ≥ 4 if anything else qualifies | rounded, 1.6 × 1.0 mm |
| Creeks | NHD | stream order ≥ 3 (tune from `resolve_area` counts), always include Second Creek, Vasquez Creek | rounded, 1.2 × 0.7 mm |
| Roads | OSM | `motorway`, `trunk`, `primary`, always include ref US 40 | flat-top, 2.0 × 1.5 mm |
| Lifts | OSM | all `aerialway` lines except `magic_carpet`; drop any shorter than the profile's minimum feature length | pointed, 1.2 × 1.2 mm |

Lifts use the pointed profile in Phase 1 because terminal bumps are Phase 3. Whether pointed vs rounded vs flat-top is distinguishable is exactly what the sampler measures; if it isn't for you, the fallback is to separate lifts by height (taller than creeks) and accept fewer categories.

## Spec files

Two models, same data cache:

- `winter-park` — `mode: "terrain"`
- `winter-park-flat` — `mode: "flat"`, same features, same scale, base 3 mm, flat-mode style heights from the profile (no terrain to compete with)

Reference copies of both specs go in `examples/` so the build is reproducible without the conversation.

Optional third model, recommended before the full print:

- `winter-park-cirques` — crop to about 5 × 5 km around the Second Creek cirques at the same scale and exaggeration (≈50 × 50 mm, short print). Tests success criterion 1 (do the cirques read from terrain alone?) for a fraction of the print time.

## What describe_model should say (spot checks for you)

You'll be the judge, but these are the things to listen for:

- Fraser River enters near the south edge (draining off Berthoud Pass), runs roughly north through the valley, past the Winter Park base, and exits the north edge near Fraser.
- US-40 runs alongside the Fraser for most of the length, with the switchbacks up to Berthoud Pass near the south edge. Expect several "road over river" crossings in the valley.
- Second Creek comes in from the east above the valley, south of the resort.
- Vasquez Creek comes in from the west/southwest and joins near the town of Winter Park.
- Lifts are clustered around the Winter Park and Mary Jane bases with top terminals on the ridges.
- The highest points are on the Continental Divide along the east and south edges.

For the cirques, add a cross-section request through them: `describe_model` takes optional `sections` (e.g. `[{"through": "Second Creek", "direction": "EW"}]` or `{"y_mm": 40}`), so the text profile shows the bowl shape as heights every 5 mm.

## Validation protocol

1. **Sampler first** (`create_sampler("standard")`). Print it, feel it, write results into `plans/winter-park-results.md` (pairs you can't tell apart, smallest width you can find, where parallel lines merge). Adjust a personal profile by hand (Phase 1 has no `calibrate`).
2. **resolve_area** on the bbox; adjust bbox and stream-order cutoff from its counts.
3. **create_model** `winter-park` through the skill. Read `analyze_model` warnings, especially line spacing around the lift bases.
4. **describe_model**: check against the spot checks above. Every wrong or missing item is either a data problem (bbox, filter, OSM tagging) or a describe bug; record which.
5. **check_print**: must report watertight.
6. **create_model** `winter-park-flat`, describe, check.
7. **Print** `winter-park-cirques` (if made), then `winter-park-flat`, then `winter-park`.
8. Record outcomes against the success criteria below in `plans/winter-park-results.md`.

## Success criteria (from the spec) and how each is measured

| Criterion | Measured by |
|---|---|
| Second Creek cirques read clearly from terrain alone | Cirque crop print, by touch; cross-section text shows a bowl with a headwall ≥ 3 mm |
| Fraser River and US-40 can be followed and told apart | Full print, by touch; flat print as the easier version |
| Lifts distinguishable from roads and creeks | Full and flat prints; sampler row 1 predicts the answer |
| describe_model matches your knowledge | Step 4 checklist, all items correct or explained |
| Watertight | `check_print` and the test suite |

## Likely problems to watch for

- **Lift crowding at the bases.** Several lifts load within a few hundred metres, which is a few mm at this scale. The spacing check will flag it; options are dropping lifts by name, or accepting merged lines near terminals.
- **US-40 and Fraser River overlap.** In the narrow parts of the valley the road and river may be closer than the minimum spacing. The road (taller) wins where they overlap; describe text should mention where they run within 3 mm of each other.
- **OSM lift data** may be out of date for recent lift replacements. `resolve_area` lists lift names so you can catch this before printing.
- **Valley floor flatness.** At 1.5×, the valley floor around Fraser will be nearly flat; that's correct, not a bug.
