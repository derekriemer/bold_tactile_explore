# Winter Park results

Run on 2026-10-24 from the Python API and the `tactile-terrain` command line, not yet through the Claude plugin. The checks that need the user are listed at the end.

## Models built

| Model | Printer | Scale | Footprint | Total height | STL | Triangles |
|---|---|---|---|---|---|---|
| winter-park | generic-220 | 1 mm = 100 m | 129.8 × 189.8 mm | 25.3 mm | 62.1 MB | 1,241,390 |
| winter-park-library | louisville-library | 1 mm = 125 m | 103.8 × 151.8 mm | 20.8 mm | 25.5 MB | 509,942 |
| winter-park-flat | louisville-library | 1 mm = 125 m | 103.8 × 151.8 mm | 4.5 mm | 25.5 MB | 509,942 |
| winter-park-cirques | louisville-library | 1 mm = 125 m | 40.0 × 41.0 mm | 15.2 mm | 2.7 MB | 54,424 |
| sampler-standard | louisville-library | not applicable | 134.0 × 101.5 mm | 4.5 mm | 22.0 MB | 440,884 |

All five pass `check_print` for watertightness and valid solids. Build time with cached data was 1 to 3 seconds for the big models. A cold build of the cirques crop took 54 seconds, mostly the NHD download.

Terrain range is 2,588 m to 4,071 m. The relief analyzer reports 18.1 mm of spread at 100 m per mm and does not ask for more exaggeration, as the plan expected.

## Checks against the plan's spot checks

- Fraser River appears, named, and runs south to north through the area.
- US 40 appears with ref `US 40`.
- Second Creek is only stream order 1 in NHD HR. It appears only because the spec names it. Without `include_names` it would be missing.
- 29 aerialways in the full area, 18 chair lifts, 2 gondolas, 5 magic carpets (excluded), 3 rope tows and 1 T-bar.
- Named peaks include Parry Peak (4,076 m), Mount Eva, Mount Flora, Vasquez Peak and Witter Peak. Berthoud Pass is found as a pass.
- Highest points in the describe text match the real elevations within about 10 m.

## Problems found

Each is classed as a data issue, a describe bug, an analyzer bug, a server bug or a skill fix.

| # | Class | Problem | Status |
|---|---|---|---|
| 1 | analyzer bug | Three 0.4 mm nozzles is 1.2000000000000002 in floating point, so a 1.2 mm line was reported as below a 1.2 mm minimum, with that value as the fix. | Fixed, with a test. |
| 2 | analyzer bug | Consecutive pieces of one road (a named and an unnamed piece of US 40) were reported as close parallels. | Fixed, with a test. Pieces of the same feature type that touch are skipped. |
| 3 | data issue | `winter-park-library` does not fit the Louisville bed once the 5 mm margin is applied: the usable bed is 142 × 142 mm and the print is 103.8 × 151.8 mm. `analyze_model` correctly suggests 135 m per mm. The plan's 125 m per mm assumed the whole 152 mm. | Open. The user should choose: scale 135, a smaller margin, or a smaller bounding box. The examples are unchanged. |
| 4 | data issue | The river and creek features overlap: creeks of order 3 or more include the rivers of order 4 and above, and Vasquez Creek is added by name to both. `describe_model` lists such lines twice, once per style. The taller style wins on the model, so printing is not affected. | Open. A `max_stream_order` filter, or removing Vasquez Creek from the creek list, would remove the duplicates. |
| 5 | data issue | US 40 runs along the Fraser River for about 87 mm in the library model, with the two lines merged. This is real geography, but it means the road and river cannot be told apart there by touch. | Open. Needs a decision, for example a different road height or leaving the river out where the road follows it. |
| 6 | data issue | The `standard` profile's `rounded_minor` and `pointed` lines are 1.2 mm wide, which is below three nozzle widths (1.5 mm) on the Louisville 0.5 mm nozzle. The analyzer warns and gives the fix. | Open. Apply the fix or change the profile after the sampler. |
| 7 | server bug | The Overpass status check in `doctor` timed out once and passed another time. Public Overpass servers are sometimes slow. | Open, low priority. |
| 8 | analyzer limit | A sampler plate for a `coarse` profile does not fit the Louisville bed with all four rows. `create_sampler` says so and suggests `focus`. | Open. |
| 9 | not built | Braille labels on the sampler are refused with a clear message. Numerals and notches are always present. | Deferred. |

## Needs the user

1. Read the `describe_model` text for `winter-park-library` and `winter-park-cirques` and compare it with what you know of the area. Record each wrong or missing item here as a data issue or a describe bug.
2. Run the plugin test steps in `plans/claude-plugin-and-skill.md` (the "Winter Park test run" section) with Claude Code, and record anything the skill did wrong as a skill fix.
3. Decide problems 3 to 6 above.
4. Print the sampler first, then the cirques crop, then the flat model, then the full model, and record the results here.

## Crop and rescale iteration (2026-10-25)

- Crop: the original model rectangle x 0..129.8 mm, y 0..120 mm (south part, 100 m/mm) converted through the UTM 13N transform to the lon/lat box -105.86134, 39.78899, -105.7084, 39.89812 (about 13.2 km by 12.2 km). The box is a little wider than the rectangle because UTM grid north is rotated from true north.
- winter-park (generic-220, usable 210 by 210 mm): 63 m/mm, the smallest scale that fits. Footprint 209.2 by 194.0 mm, 35.2 mm tall. Was 100 m/mm.
- winter-park-library (Louisville, usable 142 by 142 mm): 93 m/mm. Footprint 141.8 by 131.2 mm, 24.8 mm tall. It now fits; the earlier overflow is closed.
- Water duplicates fixed in the lines stage: a river or creek reach already placed by an earlier water feature is not placed again, so "Fraser River (creek)" no longer repeats the river.
- Still open: Fraser River and US 40 run together; `rounded_minor` and `pointed` stay 1.2 mm wide, below the Louisville 1.5 mm minimum.
